"""Read an EAD file into a YCAR record. Current functionality supports EAD2002 and EAD3 exported from Yale's ArchivesSpace."""

from __future__ import annotations

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

_COMPONENT_TAGS = frozenset(["c", *(f"c{n:02d}" for n in range(1, MAX_COMPONENT_DEPTH + 1))])


def _is_valid_xml_char(ch: str) -> bool:
    codepoint = ord(ch)
    return (
        codepoint in (0x9, 0xA, 0xD)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _sanitize_xml(source: Path) -> tuple[Path, list[tuple[int, str]]]:
    replaced: list[tuple[int, str]] = []
    with (
        tempfile.NamedTemporaryFile(suffix="_sanitized.xml", delete=False, mode="w", encoding="utf-8") as tmp,
        source.open(encoding="utf-8", errors="replace") as infile,
    ):
        for number, line in enumerate(infile, start=1):
            kept = "".join(ch if _is_valid_xml_char(ch) else "?" for ch in line)
            replaced += [(number, ch) for ch in line if not _is_valid_xml_char(ch)]
            tmp.write(kept)
    return Path(tmp.name), replaced


def _unreadable(path: Path, why: str, **values: str) -> InputError:
    return InputError("unreadable-ead", name=path.name, reason=say(f"ead_reason.{why}", **values))


def _parse_path(path: Path) -> tuple[ET._ElementTree, list[tuple[int, str]]]:
    try:
        return ET.parse(str(path)), []
    except ET.XMLSyntaxError as original:
        sanitized, replaced = _sanitize_xml(path)
        try:
            try:
                return ET.parse(str(sanitized)), replaced
            except ET.XMLSyntaxError as exc:
                raise _unreadable(path, "malformed", detail=exc.msg) from original
        finally:
            sanitized.unlink(missing_ok=True)


_ENTITY = re.compile(r"&(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);")
_OPENING = "([{"
_CLOSING = ",.;:!?)]}"


def _inline_text(el, restore_spaces: bool) -> str:
    text = el.text or ""
    for child in el:
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
        raise _unreadable(path, "namespace")
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
            repo_text = " ".join(" ".join(repo_el.itertext()).split())
            if repo_text:
                record.repository = Repository(code="", display=repo_text)
                record.repository_provenance = "declared"

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
            tag = ET.QName(child.tag).localname
            if tag in _COMPONENT_TAGS:
                record.components.append(_parse_component(child, nsmap, ead_version))

    return record


def _namespace_uri(root: ET._Element) -> Optional[str]:
    if EAD2002_NS in root.nsmap.values():
        return EAD2002_NS
    if EAD3_NS in root.nsmap.values():
        return EAD3_NS
    return None


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
    for el in did.findall("./ns:unitdate", namespaces=nsmap):
        text = (el.text or "").strip()
        if not text and el.attrib.get("normal"):
            start, _, end = el.attrib["normal"].partition("/")
            text = _span(start, end)
        if text:
            date_type = el.attrib.get("unitdatetype") or el.attrib.get("type") or "inclusive"
            dates.append(DateValue(type=date_type, display=text))
    if ead_version != "ead2002":
        for structured in did.findall("./ns:unitdatestructured", namespaces=nsmap):
            date_type = structured.attrib.get("unitdatetype", "inclusive")
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
