# Running the command-line label generator

Use Label Generator to make Word sheets for folder labels, box labels, or both. Each run also writes CSV files with the rows behind the labels.

## Choose a file

Use an ArchivesSpace finding aid exported as EAD2002 or EAD3 (`.xml`), or a bulk import spreadsheet saved as CSV in the ArchivesSpace-native or Yale-custom layout. One header row is enough. A reduced sheet can use field codes or recognized column names for just the fields you have.

On Windows, double-click `label-generator.exe`. The program looks beside the executable and in recent Downloads, listing up to nine files. Choose by number or choose **Choose another file** and drag in the file or type its path. If you already have the file open in Explorer, you can drag it directly onto the executable to start there.

To run from source, open a terminal in the CLI’s `code` directory with `uv` installed. Run `uv run main.py` for the picker, or `uv run main.py "finding aid.xml"` to open a file directly. The project uses Python 3.12.

## Review and make labels

1. Supply any collection name, call number, or repository the program asks for. For the collection name, give the name of the whole collection.
2. Read the settings on the review screen. By default you get folder and box labels for the whole collection. If these settings fit, go straight to step 5.
3. For a different label type, choose **Change which labels to make and what they show**. For boxes that hold no folders, choose **Box labels only**, then **Leave folder information off**.
4. For particular boxes or series, choose **Change scope or other settings**. Enter box indicators or the listed numbers for top-level groups. The generator numbers the whole collection before applying the selection, so a folder keeps its number on a partial run.
5. Press **Enter** on **Make these labels**. Check the output paths and read any numbered notes before printing. **Change settings for this file** lets you make another selection. **Finish** closes the session.

By default the outputs go beside the input. If you picked a file from the Downloads list, look for the reported output folder. When possible the program copies that input beside the executable and writes the labels there. If you edit a Word sheet, save your changes under a new name before running again with the same settings.

If the file cannot be used, **Choose a file** lets you try again. If your selection produces no labels, use **Change settings**. **Note 302 — Placeholder box number** means at least one generated label uses `10001` as a placeholder. Check those labels against the source before printing. A genuine box numbered `10001` can also occur in the collection.

## Repeatable runs

Use `run` to supply the choices in advance. To try it, save the following as `example.csv` in the CLI’s `code` directory. It describes two folders in box 7.

```csv
collection_name,call_number,repo_code,title,top_ind,child_ind
Example papers,MS 12,BRBL,Correspondence,7,1
Example papers,MS 12,BRBL,Photographs,7,2
```

From that directory, list the choices, generate both label types, or make just the box label with the folder information omitted.

```sh
uv run main.py run example.csv --list-choices
uv run main.py run example.csv --output-dir labels
uv run main.py run example.csv --labels boxes --boxes 7 --box-folders omit --output-dir box-only
```

The first command lists box 7. The `labels` directory contains two Word sheets and two CSV files, with two folder rows and one box row. The `box-only` directory contains one box sheet and one box CSV. Use the same arguments after `.\label-generator.exe` in PowerShell when running the Windows executable from its folder.

Run `uv run main.py run --help` for every option, including collection identity, numbering, label stock, and how many CSV header rows to read. A successful command exits with status 0. Status 1 indicates a file or generation error. Status 2 indicates invalid command arguments.
