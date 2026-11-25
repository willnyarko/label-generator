"""Exercise supported inputs, scope, preview, Word labels, and row exports."""

import csv
from io import BytesIO, StringIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from label_generator.engine.notices import notice
from label_generator.service.app import create_app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def upload(client, text):
    return client.post("/api/analyze", files={"file": ("collection.csv", text.encode(), "text/csv")})


def workbook_rows(client, files, suffix):
    file = next(f for f in files if f["name"].endswith(suffix))
    response = client.get(file["url"])
    response.raise_for_status()
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    try:
        rows = iter(workbook.active.values)
        headers = next(rows)
        return [dict(zip(headers, row)) for row in rows]
    finally:
        workbook.close()


@pytest.mark.parametrize("header,kind", [("top_ind", "yale-csv"), ("indicator_1", "native-csv")])
def test_one_box_column_supports_preview_and_download(header, kind):
    with TestClient(create_app()) as client:
        data = upload(client, f"{header}\n1\n2\n").json()
        summary = data["summary"]
        assert (summary["input_kind"], summary["folder_count"], summary["box_count"]) == (kind, 2, 2)
        token = data["token"]
        preview = client.get("/api/preview", params={"token": token, "numbering": "continuous"})
        assert "Box 2  Folder 2" in preview.text
        result = client.post("/api/generate", json={"token": token, "formats": ["excel"], "numbering": "continuous"})
        rows = workbook_rows(client, result.json()["files"], "_folder.xlsx")
        assert [(r["BOX"], r["FOLDER"]) for r in rows] == [("1", "1"), ("2", "2")]


@pytest.mark.parametrize("headers,expected", [(None, ["Letters"]), ("1", ["Title", "Letters"]), ("2", ["Letters"])])
def test_csv_header_choice_survives_identity_preview_and_download(headers, expected):
    with TestClient(create_app()) as client:
        data = {"header_rows": headers} if headers else {}
        uploaded = client.post("/api/analyze", data=data, files={"file": ("ambiguous.csv", b"title\nTitle\nLetters\n")})
        uploaded.raise_for_status()
        token = uploaded.json()["token"]
        identity = client.post("/api/identity", json={"token": token, "call_number": "MS 7"})
        assert identity.json()["summary"]["folder_count"] == len(expected)
        preview = client.get("/api/preview", params={"token": token})
        assert ('class="title">Title</div>' in preview.text) == ("Title" in expected)
        result = client.post("/api/generate", json={"token": token}).json()
        file = next(f for f in result["files"] if f["name"].endswith("_folder_rows.csv"))
        csv_rows = csv.DictReader(StringIO(client.get(file["url"]).content.decode("utf-8-sig")))
        assert [(r["FOLDER TITLE"], r["CALL_NO."]) for r in csv_rows] == [(title, "MS 7") for title in expected]


def test_repository_override_and_restore_match_word_csv_and_preview():
    with TestClient(create_app()) as client:
        uploaded = upload(client, "top_ind,repo_code,collection_name,call_number\n3,BRBL,Letters,MS 7\n")
        original = uploaded.json()["summary"]["repository"]
        token = uploaded.json()["token"]
        for code, expected in [("Music", "Gilmore Music Library"), ("", original)]:
            settings = {"token": token, "labels": "boxes", "repository": code}
            preview = client.get("/api/preview", params={**settings, "side": "box"})
            assert expected in preview.text
            result = client.post("/api/generate", json=settings)
            result.raise_for_status()
            assert result.json()["warnings"] == []
            files = result.json()["files"]
            assert expected in word_labels(client, files, "box")[0]
            file = next(f for f in files if f["name"].endswith("_box_rows.csv"))
            row, = csv.DictReader(StringIO(client.get(file["url"]).content.decode("utf-8-sig")))
            assert row["REPOSITORY"] == expected


