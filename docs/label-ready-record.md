# Folder numbers and box indicators on labels

The Yale Canonical Archival Record (YCAR) describes the collection in one input file. From that description, the generator prepares one label-ready record (LRR) per folder or box label. Two details matter when choosing which labels to print.

## Why a partial run keeps its folder numbers

Suppose box 7 holds two folders and box 8 holds one folder titled *Sketches*. The source gives no folder numbers. With numbering set to continue across boxes starting at 10, the generator assigns 10 and 11 in box 7 and **12** to *Sketches* in box 8.

Request only box 8 and *Sketches* is still **folder 12**. The generator numbers the folders in the whole input file before selecting rows for a box or series. The same rule applies when numbering restarts in each box. With the same input file and numbering settings, each selected folder keeps the number it has in the full run. If the source already gives a folder number, the generator keeps it.

## When two folders both say “Box 10001, Folder 1”

Suppose the Photographs series gives box **10001** for folder 1. The Drawings series gives folders 1 and 2, with no usable box indicator for either. The generator puts **10001** on the Drawings labels as a placeholder and records how it got that number. The folder numbered 1 in each series keeps its own label.

| Folder labels requested | Labels in the run | Note 302 — Placeholder box number |
| --- | --- | --- |
| Photographs only | Folder 1 in the source-supplied box 10001 | None |
| Drawings only | Folders 1 and 2, both with the placeholder 10001 | Once |
| Both series | All three folders, including both labels that read “Box 10001, Folder 1” | Once |

Selecting by box number **10001** alone can include both series. When reviewing the Word sheets or CSV rows, use the series, title and source description to tell the folders apart. Keep the genuine box number. For a placeholder, check whether the material has a physical box before deciding what to print. [Staff workflow for reviewing and printing labels](staff-labeling-workflow.md)
