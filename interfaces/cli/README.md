# Command line

- **Owner:** Will Nyarko
- **Date(s):**
  - Updated: 2026-10-14
- **Description:** The command-line implementation of the label generator.

`code/` contains the program:

```text
code/
├── pyproject.toml, .python-version   the uv project
├── main.py                           what is run containing the menus and the report after a run
├── build.py                          builds the program
├── pipeline.py                       runs the workflow below, from input to label files
├── readers/                          input (EAD or spreadsheet) to YCAR
├── lrr/                              YCAR to LRR: folders, boxes, numbering, box kinds and selection
├── projections/                      LRR to Word label sheets and CSV files
├── models/                           the two records, YCAR and LRR
├── content.py, repositories.py,      lookups every stage shares: wording, repositories
│   notices.py                        errors and notes
└── config/                           wording, repositories, label sheets, box kinds and typography
```

The documentation lives in `docs/`:

```text
docs/
├── end-user/
│   └── running-the-cli-tool.md       how to start the program
└── technical/
    ├── awm-ycar-lrr.md               the three layers the program is built around
    ├── rules.md                      the rules the program applies
    └── notices.md                    every error and note the program gives
```

From `code/`, `uv run main.py` runs the program and `uv run --with pyinstaller build.py` builds it; run the build on Windows to get `label-generator.exe`. The files for trying the program are in [`../../testing-inputs`](../../testing-inputs).