@pytest.mark.parametrize("kind,header", [
    ("native-csv", "collection_id,indicator_1,indicator_2"),
    ("yale-csv", "call_number,top_ind,child_ind"),
])
def test_sourced_identity_and_numbering_survive_preview_and_generation(kind, header):
    with TestClient(create_app()) as client:
        data = upload(client, f"{header}\nMS 7,1,1\n,2,1\n,2,\n").json()
        assert data["summary"]["input_kind"] == kind
        assert data["summary"]["default_numbering"] == "non-continuous"
        assert not data["summary"]["numbering_required"]
        token = data["token"]
        identity = client.post("/api/identity", json={"token": token, "collection": "Papers"}).json()["summary"]
        assert (identity["call_number"], identity["call_number_provenance"]) == ("MS 7", "declared")
        assert identity["collection_provenance"] == "supplied"
        preview = client.get("/api/preview", params={"token": token, "numbering": "continuous"})
        assert "Box 2  Folder 1" in preview.text and "MS 7" in preview.text and "Papers" in preview.text
        generated = client.post("/api/generate", json={"token": token, "numbering": "continuous", "formats": ["excel"]})
        rows = workbook_rows(client, generated.json()["files"], "_folder.xlsx")
        assert [(r["BOX"], r["FOLDER"]) for r in rows] == [("1", "1"), ("2", "1"), ("2", "2")]
        assert {(r["COLLECTION"], r["CALL_NO."]) for r in rows} == {("Papers", "MS 7")}


def test_box_only_checks_the_origin_of_10001():
    with TestClient(create_app()) as client:
        for source_box, expected_status in [("", 400), ("10001", 200)]:
            token = upload(client, f"top_ind,title\n{source_box},Letters\n").json()["token"]
            options = {"token": token, "folder_generation": "none"}
            preview = client.get("/api/preview", params={**options, "side": "box"})
            result = client.post("/api/generate", json={**options, "formats": ["excel"]})
            assert preview.status_code == result.status_code == expected_status
            if source_box:
                assert workbook_rows(client, result.json()["files"], "_box.xlsx")[0]["BOX"] == "10001"
                assert all("10001" not in w["message"] for w in result.json()["warnings"])
            else:
                assert "no source-supplied box number" in preview.text
                assert result.json()["error"]["code"] == "301"


@pytest.mark.parametrize("csv,code", [("unknown\nvalue\n", "202"), ("top_ind\n", "301")])
def test_unrecognized_columns_and_empty_recognized_sheets_have_distinct_recovery(csv, code):
    with TestClient(create_app()) as client:
        response = upload(client, csv)
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == code
        assert "collection.csv" in error["message"]


# Two top-level groups have the same title, a shared box and an ungrouped sibling.
# The second group contains the shallowest label. Its export must still use all
# ancestor columns required by the whole collection.
GROUPED = """depth,title,top_ind
1,Papers,
2,Subgroup,
3,Early file,1
3,First group letters,2
1,Outside,1A
1,Papers,
2,Second group letters,2
2,Later file,3
"""


def word_labels(client, files, kind):
    file = next(f for f in files if f["name"].endswith(f"_{kind}_labels.docx"))
    doc = Document(BytesIO(client.get(file["url"]).content))
    labels = []
    for table in doc.tables:
        for row in table.rows:
            left, _, right = (cell.text for cell in row.cells)
            if kind == "folder" and left:
                labels.append((left, right))
            elif kind == "box":
                labels.extend(cell for cell in (left, right) if cell)
    return labels


