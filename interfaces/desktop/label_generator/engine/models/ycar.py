"""YCAR, the Yale Canonical Archival Record, is a structured description of one archival collection: its identity, its components and the containers.
It is the same shape whichever file the description came from, whether an EAD or a bulk import spreadsheet.

Every reader turns its input into a YCAR record, and the labels are derived from that record alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from label_generator.engine.content import say

#: How a YCAR record's collection title or call number comes to hold its value.
#:
#: ``declared``  the source document states it in a resource-level field
#: ``supplied``  a staff member typed it in
#: ``absent``    the source has nothing usable
Provenance = Literal["absent", "declared", "supplied"]

#: Deepest component nesting an archival description can have. EAD2002 and EAD3
#: define <c01> to <c12>, and ArchivesSpace allows the same. Everything that
#: depends on how deep a hierarchy can go reads this value and nothing else.
MAX_COMPONENT_DEPTH = 12


@dataclass
class Identifier:
    """A name for the resource, such as its call number."""
    kind: str
    value: str


@dataclass
class Title:
    """A title of the resource or of a component."""
    display: str
    kind: Optional[str] = None


@dataclass
class Repository:
    """The repository holding the material: a short code and the name printed on labels."""
    code: str
    display: str


@dataclass
class DateValue:
    """A date as the source displays it, with its type (for example inclusive)."""
    type: str
    display: str


@dataclass
class Extent:
    """A physical extent: quantity and unit where stated, and the text the source displays."""
    kind: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    display: Optional[str] = None


@dataclass
class Container:
    """A box or folder a component sits in, in ArchivesSpace's terms.

    ``indicator`` is the number or name written on the container ("3", "2-6");
    ``type`` is the kind of container the source names ("archive half legal").
    """
    kind: str  # box | folder | other
    indicator: str
    type: Optional[str] = None


@dataclass
class YcarComponent:
    """One described unit of the collection (series, file, item) and the units beneath it."""
    level: str
    title: Optional[Title] = None
    unitid: Optional[str] = None
    dates: list[DateValue] = field(default_factory=list)
    extents: list[Extent] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    children: list[YcarComponent] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        """True for a unit with nothing beneath it, which is what gets a label."""
        return len(self.children) == 0

    def title_display(self) -> str:
        """The title to print, or the configured fallback when the unit has none."""
        if self.title and self.title.display:
            return self.title.display
        return say("labels.component_title_unavailable")


@dataclass
class YcarRecord:
    """A whole collection as the engine understands it, whatever file it was read from."""
    repository: Optional[Repository] = None
    titles: list[Title] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)
    components: list[YcarComponent] = field(default_factory=list)
    title_provenance: Provenance = "absent"
    call_number_provenance: Provenance = "absent"
    repository_provenance: Provenance = "absent"
    # The line and character of each character XML doesn't allow, replaced with "?" so the file could be read.
    replaced_characters: list[tuple[int, str]] = field(default_factory=list)

    def primary_title(self) -> str:
        """The collection name to print, or the configured fallback when the source has none."""
        for t in self.titles:
            if t.kind in (None, "unittitle", "primary"):
                return t.display
        return self.titles[0].display if self.titles else say("labels.collection_unavailable")

    def call_number(self) -> str:
        """The call number to print, or the configured fallback when the source has none."""
        for ident in self.identifiers:
            if ident.kind in ("call-number", "unitid"):
                return ident.value
        return say("labels.call_number_unavailable")

    def repository_display(self) -> str:
        """The repository name to print, or the configured fallback when none is known."""
        if self.repository:
            return self.repository.display
        return say("labels.repository_unavailable")

    def identity_missing(self) -> bool:
        """True when the collection title or call number is neither stated by the source nor typed in."""
        return self.title_provenance == "absent" or self.call_number_provenance == "absent"

    def apply_identity(
        self,
        *,
        collection: Optional[str] = None,
        call_number: Optional[str] = None,
        repository: Optional[Repository] = None,
    ) -> None:
        """Overwrite the collection title, call number and repository with staff-supplied values.

        Blank values are ignored, so an empty answer never erases what the reader found.
        """
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
        """Walk the component hierarchy and yield each leaf with its ancestors."""
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
