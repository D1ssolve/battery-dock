# Screenshot provenance

`dashboard-demo.png` and `settings-demo.png` are captures of Battery Dock's
actual Tk windows on Windows, including the native window controls. They are
not mockups and have no added UI, recoloring, resizing or compositing.
The interface is currently in Russian.

The built-in **DEMO / ДЕМО** provider supplies the illustrated 76% and 18%
readings. These are simulated values, **not evidence of device compatibility
or real battery measurements**. No HID devices, private calibration, device
identifiers or external plugins are involved. Tray behavior is not pictured.

## Reproduce

On an interactive Windows desktop, from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m scripts.capture_screenshots
```

The script uses a fresh temporary `APPDATA` directory and disables notification
toasts so they cannot obscure the capture. It opens the real dashboard and
settings dialog, captures their visible pixels with Pillow, then exits. It does
not save settings via the dialog or change Windows startup registration.
Keep the desktop unobscured while it runs. A desktop too small to fit either
window fails the capture rather than silently clipping it.

`capture.json` records the source commit (in CI), application and runtime
versions, dimensions and SHA-256 hashes. The Windows build workflow uploads
these captures as a separate artifact. Review the PNGs visually before replacing
the checked-in screenshots; an automated capture alone is not visual QA or a
physical-hardware acceptance test.