@pytest.mark.parametrize("header", ["depth,title,top_ind,child_ind", "hierarchy,title,indicator_1,indicator_2"])
def test_note_302_follows_placeholder_origin_in_generated_labels(header):
    sheet = f"""{header}
1,Physical series,,
2,Real folder,10001,1
1,Review series,,
2,First placeholder,,2
2,Second placeholder,,3
1,Ordinary series,,
2,Ordinary folder,7,4
"""
    expected = notice("missing-box", sentinel="10001")
    note = {"code": "302", "heading": "Note 302 — Placeholder box number",
            "message": expected.text, "fix": expected.fix}
    physical = ("Real folder", "10001")
    placeholders = [("First placeholder", "10001"), ("Second placeholder", "10001")]
    ordinary = ("Ordinary folder", "7")
    cases = [
        ({}, [ordinary, physical, *placeholders], [note]),
        ({"scope": "aggregates", "choices": "2", "labels": "folders"}, placeholders, [note]),
        ({"scope": "aggregates", "choices": "1"}, [physical], []),
        ({"scope": "boxes", "choices": "7"}, [ordinary], []),
    ]
    with TestClient(create_app()) as client:
        token = upload(client, sheet).json()["token"]
        for selection, expected_rows, expected_notes in cases:
            result = client.post("/api/generate", json={"token": token, **selection})
            result.raise_for_status()
            data = result.json()
            assert [w for w in data["warnings"] if w["code"] == "302"] == expected_notes
            file = next(f for f in data["files"] if f["name"].endswith("_folder_rows.csv"))
            response = client.get(file["url"])
            response.raise_for_status()
            rows = csv.DictReader(StringIO(response.content.decode("utf-8-sig")))
            assert [(r["FOLDER TITLE"], r["BOX"]) for r in rows] == expected_rows
            labels = word_labels(client, data["files"], "folder")
            for (title, box), (left, right) in zip(expected_rows, labels, strict=True):
                assert title in right and f"Box {box}  Folder " in left


@pytest.mark.parametrize("invalid", [False, True])
def test_character_replacement_note_uses_source_line(invalid):
    raw = (EXAMPLES / "example-ead3.xml").read_bytes()
    line = next(i for i, row in enumerate(raw.splitlines(), 1) if b"Correspondence" in row)
    if invalid:
        raw = raw.replace(b"Correspondence", b"Letters\x17", 1)
    with TestClient(create_app()) as client:
        uploaded = client.post("/api/analyze", files={"file": ("example.xml", raw)})
        uploaded.raise_for_status()
        result = client.post("/api/generate", json={"token": uploaded.json()["token"], "formats": ["csv"]})
        result.raise_for_status()
        notes = [note for note in result.json()["warnings"] if note["code"] == "203"]
        if invalid:
            note, = notes
            assert f"line {line}" in note["message"] and "U+0017" in note["fix"]
        else:
            assert notes == []


@pytest.mark.parametrize("labels", ["both", "folders", "boxes"])
@pytest.mark.parametrize("scope,choices,titles,boxes", [
    ("boxes", "Box 1-2", {"Early file", "Outside", "First group letters", "Second group letters"}, {"1", "1A", "2"}),
    ("aggregates", "3", {"Second group letters", "Later file"}, {"2", "3"}),
    ("aggregates", "2", {"Outside"}, {"1A"}),
])
def test_partial_runs_keep_full_rows_and_whole_box_descriptions(labels, scope, choices, titles, boxes):
    with TestClient(create_app()) as client:
        upload_result = upload(client, GROUPED).json()
        assert upload_result["summary"]["box_choices"] == ["1", "1A", "2", "3"]
        assert upload_result["summary"]["aggregate_choices"] == ["Papers", None, "Papers"]
        settings = {"token": upload_result["token"], "numbering": "continuous", "first_folder": 40}
        full = client.post("/api/generate", json={**settings, "formats": ["excel", "word"]}).json()
        request = {**settings, "labels": labels, "scope": scope, "choices": choices}
        partial = client.post("/api/generate", json={**request, "formats": ["excel", "word", "html"]})
        partial.raise_for_status()
        files = partial.json()["files"]
        assert partial.json()["stem"].startswith(full["stem"] + "_" + scope + "_")
        for kind, label_type in (("folder", "folders"), ("box", "boxes")):
            included = labels in ("both", label_type)
            assert sum(("_" + kind + ".xlsx") in item["name"] or ("_" + kind + "_labels.") in item["name"]
                       for item in files) == (3 if included else 0)
            if not included:
                continue
            whole_rows = workbook_rows(client, full["files"], f"_{kind}.xlsx")
            if kind == "folder":
                # Catch restarting at 40 in a partial run, as well as trimming the row schema.
                assert {r["FOLDER"] for r in whole_rows} == {"40", "41", "42", "43", "44"}
                expected = [r for r in whole_rows if r["FOLDER TITLE"] in titles]
            else:
                expected = [r for r in whole_rows if r["BOX"] in boxes]
                assert next(r for r in whole_rows if r["BOX"] == "2")["FOLDER_COUNT"] == "2 folders"
            assert workbook_rows(client, files, f"_{kind}.xlsx") == expected
            full_labels = word_labels(client, full["files"], kind)
            assert word_labels(client, files, kind) == [
                text for row, text in zip(whole_rows, full_labels, strict=True) if row in expected
            ]
            preview = client.get("/api/preview", params={**request, "side": kind})
            preview.raise_for_status()
            if kind == "folder":
                for r in whole_rows:
                    assert (r["FOLDER TITLE"] in preview.text) == (r["FOLDER TITLE"] in titles)
            html = next(f for f in files if f["name"].endswith(f"_{kind}_labels.html"))
            assert client.get(html["url"]).text == preview.text


