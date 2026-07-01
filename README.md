# step-to-drawing

Automatically convert a STEP file into a multi-view 2D engineering drawing PDF using FreeCAD.

Given any `.step` / `.stp` file it produces a single PDF containing:

| Element | Description |
|---|---|
| **Front / Top / Right** | The three principal orthographic views |
| **Isometric** | A reduced-scale (half) 3D view for reference |
| **Section A–A** | A cross-section on the **auto-detected plane of symmetry**, revealing internal features |
| **Dimensions** | Overall envelope — width, height and depth |
| **Title block** | From the standard ISO template (part number, scale, etc. can be filled in) |

Everything runs headless from one command; a FreeCAD window flashes briefly and closes itself.

---

## Example output

Running it on a bracket produces Front (120 × 55), Top (with all holes), Right (80 deep),
an isometric view, and a Section A–A revealing the bore — each auto-scaled and laid out on an
A3 sheet. A rotational flange produces the same layout with the section cutting through the
central bore and hub.

---

## Requirements

| Requirement | Version / Notes |
|---|---|
| FreeCAD | **1.0 or later** (tested on 1.1.0). Must be the GUI build — see below. |
| OS | Windows 10/11 (the `run.ps1` launcher is PowerShell). Linux/macOS supported via the manual command. |

### Why the GUI binary (not `freecadcmd`)

FreeCAD 1.1's PDF export (`TechDrawGui.exportPageAsPdf`) needs the **Gui module**, which the
console binary `freecadcmd` cannot load (`Cannot load Gui module in console application`).
So the tool runs under **`freecad.exe`**. It does *not* open an interactive session — it runs
the script and exits. Qt's `offscreen` platform (which would hide the window) unfortunately
**deadlocks** this build during TechDraw export, so a window appears for a few seconds and then
closes on its own.

---

## Installation

Install FreeCAD into a conda environment (any drive):

```powershell
conda create --prefix D:\conda-envs\freecad python=3.11 -y
conda install --prefix D:\conda-envs\freecad -c conda-forge freecad -y
```

This puts the GUI binary at `D:\conda-envs\freecad\Library\bin\freecad.exe`.

If you install FreeCAD somewhere else, either edit `$DefaultFreeCadHome` at the top of
`run.ps1`, or set the environment variable `FREECAD_HOME` to the environment root (the folder
that contains `Library\bin\freecad.exe`).

### Verify the install

```powershell
& "D:\conda-envs\freecad\Library\bin\freecadcmd.exe" install.py
```

Expected:
```
  [OK]  FreeCAD
  [OK]  Part
  [OK]  TechDraw
All dependencies satisfied.
```

---

## Usage

### Recommended — the launcher

```powershell
# output PDF is written next to the input file
.\run.ps1 my_part.step

# explicit output path and sheet size
.\run.ps1 my_part.step drawings\my_part.pdf -Sheet A2
```

`-Sheet` accepts `A4`, `A3` (default), `A2`, `A1`, `A0`.

The launcher sets up PATH, passes parameters via environment variables, runs `freecad.exe`,
and reports the resulting PDF (or prints the log if something went wrong).

### Manual (any OS)

The FreeCAD GUI binary intercepts dashed command-line flags, so parameters are passed as
environment variables rather than arguments:

```bash
export S2D_INPUT=/abs/path/my_part.step
export S2D_OUTPUT=/abs/path/my_part.pdf   # optional
export S2D_SHEET=A3                        # optional
freecad step_to_drawing.py
```

On success the PDF is written and a matching `.log` file records progress.

---

## How it works

```
STEP file
  → FreeCAD imports it (Part workbench); multiple solids are fused
  → Symmetry plane: mirror the solid about each principal mid-plane and measure
      the volume of the intersection with the original; the plane with the
      highest overlap ratio is chosen as the cut plane
  → TechDraw page (ISO template, chosen sheet size)
      · Front / Top / Right / Isometric views, auto-scaled to fit the grid
      · Section = the solid with the +normal half removed, projected ALONG the
        normal so the cut face and internal features are visible
  → The page is opened so its 2D geometry materialises, then overall
      width / height / depth dimensions are added (TechDraw.makeExtentDim)
  → Exported to PDF, then the process exits
```

### Symmetry detection

Works well for prismatic parts (brackets, plates, blocks) and rotational parts
(shafts, flanges, hubs). For a rotational part multiple planes tie at ratio 1.0, and the tie
is broken toward the axis that gives the most informative section. Highly asymmetric or organic
shapes fall back to the best-scoring plane, which may not be the ideal engineering section.

### Scale

The nearest standard scale is chosen so the part fills ~75 % of a view cell:

```
1:50 … 1:5, 1:4, 1:2, 1:1, 2:1, 5:1 … 100:1
```

The isometric view is drawn at half the main scale.

---

## Current limitations

- **Dimensions cover the overall envelope only** (width, height, depth). Individual hole
  diameters, hole positions, radii and GD&T are **not** auto-added — in headless FreeCAD only
  the whole-view extent dimension renders reliably. Add feature dimensions manually in the
  FreeCAD GUI (open the generated logic in TechDraw) if needed.
- **Section hatching** is not applied (the cut face is shown without ISO hatching).
- Surface-finish symbols, tolerances, datums and title-block text must be added manually.
- Very large assemblies (many solids) are fused before drawing and may be slow.

These are honest boundaries of what can be produced fully automatically; the geometry, views,
section and envelope dimensions are correct and to scale.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `freecad.exe not found under ...` | Set `FREECAD_HOME` or edit `$DefaultFreeCadHome` in `run.ps1`. |
| Runs but no PDF, empty `.log` | freecad.exe couldn't start its Python — ensure the whole env is reachable (the launcher adds the conda env root + `Library\bin` to PATH automatically). |
| PDF has views but value shows `0` | The page scene wasn't built before dimensioning — this is handled by the script; if you modified it, keep `open_page_scene()` before `auto_dimension()`. |
| Window stays open / hangs | Don't set `QT_QPA_PLATFORM=offscreen` (it deadlocks); the script hard-exits after export. |
| `No solid geometry found` | The STEP is surface-only or empty — check it in a viewer. |

---

## Files

```
step-to-drawing/
├── step_to_drawing.py   # main script (run under freecad.exe)
├── run.ps1              # Windows launcher — sets up env and runs it
├── install.py           # dependency checker (run under freecadcmd)
└── README.md
```

---

## License

MIT.
