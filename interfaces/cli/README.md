# Command line

- **Owner:** Will Nyarko
- **Date(s):**
  - Updated: 2026-11-24
- **Description:** The command-line implementation of the label generator.

On Windows, double-click `label-generator-cli.exe` to choose a file, or drag an EAD XML or bulk import CSV file onto the executable. Follow the [guide to making labels](docs/end-user/running-the-cli-tool.md).

`code/` contains the program:

```text
code/
├── pyproject.toml, .python-version   the uv project
├── main.py                           guided menus, review, and the report after a run
├── command.py                        arguments for repeatable, unattended runs
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
│   └── running-the-cli-tool.md       guided use, command examples, and a sample CSV
└── technical/
    ├── awm-ycar-lrr.md               the three layers the program is built around
    ├── rules.md                      the rules the program applies
    └── notices.md                    every error and note the program gives
```

From the `code/` directory, run `uv run main.py` for the guided program or `uv run main.py run --help` for unattended use. To build an executable for the current platform, run `uv run --with pyinstaller build.py` there. On Windows the result is `dist/label-generator-cli.exe`.
