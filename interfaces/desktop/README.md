# Label Generator desktop app

1. Open Label Generator. Drop an EAD2002 or EAD3 finding aid, or an ArchivesSpace-native or Yale-custom bulk import CSV, into the window.
2. Check the collection name and call number. Choose folder labels, box labels, or both. Use the whole collection or select the boxes or series you need. A selection keeps the folder numbers from the full collection.
3. Review the label preview and choose **Make labels**. Read any notes before printing.
4. Choose **Download all** and extract the ZIP. The default download includes Word label sheets for printing and CSV rows for checking the label data.

For platform launchers, label stock, a worked example, and in-app updates, see the [desktop user guide](docs/user-guide.md).

## Run from source

From this directory, with Python 3.12 and uv available, run the following command to open the app.

```sh
uv run --extra window label-generator-desktop
```

The window displays a service on this computer. To use the local browser view, run `uv run label-generator-desktop --browser`. To run the desktop tests, use `uv run --extra dev pytest -q tests`.

The `label_generator` package contains the label engine, file writers, and window content. The `label_generator_desktop` package starts the service and window, checks for updates, and reopens the last working version after a failed update.

## Package the app

From this directory, run `python3 packaging/assemble.py --target macos-arm64 --zip` for an Apple silicon build. Other targets are `macos-x64`, `windows-x64`, `linux-x64`, and `linux-arm64`. The assembler uses uv to bundle Python and the app dependencies. For example, check the Apple silicon package on an Apple silicon Mac with `python3 packaging/verify.py --payload dist/staging-macos-arm64 --target macos-arm64 --live`.

For installations that should receive updates, give the assembler `--update-url` followed by the full URL or path to the staff-accessible `latest.json`. With `--zip` the assembler writes the manifest and platform ZIP together. For the next version, set the version in `pyproject.toml` and both package initializers, then assemble the target ZIPs into the same output directory. Make the ZIPs available beside the manifest before replacing the manifest at the configured location.
