# Testing inputs

- **Owner:** Will Nyarko
- **Date(s):**
  - Updated: 2026-10-12
- **Description:** Directory for test artifacts for the label generator tool.
- **Note(s):** -

This folder contains finding aids in EAD and CSV formats (real and synthetic). The number you see in a test artifact's name denotes the collection in scope. When artifacts share a number, it means they must produce identical labels:

- `test-1-*`: Robert Ashe papers
- `test-2-*`: Offeibea family papers (synthetic)
- `test-3-*`: Kwabena Offei papers (synthetic)
- `test-4-*`: Michel Bégon papers
- `test-5-*`: Henri Chopin papers
- `test-6-*`: Gerrit Lansing papers

In the file names, "numbered" and "unnumbered" refer to the component tags inside an EAD's `<dsc>`:

- numbered: `<c01>`, `<c02>` ... to `<c12>`
- unnumbered: `<c>`

Numbered components provide high visual clarity, making it easy to immediately see what level a component belongs to just by reading the tag name. Unnumbered components make editing easy and flexible: adding or removing layers of description does not require re-tagging, since every level uses the exact same `<c>` tag.

For more information about what to expect while using this program, see `expected/test-{number}.md`.

For more information about numbered and unnumbered components, see [`<c01>` Component (First Level)](https://www.loc.gov/ead/tglib/elements/c01.html) and [`<c>` Component (Unnumbered)](https://www.loc.gov/ead/tglib/elements/c.html) in the Library of Congress EAD Tag Library.

```text
testing-inputs/
├── README.md
├── cases/      inputs for running the tool
└── expected/   the labels each input must produce
```

| EAD2002 | Relevance |
| --- | --- |
| `test-1-ead2002-numbered.xml` | Numbered components |
| `test-1-ead2002-unnumbered.xml` | Unnumbered components |
| `test-4-ead2002.xml` | One half Hollinger box and two low flat boxes that stay in the full stock |
| `test-5-ead2002.xml` | Boxes with no container type, box numbers with gaps, series four levels deep, accents and invalid control characters |
| `test-6-ead2002.xml` | Containers give box numbers only, and every folder comes from an extent; all three box stocks appear across a large collection (84 boxes, 2,076 folders) |

| EAD3 | Relevance |
| --- | --- |
| `test-1-ead3-numbered.xml` | Numbered components |
| `test-1-ead3-unnumbered.xml` | Unnumbered components |

| CSV | Relevance |
| --- | --- |
| `test-2-csv-yale-custom.csv` | Yale-custom import sheet; folder numbers written, one as a range; no collection named |
| `test-2-csv-native.csv` | ArchivesSpace import sheet |
| `test-3-csv-yale-custom.csv` | Folders counted from the extent columns |
