# Versioned Windows releases

## What a release contains

- `BatteryDock-0.4.0-Windows-x64.zip` (the filename follows `battery_dock.__version__`).
- `BatteryDock-0.4.0-Windows-x64.zip.sha256`: SHA-256 of the entire ZIP.
- Inside the ZIP: unsigned EXE, full application source/build scripts/tests/docs,
  dependency source archives and notices, resolved build versions, `BUILD-INFO.json`
  (application version and exact commit), and per-file `SHA256SUMS.txt`.

Keep the source and licenses with redistributed binaries. The existing source-bearing
package is intentionally retained; this change does not introduce a binary-only download.
GitHub's automatic source archive does not replace the dependency sources in this bundle.
A checksum detects changes relative to the published checksum, not publisher identity.
Code signing requires a separate certificate/identity decision; no certificate is configured.

## Publication controls

1. Update `battery_dock/__init__.py` to a new stable `MAJOR.MINOR.PATCH` version
   and `docs/RELEASE-NOTES.md` with the matching first-line version and actual changes.
   Publication refuses mismatched notes and uses the notes inside the tested ZIP.
2. Review changes and run the test suite. Record actual Windows/hardware validation
   separately using [WINDOWS-CHECKLIST.md](WINDOWS-CHECKLIST.md).
3. A normal push to `main` only builds/tests/uploads a 30-day Actions artifact.
4. To explicitly publish, either run **Build Windows EXE** on `main` with the
   `release` checkbox enabled, or push an intentionally approved release commit
   to `main` with `[release]` in its commit message. Do not use that marker casually.
5. The release job runs only after the Windows build, tests, Tk lifecycle smoke,
   frozen demo diagnostics, external-plugin smoke and source packaging succeed.
   It downloads only this run's artifact and verifies its external checksum.
6. It refuses an existing version tag; it never replaces releases/assets. It stages
   assets in a draft, targets the exact tested commit, then publishes `v<version>`.
   Only this job has `contents: write`; the build is read-only. Credentials are the
   workflow's repository-scoped token, not an external service or personal token.
7. Verify the published tag/commit, ZIP, checksum and `BUILD-INFO.json` after the run.
   Inspect the release-job logs if publishing fails; a successful build alone does
   not mean a release exists. A partial draft is deliberately not auto-overwritten:
   inspect/reconcile that draft and its tag manually before retrying publication.

For a local complete package, after building on Windows run:

```powershell
.\.venv\Scripts\python.exe scripts\package_windows.py
Get-FileHash .\dist\BatteryDock-0.4.0-Windows-x64.zip -Algorithm SHA256
Get-Content .\dist\BatteryDock-0.4.0-Windows-x64.zip.sha256
```

Compare the two digest values. Packaging downloads matching dependency source
archives from PyPI and verifies the upstream SHA-256; it does not execute these archives.

## Size and one-folder builds

The previous CI ZIP was approximately 71 MB. The source archives and notices are
part of the distribution, not disposable padding. A PyInstaller `--onedir` build
could reduce repeated extraction/startup cost but is not automatically smaller and
changes deployment layout. It remains an optional future measurement: compare cold
startup, antivirus behavior, size, frozen plugin child startup, clean-machine runs
and source/license completeness before replacing the current one-file build. No
size-reduction or startup-speed claim is made for 0.4.0.

References: [GitHub manual workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow),
[GitHub CLI release create](https://cli.github.com/manual/gh_release_create).
