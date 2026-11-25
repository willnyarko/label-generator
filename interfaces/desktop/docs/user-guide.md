# Making labels with the desktop app

## Open the app

Extract the package for your computer into a folder you can keep. In the Windows staff ZIP, extract both folders and open **label-generator-desktop.exe** inside **desktop**. Keep using that executable after an update. On an Intel or Apple silicon Mac, open **Label Generator.app**. On Linux x64 or ARM64, run **label-generator** from the extracted **Label Generator** folder. Use the same launcher or a shortcut to it each time.

Your collection files are processed on your computer. If the native window cannot open, the app opens the same controls in your default browser.

## Choose a file and check its contents

Drop an ArchivesSpace EAD2002 or EAD3 XML export into **Choose your file**, or click to select it. For a spreadsheet, save it as CSV in the ArchivesSpace-native or Yale-custom bulk import layout. One recognized header row is enough. If the first component of a reduced sheet is being treated as a heading, open **CSV reading options** and set the number of header rows.

Check the folder and box counts and the sample folder titles. Under **Collection and repository**, confirm the collection name, call number, and repository, then edit any value you want to change for this run. Click outside the field to apply an edit.

## Make a whole or partial run

1. Under **Which labels do you need?**, choose folder labels, box labels, or both. For boxes that hold no folders, choose **Box labels only** and select **Leave it off** under **Folder text on box labels**.
2. Under **What are the labels for?**, keep the whole collection or choose boxes or top-level groups. Partial selections preserve the full collection’s folder numbering.
3. Under **More options**, choose layout, box size, and file types as needed. The defaults make Word sheets and matching CSV rows. HTML proofs and Excel workbooks are also available.
4. Check **Preview**, then choose **Make labels**. Read any notes above the downloads. **Note 302 — Placeholder box number** means at least one selected label uses 10001 as a placeholder. Check the source before editing or skipping a label, since a real box can also be numbered 10001.
5. Choose **Download all** to save a ZIP, or save individual files. Extract the ZIP before opening the Word sheets. Save each run you want to keep before changing settings or closing the app.

Folder labels use Avery 5161. Standard boxes use Avery 5164. Half Hollinger and tall flat boxes use Avery 5163, with different text orientations. Review the sheets in Word and choose actual size when printing.

## Try a sample

Open the [example spreadsheet](../examples/example-yale.csv). The summary should show **Example papers**, call number **MS 12**, three folders, and two boxes. With the defaults, **Download all** gives two Word documents and two CSVs. To check a partial run, select **Chosen boxes** and enter **8**. The folder CSV should contain just **Sketches**, folder **12**.

The [EAD2002](../examples/example-ead2002.xml), [EAD3](../examples/example-ead3.xml), and [ArchivesSpace-native CSV](../examples/example-native.csv) examples describe the same three folders. The native CSV supplies the call number. You can enter the collection name and choose the repository in the window.

## Install an update

When an installed copy offers an update, save any labels you want to keep and select **Install and restart**. The app verifies the package before switching. After it reopens, check the version in the footer. If the update is interrupted or the new version fails to open, reopen the original launcher to use the last working version. You can continue making labels when the update location is offline.
