"""Write the folder and box rows as CSV files beside the label sheets.

The CSV files hold the same rows the labels are made from, one line per folder label and one per box label, for users to check before printing.
Their column names match the merge fields of the Word templates users already have. The files are UTF-8 with a byte order mark, which Excel needs to show accents correctly.
"""

from __future__ import annotations

import csv
from pathlib import Path

from models.lrr import LrrBundle


def write_rows(bundle: LrrBundle, output_dir: Path, stem: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, rows in (("folder", bundle.folders_as_dicts()), ("box", bundle.boxes_as_dicts())):
        if not rows:
            continue
        path = output_dir / f"{stem}_{name}_rows.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        paths.append(path)
    return paths
