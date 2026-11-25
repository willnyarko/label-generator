"""HTTP service exposing the label pipeline end to end, with its browser interface.

``create_app()`` returns a complete application: the interface at ``/`` and the
JSON API behind it. Anything that hosts it adds only its own concerns around it.

Nothing here reaches the network on its own. Collection identity can be supplied or
corrected through ``/api/identity``,
never fetched from ArchivesSpace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from label_generator_desktop import __version__

from ..engine.lrr.selection import Scope
from ..engine.notices import notice as input_notice
from ..engine.readers.detect import SUPPORTED_SUFFIXES
from ..engine.repositories import repositories
from ..content import add as add_content, content, say
from ..pipeline import DEFAULT_FORMATS, FORMATS, Labels, analyze, generate, select_labels, zip_download_name
from ..projections.html import render_box_html, render_folder_html
from ..projections.options import BoxFormatChoice, RenderOptions
from ..validation import ValidationError

add_content(Path(__file__).with_name("config") / "content.toml")  # the page's wording

INTERFACE_PAGE = Path(__file__).resolve().parent / "static" / "index.html"
ALLOWED_FORMATS = {*FORMATS, "all"}
UPLOAD_CHUNK_SIZE = 1024 * 1024


def render_interface() -> str:
    """The browser page with its wording filled in from config/content.toml.

    ``{{key}}`` in the page becomes that interface string, escaped for HTML.
    ``{{TEXT}}`` becomes the whole table as JSON, for the strings the page's
    script builds itself; ``<`` is escaped so no string can close the script tag.
    """
    ui = content()["interface"]
    page = INTERFACE_PAGE.read_text(encoding="utf-8")
    page = page.replace("{{TEXT}}", json.dumps(ui).replace("<", "\\u003c"))
    folder_error = ValidationError(input_notice("not-a-file", variant="folder")).to_dict()
    page = page.replace("{{FOLDER_ERROR}}", json.dumps(folder_error).replace("<", "\\u003c"))
    return re.sub(r"\{\{(\w+)\}\}", lambda m: escape(ui[m.group(1)]), page)


class IdentityRequest(BaseModel):
    """Operator-supplied collection identity for the current session."""

    token: str
    collection: Optional[str] = None
    call_number: Optional[str] = None
    repository: Optional[str] = None  # a short name from config/repositories.json


class GenerateRequest(BaseModel):
    """The choices a person made, sent with a request to write the labels."""
    token: str
    labels: Optional[Labels] = None
    scope: Scope = "all"
    choices: str = ""
    first_folder: int = Field(default=1, ge=1)
    numbering: Optional[Literal["continuous", "non-continuous"]] = None
    folder_generation: Literal["derive", "none"] = "derive"
    folder_layout: Literal["regular", "left"] = "regular"
    box_format: BoxFormatChoice = "auto"
    box_folder_text: Literal["show", "omit"] = "show"
    collection: Optional[str] = None
    call_number: Optional[str] = None
    repository: Optional[str] = None
    formats: list[str] = Field(default_factory=lambda: list(DEFAULT_FORMATS))


def create_app(
    *,
    feedback_url: Optional[str] = None,
    notice: Optional[str] = None,
    updater: Optional[Any] = None,
    on_opened: Optional[Callable[[], None]] = None,
    default_upload_bytes: int = 25 * 1024 * 1024,
) -> FastAPI:
    """Build the shared service application.

    ``feedback_url`` adds a "report a problem" link to the interface footer, so
    that a member of staff running a packaged copy has somewhere to send a
    defect without hunting for the project. It defaults to the
    ``LABEL_GENERATOR_FEEDBACK_URL`` environment variable, and no link is shown
    when neither is set.

    ``notice`` is a single line displayed above the interface, for a host to
    report something such as a newer build, which a packaged application cannot
    say on standard output.

    ``updater`` is an object with ``status()`` and ``start()``. When it is given,
    the notice shows an "Install and restart" button that calls it.

    Deployment concerns are intentionally absent. A host that needs them wraps
    the returned app with its own middleware.
    """
    feedback_url = (feedback_url or os.environ.get("LABEL_GENERATOR_FEEDBACK_URL", "")).strip()
    notice = (notice or "").strip()
    sessions: dict[str, dict] = {}
    max_upload_bytes = _positive_env_int("MAX_UPLOAD_BYTES", default_upload_bytes)
    session_ttl_seconds = _positive_env_int("SESSION_TTL_SECONDS", 60 * 60)

    def _cleanup_expired_sessions() -> None:
        cutoff = time.monotonic() - session_ttl_seconds
        expired = [t for t, s in sessions.items() if s["last_access"] < cutoff]
        for token in expired:
            session = sessions.pop(token, None)
            if session:
                shutil.rmtree(session["dir"], ignore_errors=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Remove every session's working files when the service stops."""
        yield
        for session in list(sessions.values()):
            shutil.rmtree(session["dir"], ignore_errors=True)
        sessions.clear()

    app = FastAPI(title="Label Generator", version=__version__, lifespan=lifespan)
    app.state.sessions = sessions

    @app.middleware("http")
    async def reap_sessions(request, call_next):
        """Before each request, drop expired sessions and refuse an upload already declared too large."""
        _cleanup_expired_sessions()
        declared = request.headers.get("content-length", "")
        if max_upload_bytes and declared.isdigit() and int(declared) > max_upload_bytes + UPLOAD_CHUNK_SIZE:
            return _error_response(_too_large(max_upload_bytes))
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unexpected(_request, exc: Exception):
        # Anything unforeseen still reaches the interface as a readable message.
        """Turn an unforeseen failure into a message the interface can show."""
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "ERR", "message": str(exc) or type(exc).__name__,
                               "fix": say("service.unexpected_fix")}},
        )

    def _session(token: str) -> dict:
        """The session for ``token``, refreshed as in use; a missing one is reported as gone."""
        sess = sessions.get(token)
        if not sess:
            raise HTTPException(status_code=404, detail=say("service.session_gone"))
        sess["last_access"] = time.monotonic()
        return sess

    def _analyze_session(sess: dict, **kwargs):
        """Read with this upload's header choice and this request's identity."""
        options = {key: sess.get(key) for key in ("collection", "call_number", "repository", "header_rows")}
        options.update(kwargs)
        return analyze(sess["input"], **options)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        """The browser interface."""
        return HTMLResponse(render_interface())

    @app.get("/health")
    def health() -> dict:
        """A liveness check for hosts and the desktop shell."""
        return {"status": "ok", "app": "label-generator"}

    @app.get("/api/config")
    def api_config() -> dict:
        """Host-supplied extras the interface renders if present."""
        return {
            "version": app.version,
            "feedback_url": feedback_url,
            "notice": notice,
            "update": updater is not None,
            "confirm_open": on_opened is not None,
            "repositories": [{"code": r.code, "name": r.display} for r in repositories()],
        }

    @app.post("/api/update/opened")
    async def api_update_opened():
        nonlocal on_opened
        if on_opened:
            on_opened()
            on_opened = None
        return {"ok": True}

    @app.get("/api/update")
    def api_update_status() -> dict:
        """Where an installation of a newer version has got to."""
        if updater is None:
            raise HTTPException(status_code=404, detail="No update is available.")
        return updater.status()

    @app.post("/api/update")
    def api_update_start() -> dict:
        """Download and install the newer version, then restart."""
        if updater is None:
            raise HTTPException(status_code=404, detail="No update is available.")
        return updater.start()

    @app.post("/api/analyze")
    async def api_analyze(
        file: UploadFile = File(...),
        collection: Optional[str] = Form(default=None),
        call_number: Optional[str] = Form(default=None),
        repository: Optional[str] = Form(default=None),
        header_rows: Optional[int] = Form(default=None, ge=1, le=2),
    ):
        """Accept an uploaded file, read it, and return what was found for a preview."""
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            await file.close()
            variant = "excel" if suffix in {".xlsx", ".xls", ".xlsm", ".xlsb"} else None
            return _error_response(ValidationError(input_notice("wrong-file-type", variant=variant)))
        token = uuid.uuid4().hex
        sess_dir = Path(tempfile.mkdtemp(prefix=f"lg_{token}_"))
        in_path = sess_dir / _safe_name(file.filename or f"input{suffix}")
        try:
            uploaded = 0
            with in_path.open("wb") as handle:
                while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                    uploaded += len(chunk)
                    if max_upload_bytes and uploaded > max_upload_bytes:
                        raise _too_large(max_upload_bytes)
                    handle.write(chunk)
            sessions[token] = {
                "dir": sess_dir,
                "input": in_path,
                "name": file.filename or in_path.name,
                "runs": {},
                "header_rows": header_rows,
                "collection": _clean(collection),
                "call_number": _clean(call_number),
                "repository": _clean(repository),
                "last_access": time.monotonic(),
            }
            analysis = _analyze_session(sessions[token])
        except ValidationError as exc:
            sessions.pop(token, None)
            shutil.rmtree(sess_dir, ignore_errors=True)
            return _error_response(exc)
        except OSError as exc:
            sessions.pop(token, None)
            shutil.rmtree(sess_dir, ignore_errors=True)
            return _error_response(ValidationError(input_notice(
                "cannot-open", path=file.filename or in_path.name, reason=exc.strerror or str(exc)
            )))
        finally:
            await file.close()
        sample = [f.to_row(analysis.bundle.ancestor_columns) for f in analysis.bundle.folders[:8]]
        return {"token": token, "summary": analysis.summary(), "sample_folders": sample}

    @app.post("/api/identity")
    def api_identity(req: IdentityRequest):
        """Record the operator's collection name, call number and repository, then re-analyze.

        This is how a spreadsheet that names no resource still produces correctly
        headed labels. The values are taken at face value and stored only for the
        life of the session; no lookup of any kind is performed.
        """
        sess = _session(req.token)
        identity = {key: _clean(getattr(req, key)) for key in ("collection", "call_number", "repository")}
        try:
            analysis = _analyze_session(sess, **identity)
        except ValidationError as exc:
            return _error_response(exc)
        sess.update(identity)
        return {"token": req.token, "summary": analysis.summary()}

    @app.post("/api/generate")
    def api_generate(req: GenerateRequest):
        """Write the labels for a session and return the files."""
        sess = _session(req.token)
        identity = {key: _clean(getattr(req, key)) for key in ("collection", "call_number", "repository")
                    if getattr(req, key) is not None}
        sess.update(identity)
        formats = [f for f in req.formats if f in ALLOWED_FORMATS] or ["word"]
        run = uuid.uuid4().hex
        out_dir = sess["dir"] / run
        render_options = RenderOptions(
            folder_layout=req.folder_layout,
            box_format=req.box_format,
            box_folder_text=req.box_folder_text,
        )
        try:
            analysis = _analyze_session(sess, numbering_preference=req.numbering, first_folder=req.first_folder, **identity)
            result = generate(
                analysis, out_dir, labels=req.labels, scope=req.scope, choices=req.choices,
                folder_generation=req.folder_generation, formats=formats, render_options=render_options,
            )
            zip_name = zip_download_name(result.stem)
            with zipfile.ZipFile(out_dir / zip_name, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in result.output_paths:
                    archive.write(path, path.name)
        except ValidationError as exc:
            return _error_response(exc)
        except Exception:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise
        sess["runs"][run] = zip_name
        sess["latest_run"] = run
        files = [
            {"name": p.name, "url": f"/api/download/{req.token}/{p.name}?run={run}"}
            for p in result.output_paths
        ]
        return {
            "token": req.token,
            "stem": result.stem,
            "zip_name": zip_name,
            "files": files,
            "zip_url": f"/api/download/{req.token}/zip?run={run}",
            "warnings": [w.to_dict() for w in result.warnings],
        }

    @app.get("/api/preview", response_class=HTMLResponse)
    def api_preview(
        token: str,
        side: Literal["folder", "box"] = "folder",
        labels: Optional[Labels] = None,
        scope: Scope = "all",
        choices: str = "",
        first_folder: int = Query(default=1, ge=1),
        numbering: Optional[Literal["continuous", "non-continuous"]] = None,
        folder_generation: Literal["derive", "none"] = "derive",
        folder_layout: Literal["regular", "left"] = "regular",
        box_format: BoxFormatChoice = "auto",
        box_folder_text: Literal["show", "omit"] = "show",
        collection: Optional[str] = None,
        call_number: Optional[str] = None,
        repository: Optional[str] = None,
    ):
        """One side of the labels as an HTML proof, for the interface to show."""
        try:
            sess = _session(token)
        except HTTPException as exc:
            return HTMLResponse(escape(str(exc.detail)), status_code=exc.status_code)
        identity = {k: _clean(v) for k, v in (("collection", collection), ("call_number", call_number),
                                               ("repository", repository)) if v is not None}
        try:
            analysis = _analyze_session(sess, numbering_preference=numbering, first_folder=first_folder, **identity)
            bundle, _ = select_labels(
                analysis, labels=labels, scope=scope, choices=choices,
                folder_generation=folder_generation, omit_box_folders=box_folder_text == "omit",
            )
        except ValidationError as exc:
            return HTMLResponse(_error_html(exc), status_code=400)
        opts = RenderOptions(
            folder_layout=folder_layout,
            box_format=box_format,
            box_folder_text=box_folder_text,
        )
        html = (
            render_box_html(bundle, options=opts)
            if bundle.boxes and (side == "box" or not bundle.folders)
            else render_folder_html(bundle, options=opts)
        )
        return HTMLResponse(html)

    @app.get("/api/download/{token}/{name}")
    def api_download(token: str, name: str, run: Optional[str] = None):
        """Serve the completed selection named by the link, or the latest for older clients."""
        sess = _session(token)
        run = run or sess.get("latest_run")
        if run not in sess["runs"]:
            raise HTTPException(status_code=404, detail=say("service.file_missing"))
        out_dir = sess["dir"] / run
        if name == "zip":
            zip_name = sess["runs"][run]
            return FileResponse(out_dir / zip_name, filename=zip_name, media_type="application/zip")
        target = out_dir / Path(name).name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail=say("service.file_missing"))
        return FileResponse(str(target), filename=target.name)

    return app


def _clean(value: Optional[str]) -> Optional[str]:
    """Normalize a form field: blank and whitespace-only become ``None``."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _safe_name(name: str) -> str:
    """Keep the staff-facing filename, including accents and cataloguing punctuation."""
    leaf = PureWindowsPath(name).name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", leaf).rstrip(" .") or "input"
    return "_" + cleaned if PureWindowsPath(cleaned).is_reserved() else cleaned


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _too_large(limit: int) -> ValidationError:
    return ValidationError("too_large", limit_mb=limit // (1024 * 1024))


def _error_response(exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": exc.to_dict()})


def _error_html(exc: ValidationError) -> str:
    heading = exc.finding.heading or (f"[{exc.code}]" if exc.code else "")
    return (
        f"<div style='font-family:sans-serif;padding:1rem;color:#b00'>"
        f"<strong>{escape(heading)}</strong><p>{escape(exc.finding.message)}</p>{escape(exc.finding.fix)}</div>"
    )


app = create_app()