def test_shared_folder_keeps_its_label_under_either_group():
    sheet = "depth,title,top_ind,child_ind\n1,First,,\n2,Letters,7,5\n1,Second,,\n2,Enclosure,7,5\n"
    with TestClient(create_app()) as client:
        token = upload(client, sheet).json()["token"]
        args = {"token": token, "labels": "folders", "formats": ["excel"]}
        full = client.post("/api/generate", json=args).json()
        expected = workbook_rows(client, full["files"], "_folder.xlsx")
        assert len(expected) == 1 and expected[0]["FOLDER"] == "5"
        for choices in ("1", "2", "1-2"):
            data = client.post("/api/generate", json={**args, "scope": "aggregates", "choices": choices}).json()
            assert workbook_rows(client, data["files"], "_folder.xlsx") == expected


def test_invalid_selection_preserves_the_previous_download_and_can_be_corrected():
    with TestClient(create_app()) as client:
        data = upload(client, "top_ind,title\n1,A file\n,Unhoused\n").json()
        assert data["summary"]["aggregate_choices"] == []
        settings = {"token": data["token"], "formats": ["html"], "labels": "boxes"}
        previous = client.post("/api/generate", json=settings).json()
        archive = client.get(previous["zip_url"]).content
        for scope, choices in [("boxes", "10001"), ("boxes", "1, 99"), ("boxes", ""), ("aggregates", "1")]:
            req = {**settings, "scope": scope, "choices": choices}
            result = client.post("/api/generate", json=req)
            assert result.status_code == client.get("/api/preview", params=req).status_code == 400
            if choices == "10001":
                assert result.json()["error"]["code"] == "301"
            assert client.get(previous["zip_url"]).content == archive
        corrected = client.post("/api/generate", json={**settings, "scope": "boxes", "choices": "1"})
        corrected.raise_for_status()
        assert "10001" not in client.get(corrected.json()["files"][0]["url"]).text
        assert client.get(previous["zip_url"]).content == archive


@pytest.mark.parametrize("filename", [
    "example-ead2002.xml", "example-ead3.xml", "example-yale.csv", "example-native.csv",
])
def test_guide_examples_keep_folder_numbers_and_export_defaults(filename):
    from zipfile import ZipFile

    with TestClient(create_app()) as client:
        sample = EXAMPLES / filename
        analysis = client.post("/api/analyze", files={"file": (sample.name, sample.read_bytes())})
        analysis.raise_for_status()
        token = analysis.json()["token"]
        summary = analysis.json()["summary"]
        assert (summary["folder_count"], summary["box_count"], summary["call_number"]) == (3, 2, "MS 12")
        for scope, titles in [({}, ["Correspondence", "Photographs", "Sketches"]),
                              ({"scope": "boxes", "choices": "8"}, ["Sketches"])]:
            result = client.post("/api/generate", json={"token": token, **scope})
            result.raise_for_status()
            download = client.get(result.json()["zip_url"])
            download.raise_for_status()
            with ZipFile(BytesIO(download.content)) as archive:
                names = archive.namelist()
                assert sum(n.endswith(".docx") for n in names) == sum(n.endswith(".csv") for n in names) == 2
                folder_name, = [n for n in names if n.endswith("_folder_rows.csv")]
                rows = list(csv.DictReader(StringIO(archive.read(folder_name).decode("utf-8-sig"))))
                assert [r["FOLDER TITLE"] for r in rows] == titles
                assert (rows[-1]["BOX"], rows[-1]["FOLDER"]) == ("8", "12")
