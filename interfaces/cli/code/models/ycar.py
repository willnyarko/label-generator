"""YCAR, the Yale Canonical Archival Record, is a structured description of one archival collection: its identity, its components and the containers.
It is the same shape whichever file the description came from, whether an EAD or a bulk import spreadsheet.

Every reader turns its input into a YCAR record, and the labels are derived from that record alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from content import say

Provenance = Literal["absent", "declared", "supplied"]

MAX_COMPONENT_DEPTH = 12


@dataclass
class Identifier:
    kind: str
    value: str


@dataclass
class Title:
    display: str
    kind: Optional[str] = None


@dataclass
class Repository:
    code: str
    display: str


@dataclass
class DateValue:
    type: str
    display: str


@dataclass
class Extent:
    kind: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    display: Optional[str] = None


@dataclass
class Container:
    kind: str
    indicator: str
    type: Optional[str] = None


@dataclass
class YcarComponent:
    level: str
    title: Optional[Title] = None
    unitid: Optional[str] = None
    dates: list[DateValue] = field(default_factory=list)
    extents: list[Extent] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    children: list[YcarComponent] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return len(self.children) == 0

    def title_display(self) -> str:
        if self.title and self.title.display:
            return self.title.display
        return say("labels.component_title_unavailable")


@dataclass
class YcarRecord:
    repository: Optional[Repository] = None
    titles: list[Title] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)
    components: list[YcarComponent] = field(default_factory=list)
    title_provenance: Provenance = "absent"
    call_number_provenance: Provenance = "absent"
    repository_provenance: Provenance = "absent"
    replaced_characters: list[tuple[int, str]] = field(default_factory=list)

    def primary_title(self) -> str:
        for t in self.titles:
            if t.kind in (None, "unittitle", "primary"):
                return t.display
        return self.titles[0].display if self.titles else say("labels.collection_unavailable")

    def call_number(self) -> str:
        for ident in self.identifiers:
            if ident.kind in ("call-number", "unitid"):
                return ident.value
        return say("labels.call_number_unavailable")

    def repository_display(self) -> str:
        if self.repository:
            return self.repository.display
        return say("labels.repository_unavailable")

    def identity_missing(self) -> bool:
        return self.title_provenance == "absent" or self.call_number_provenance == "absent"

    def apply_identity(
        self,
        *,
        collection: Optional[str] = None,
        call_number: Optional[str] = None,
        repository: Optional[Repository] = None,
    ) -> None:
        if collection and collection.strip():
            kept = [t for t in self.titles if t.kind not in (None, "unittitle", "primary")]
            self.titles = [Title(display=collection.strip(), kind="unittitle"), *kept]
            self.title_provenance = "supplied"
        if call_number and call_number.strip():
            kept = [i for i in self.identifiers if i.kind not in ("call-number", "unitid")]
            self.identifiers = [
                Identifier(kind="call-number", value=call_number.strip()),
                *kept,
            ]
            self.call_number_provenance = "supplied"
        if repository:
            self.repository = repository
            self.repository_provenance = "supplied"

    def terminal_components(self) -> list[tuple[list[YcarComponent], YcarComponent]]:
        results: list[tuple[list[YcarComponent], YcarComponent]] = []

        def walk(ancestors: list[YcarComponent], node: YcarComponent) -> None:
            if node.is_terminal:
                results.append((ancestors.copy(), node))
                return
            for child in node.children:
                walk(ancestors + [node], child)

        for top in self.components:
            walk([], top)
        return results
