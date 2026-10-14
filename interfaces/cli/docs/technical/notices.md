# Notices

- **Owner:** Will Nyarko
- **Date(s):**
  - Updated: 2026-10-14
- **Description:** Every notice the label generator gives: its tier, its kind, when it appears and how the program reports it.

A notice tells the user something they need to know about a file. Each notice has a number, a name and a kind. The kind is either an **error**, which stops the run and writes nothing, or a **note**, which comes with the labels for the user to check before printing. The wording of each notice, what happened and what to do, lives in `config/content.toml` under `notices.<name>`, and `notices.py` reads it from there.

## Tiers

The first digit of a notice's number places it in the run:

- **1NN, opening the file.** The program checks that the path leads to a file it can open, of a type it reads, with something in it. These checks run inside input detection, which means every way of starting the program meets them before any reading.
- **2NN, reading the file.** The program reads the file as an EAD or a bulk import spreadsheet. A file that reads as neither stops here, and an EAD with characters XML doesn't allow carries on with a note.
- **3NN, making the labels.** The program derives, chooses and writes the labels. A run with nothing to label stops here; anything the user can put right before printing comes as a note.

The name after the number says what happened, such as `302 missing-box`.

## The notices

| Notice | Kind | Raised by | Condition |
| --- | --- | --- | --- |
| `101 not-a-file` | error | `readers/detect.py` | Nothing exists at the path, or the path is not a file. |
| `102 wrong-file-type` | error | `readers/detect.py` | The file is neither `.xml` nor `.csv`. |
| `103 cannot-open` | error | `readers/detect.py` | The file exists, but the program cannot read it. |
| `104 empty-file` | error | `readers/detect.py` | The file is empty. |
| `201 unreadable-ead` | error | `readers/detect.py`, `readers/ead.py` | An `.xml` file does not read as EAD. The notice gives the reason: no `<ead` in its opening 8,192 bytes, XML too broken to read even after replacing invalid characters, a namespace other than EAD2002 or EAD3, or no `archdesc`. |
| `202 not-bulk-import` | error | `readers/detect.py` | A `.csv` file's header rows match neither bulk import layout. |
| `203 replaced-characters` | note | `pipeline.py` | An EAD file held characters XML doesn't allow. Each became "?" so the file could be read, and the note names the characters and their lines. |
| `301 nothing-to-label` | error | `pipeline.py` | The input has no components: an EAD with no c components under `<dsc>`, or a spreadsheet with no component rows. Or the run asked for box labels alone and every chosen box is `10001`. |
| `302 missing-box` | note | `pipeline.py` | A folder row has no box. It goes into the sentinel box `10001`, which the user resolves before printing. |
| `303 missing-identity` | note | `pipeline.py` | The file gives no collection name or call number, and the user typed none. The labels show "Collection unavailable" or "Call number unavailable". |
| `304 no-repository` | note | `pipeline.py` | No repository turned up: an EAD file names none, or a spreadsheet's resource URI points to a repository missing from `config/repositories.json`, and nobody picked one. The box labels show "Repository unavailable". |

A test checks that this table and `config/content.toml` list the same notices, so change them together.

## Adding a notice

Stop the run only when no useful label could come out; otherwise add a note and go on. A notice that stops a run over something the user can fix in Word in thirty seconds is a bad notice.

## How the program reports them

An error prints `Error <number> (<name>): <text>` and `What to do: <fix>`, and the program exits with status 1. A note prints the same way with `Note`, in the run summary, just before `Done.`
