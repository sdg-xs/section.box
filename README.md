# Section Box for USD Composer

Inspect the inside of USD models with an interactive section box. This NVIDIA Omniverse Kit extension clips geometry against up to six box faces in the active viewport, without modifying the source geometry.

Fit the box to a selection, move and resize it in the viewport, and save named positions with your scene.

## Features

- Six clipping faces that can be enabled independently.
- Viewport handles for moving the box and resizing its active faces.
- Fit to Selection with geometry-derived Z rotation and horizontal top and bottom faces.
- Center on Selection while preserving the box's size and rotation.
- Named saved positions for switching between inspection areas.
- Undo and redo for box edits and saved-position changes.
- Clipping and an optional box overlay in the active viewport only.

The extension uses one box at a time. Cut surfaces remain open, without caps. Opening a scene or enabling the extension starts unclipped.

## Requirements

- USD Composer or a Kit application based on **Kit 110.2**, with an RTX viewport.
- The viewport, toolbar, USD, and Scene UI extensions listed in [extension.toml](config/extension.toml).
- Windows for the included PowerShell verification and packaging scripts. Verification has been performed on Windows with Kit 110.2.

## Installation

Clone this repository into an extension search directory, using `section.box` as the folder name:

```powershell
git clone https://github.com/sdg-xs/usd-composer-section-box.git section.box
```

Alternatively, download the repository through **Code > Download ZIP**, extract it, and rename the extracted repository folder to `section.box`.

The required runtime layout is:

```text
YourExtensions/
└── section.box/
    ├── config/
    │   └── extension.toml
    ├── section_box/
    │   └── ...
    └── data/
        ├── icon.svg
        └── icon_active.svg
```

1. Open **Developer > Extensions** in Composer. Some layouts use **Window > Extensions**.
2. In the extension manager's settings, add `YourExtensions` to the extension search paths.
3. Search for **Section Box** or `section.box`.
4. Enable the extension. The **Section Box** panel opens.

Add the parent directory of `section.box` as the search path. Avoid an extra nested `section.box/section.box` directory between that parent and `config/extension.toml`.

## Quick start

1. Select an element in the scene.
2. Click **Fit to Selection**. The box matches the selection and clipping turns on.
3. Drag the yellow center handle to move the box.
4. Drag an orange face handle to resize the box.
5. Clear **Section Box Active** to stop clipping.

### Adjust the box

| Control | Behavior |
| --- | --- |
| Section Box Active | Turns viewport clipping on or off. |
| Show Box | Shows or hides the overlay and handles while clipping is active. |
| Size | Sets the box's full dimensions along its local X, Y, and Z axes. |
| Active Faces | Chooses which sides clip geometry. |
| Center on Selection | Moves the box to the selection's center, preserving size, rotation, active faces, and clipping activation. |
| Fit to Selection | Fits selected geometry with Z rotation only, enables all six faces, and turns clipping on. |
| Rotation | Sets the box's absolute Z angle immediately with one slider. A value of 30° means 30°, not an additional turn. |

Only checked **Active Faces** show their plane, outline, and orange resize handle. Check just one face to display a single outlined plane. Shared edges remain visible when either adjacent face is active. The yellow center handle remains available to move the box.

**Fit to Selection** finds the smallest enclosing rectangle around the selected geometry's world-XY footprint. The box rotates only around world Z, keeping its top and bottom faces parallel to XY. This works for a whole building or an individual asset, including rotation in parent transforms or baked into mesh points. Tilted assets are enclosed without tilting the box. Georeferenced placement and scale are included in the fit.

Several selected elements produce one combined footprint. Irregular wings or outlying geometry can influence its angle. Non-mesh geometry uses conservative USD bounds.

The **Rotation** slider displays the current Z angle, including after fitting, loading a saved position, or undoing an edit. Drag it to set the angle directly. Top and bottom faces remain parallel to XY, and one drag creates one undo step.

The toolbar's cube button toggles clipping and opens the panel when clipping is enabled. Use Kit's **Undo** and **Redo** commands to revert or restore edits. One completed drag is one undo step.

### Save and load positions

1. Adjust the box to the area you want to inspect.
2. Under **Saved Positions**, enter a name and click **Save New**.
3. Save the scene to keep that position on disk.
4. Choose a position from the dropdown to restore it.

Loading a position moves the single box, restores its size, rotation, and active faces, and enables clipping. **Update** replaces the selected saved position with the current box. **Delete** removes the saved position.

Temporary adjustments do not overwrite saved positions. Switching positions is undoable. Saved positions belong to the main scene layer, regardless of the current editing layer. Read-only scenes allow inspection and loading positions, but creating, updating, or deleting positions requires a writable scene copy.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Section Box is missing from the extension manager | Confirm that the search path contains `section.box/config/extension.toml`. |
| No box or handles appear | Enable both **Section Box Active** and **Show Box**, then use **Fit to Selection** on a visible element. |
| A face or orange handle is missing | Check that face under **Active Faces**. |
| Fit to Selection does nothing | Select an element with geometry that has nonempty bounds. |
| Another viewport is unclipped | Clipping follows the active viewport. |
| A saved position is missing after reopening the scene | Save the scene after creating or updating positions. |

## Development

Runtime code lives in [section_box/](section_box/), the Kit manifest in [config/](config/), and verification code in [tests/](tests/). See [DESIGN.md](DESIGN.md) for the state model, module responsibilities, and persistence design.

### Run verification

Run these commands from the repository root in PowerShell 7:

```powershell
./run-verify.ps1
./run-verify-kit.ps1
./run-verify-pointer.ps1
```

Both scripts default to `C:\kit-app-template\_build\windows-x86_64\release\kit`. To use another Kit installation, pass the directory containing `kit.exe` with `-KitRoot`:

```powershell
./run-verify.ps1 -KitRoot 'C:\path\to\kit'
./run-verify-kit.ps1 -KitRoot 'C:\path\to\kit'
./run-verify-pointer.ps1 -KitRoot 'C:\path\to\kit'
```

The scripts expect an `extscache` directory beside the Kit directory. The geometry runner uses Kit's Python and USD libraries. The integration runner launches a separate headless Kit app with test scenes and checks rendered clipping, controls, drag gestures, undo, saved positions, and viewport isolation. The pointer runner opens a Kit window and checks that arrow dragging resizes the box without starting drag selection, while ordinary drag selection still works. Results and rendered images go to `verification/`.

From Windows Git Bash, `./run-verify.sh` forwards to the geometry runner and accepts the same `-KitRoot` argument. PowerShell 7 must be on your `PATH`.

### Check Python style

Install the development dependency in your development Python environment:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check section_box tests
python -m ruff format --check section_box tests
```

[ruff.toml](ruff.toml) defines the lint rules and 120-column formatting. Ruff is not a runtime dependency.

### Packaging status

The extension is under active development. Distribution packaging is on hold while further tweaks are made.

[package.ps1](package.ps1) is the packaging entry point for a future release. It produces `dist/section.box-<version>.zip` using the manifest version. The archive includes only runtime Python modules, `config/extension.toml`, and the toolbar icons. Tests, documentation, development tools, and generated files stay outside the installation.
