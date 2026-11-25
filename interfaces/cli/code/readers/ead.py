"""Read an EAD file into a YCAR record. Current functionality supports EAD2002 and EAD3 exported from Yale's ArchivesSpace."""

from __future__ import annotations

import codecs
import html
import re
import tempfile
from pathlib import Path
from typing import Optional

from lxml import etree as ET

from content import say
from models.ycar import (
    MAX_COMPONENT_DEPTH,
    Container,
    DateValue,
    Extent,
    Identifier,
    Repository,
    Title,
    YcarComponent,
    YcarRecord,
)
from notices import InputError

EAD2002_NS = "urn:isbn:1-931666-22-9"
EAD3_NS = "http://ead3.archivists.org/schema/"

#: Element names that hold a component: numbered <c01>..<c12>, or plain unnumbered <c>.
_COMPONENT_TAGS = frozenset(["c", *(f"c{n:02d}" for n in range(1, MAX_COMPONENT_DEPTH + 1))])


def _is_valid_xml_char(ch: str) -> bool:
    # XML 1.0 character ranges, adapted from https://stackoverflow.com/questions/8733233/.
    codepoint = ord(ch)
    return (
        codepoint in (0x9, 0xA, 0xD)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _sanitize_xml(source: Path) -> tuple[Path, list[tuple[int, str]]]:
    raw = source.read_bytes()
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    else:
        declaration = re.match(br"""<\?xml\s+[^?]*?encoding=["']([\w.-]+)["']""", raw)
        encoding = declaration[1].decode("ascii") if declaration else "utf-8"
    original = raw.decode(encoding)
    replaced = []
    # XML counts CRLF and lone CR as one newline. Other forbidden controls
    # (including vertical tabs) belong to the current line.
    lines = re.split(r"(\r\n|\r|\n)", original)
    for i in range(0, len(lines), 2):
        line = lines[i]
        invalid = [(i // 2 + 1, ch) for ch in line if not _is_valid_xml_char(ch)]
        if invalid:
            replaced.extend(invalid)
            lines[i] = "".join(ch if _is_valid_xml_char(ch) else "?" for ch in line)
    if not replaced:
        return source, []
    with tempfile.NamedTemporaryFile(suffix="_sanitized.xml", delete=False) as tmp:
        tmp.write("".join(lines).encode(encoding))
    return Path(tmp.name), replaced


def _unreadable(path: Path, why: str, **values: object) -> InputError:
    variant = "export_again" if why in {"malformed", "no_archdesc"} else None
    return InputError("unreadable-ead", variant=variant, name=path.name, reason=say(f"ead_reason.{why}", **values))


def _parse_path(path: Path) -> tuple[ET._ElementTree, list[tuple[int, str]]]:
    try:
        return ET.parse(str(path)), []
    except ET.XMLSyntaxError as original:
        try:
            sanitized, replaced = _sanitize_xml(path)
        except (UnicodeError, LookupError):
            raise _unreadable(path, "malformed", detail=original.msg) from original
        if not replaced:
            raise _unreadable(path, "malformed", detail=original.msg) from original
        try:
            try:
                return ET.parse(str(sanitized)), replaced
            except ET.XMLSyntaxError as exc:
                raise _unreadable(path, "malformed", detail=exc.msg) from original
        finally:
            sanitized.unlink(missing_ok=True)


# ArchivesSpace stores some titles with typed entities ("A -&gt; K") and exports
# them escaped a second time; only complete entities are decoded.
_ENTITY = re.compile(r"&(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);")
_OPENING = "([{"
_CLOSING = ",.;:!?)]}"


def _inline_text(el, restore_spaces: bool) -> str:
    text = el.text or ""
    for child in el:
        if not isinstance(child.tag, str) and isinstance(child, (ET._Comment, ET._ProcessingInstruction)):
            text += child.tail or ""
            continue
        inner = _inline_text(child, restore_spaces)
        tail = child.tail or ""
        if restore_spaces:
            before, first = text[-1:], inner[:1]
            if before.strip() and not before.isalnum() and before not in _OPENING and first.strip():
                text += " "
            last, after = inner[-1:], tail[:1]
            if last.strip() and after.strip() and after not in _CLOSING:
                inner += " "
        text += inner + tail
    return text


def _mixed_text(el, ead_version: str) -> str:
    text = _inline_text(el, restore_spaces=ead_version == "ead3")
    text = _ENTITY.sub(lambda m: html.unescape(m.group()), text)
    return " ".join(text.split())


def read_ead(path: Path) -> YcarRecord:
    tree, replaced = _parse_path(path)
    root = tree.getroot()
    ns = _namespace_uri(root)
    if ns is None:
        raise _unreadable(path, "namespace", line=root.sourceline)
    ead_version = "ead2002" if ns == EAD2002_NS else "ead3"
    nsmap = {"ns": ns}

    archdesc = root.find("./ns:archdesc", namespaces=nsmap)
    if archdesc is None:
        raise _unreadable(path, "no_archdesc")

    did = archdesc.find("./ns:did", namespaces=nsmap)
    record = YcarRecord(replaced_characters=replaced)

    if did is not None:
        repo_el = did.find("./ns:repository/ns:corpname", namespaces=nsmap)
        if repo_el is not None:
            # EAD2002 puts text directly in <corpname>; EAD3 nests it in <part>.
            # The repository name is used as the EAD states it.
            repo_text = " ".join(" ".join(repo_el.itertext()).split())
            if repo_text:
                record.repository = Repository(code="", display=repo_text)
                record.repository_provenance = "declared"

        # EAD states the collection identity in resource-level fields; no need to ask user for it.
        title_el = did.find("./ns:unittitle", namespaces=nsmap)
        if title_el is not None:
            title_text = _mixed_text(title_el, ead_version)
            if title_text:
                record.titles.append(Title(display=title_text, kind="unittitle"))
                record.title_provenance = "declared"

        call_number = _public_unitid(did, nsmap)
        if call_number:
            record.identifiers.append(Identifier(kind="call-number", value=call_number))
            record.call_number_provenance = "declared"

    dsc = archdesc.find("./ns:dsc", namespaces=nsmap)
    if dsc is not None:
        for child in dsc:
            if not isinstance(child.tag, str):
                continue
            tag = ET.QName(child.tag).localname
            if tag in _COMPONENT_TAGS:
                record.components.append(_parse_component(child, nsmap, ead_version))

    return record


def _namespace_uri(root: ET._Element) -> Optional[str]:
    uri = ET.QName(root).namespace
    return uri if uri in {EAD2002_NS, EAD3_NS} else None


def _parse_component(node: ET._Element, nsmap: dict, ead_version: str) -> YcarComponent:
    level = node.attrib.get("level", "other")
    comp = YcarComponent(level=level)

    did = node.find("./ns:did", namespaces=nsmap)
    if did is not None:
        comp.unitid = _public_unitid(did, nsmap)

        title_el = did.find("./ns:unittitle", namespaces=nsmap)
        if title_el is not None:
            comp.title = Title(display=_mixed_text(title_el, ead_version))

        comp.dates.extend(_extract_dates(did, nsmap, ead_version))
        comp.extents.extend(_extract_extents(did, nsmap, ead_version))
        comp.containers.extend(_extract_containers(did, nsmap, ead_version))

    for child in node:
        if not isinstance(child.tag, str):
            continue
        tag = ET.QName(child.tag).localname
        if tag in _COMPONENT_TAGS:
            comp.children.append(_parse_component(child, nsmap, ead_version))

    return comp


def _public_unitid(did: ET._Element, nsmap: dict) -> Optional[str]:
    for el in did.findall("./ns:unitid", namespaces=nsmap):
        if el.get("audience") != "internal" and (el.text or "").strip():
            return el.text.strip()
    return None


def _span(start: str, end: Optional[str]) -> str:
    start, end = start.strip(), (end or "").strip()
    return f"{start}-{end}" if start and end and end != start else start or end


def _date_text(el) -> str:
    if el is None:
        return ""
    return (el.text or "").strip() or el.get("standarddate", "").strip()


def _extract_dates(did: ET._Element, nsmap: dict, ead_version: str) -> list[DateValue]:
    dates: list[DateValue] = []
    # Plain <unitdate> exists in both EAD2002 and EAD3. ArchivesSpace still emits it
    # in EAD3 for qualitative dates (e.g. "undated"), so read it in both schemas.
    for el in did.findall("./ns:unitdate", namespaces=nsmap):
        text = (el.text or "").strip()
        if not text and el.attrib.get("normal"):
            # ArchivesSpace exports a date with no expression as a blank element
            # with only its normalized form.
            start, _, end = el.attrib["normal"].partition("/")
            text = _span(start, end)
        if text:
            date_type = el.attrib.get("unitdatetype") or el.attrib.get("type") or "inclusive"
            dates.append(DateValue(type=date_type, display=text))
    if ead_version != "ead2002":
        for structured in did.findall("./ns:unitdatestructured", namespaces=nsmap):
            date_type = structured.attrib.get("unitdatetype", "inclusive")
            # ArchivesSpace mirrors the curated EAD2002 <unitdate> display text in
            # @altrender; prefer it so EAD2002 and EAD3 exports of the same resource
            # agree (and so "circa"/"undated" qualifiers are not lost).
            altrender = (structured.attrib.get("altrender") or "").strip()
            if altrender:
                dates.append(DateValue(type=date_type, display=altrender))
                continue
            dr = structured.find("./ns:daterange", namespaces=nsmap)
            if dr is not None:
                display = _span(
                    _date_text(dr.find("./ns:fromdate", namespaces=nsmap)),
                    _date_text(dr.find("./ns:todate", namespaces=nsmap)),
                )
            else:
                display = _date_text(structured.find("./ns:datesingle", namespaces=nsmap))
            if display:
                dates.append(DateValue(type=date_type, display=display))
    return dates


def _extract_extents(did: ET._Element, nsmap: dict, ead_version: str) -> list[Extent]:
    extents: list[Extent] = []
    if ead_version == "ead2002":
        for el in did.findall("./ns:physdesc/ns:extent", namespaces=nsmap):
            if el.text:
                extents.append(Extent(kind="extent", display=el.text.strip()))
    else:
        for el in did.findall("./ns:physdescstructured", namespaces=nsmap):
            qty = el.find("./ns:quantity", namespaces=nsmap)
            unit = el.find("./ns:unittype", namespaces=nsmap)
            extents.append(
                Extent(
                    kind="physdescstructured",
                    quantity=qty.text.strip() if qty is not None and qty.text else None,
                    unit=unit.text.strip() if unit is not None and unit.text else None,
                )
            )
    return extents


def _extract_containers(did: ET._Element, nsmap: dict, ead_version: str) -> list[Container]:
    kind_attr = "type" if ead_version == "ead2002" else "localtype"
    type_name_attr = "altrender" if ead_version == "ead2002" else "encodinganalog"
    containers: list[Container] = []
    for el in did.findall("./ns:container", namespaces=nsmap):
        kind_raw = (el.attrib.get(kind_attr) or "").lower()
        kind = "folder" if kind_raw == "folder" else "box" if kind_raw == "box" else "other"
        containers.append(
            Container(
                kind=kind,
                indicator=(el.text or "").strip(),
                type=el.attrib.get(type_name_attr),
            )
        )
    return containers
