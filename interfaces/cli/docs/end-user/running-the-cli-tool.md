# Running the CLI tool

- **Owner:** Will Nyarko
- **Date(s):**
  - Updated: 2026-10-13
- **Description:** The two ways to start the command-line label generator.

Currently, the CLI implementation assumes (1) an executable file (with a `.exe` file extension), and thus (2) a Windows environment. This allows for two kinds of start: double-clicking and dropping a file.

## Double-clicking

Wherever your `label-generator.exe` lives, when you double-click it, it will open the command window and look for EAD or bulk import spreadsheet files in two places: the folder where the `.exe` lives and your Downloads folder. When it looks inside your Downloads folder, it checks to find any EADs or bulk import spreadsheets dated within the past seven (7) days (the one you pick from there gets copied into the `.exe`'s folder, where the labels are written), listing up to 9 files from both places (the newest one at the top) for you to choose from. The bottom most option allows you to type in the path or address of the file you want to use as input if it is not in the folder containing the `.exe` or your Downloads folder. When all is good at this stage, you will first be offered the usual choices, which make the labels at once, or a series of menus of choices (numbered so you can easily select what you want to do, with options to go back or quit if you have to). The window will stay open even after you are done, so press Enter in order to close the program upon finishing.

## Dropping a file

In the folder where your `label-generator.exe` lives, you can drag your EAD or bulk import spreadsheet file from another location (including your desktop) and let go of it on top of the `label-generator.exe` icon. Windows then starts the program and hands it the path of the file (i.e. the file's full location address) so that it can begin working on the label generation process. After an offer to use the usual choices, a series of numbered menu choices appears in a sequence, including options to quit or go back. When you are done, press Enter to close the program. Otherwise the command window will remain open.
