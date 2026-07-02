# step-to-drawing

Automatically convert a STEP file into a multi-view 2D engineering drawing PDF using FreeCAD.

Given any `.step` / `.stp` file it produces a single PDF containing:

| Element | Description |
|---|---|
| **Front / Top / Right** | The three principal orthographic views |
| **Isometric** | A reduced-scale (half) 3D view for reference |
| **Section A–A** | A cross-section on the **auto-detected plane of symmetry**, revealing internal features |
| **Envelope dimensions** | Overall width, height and depth |
| **Diameter dimensions** | One ⌀ callout per unique circular feature, leader on the actual hole |
| **Hole table** | Every Z-axis hole with tag, ⌀, X/Y position from the datum corner, and depth (`THRU` when through-going) — bosses/hubs are automatically excluded |
| **Populated title block** | Part name, material, author, drawing number, date, scale, sheet — filled from command-line parameters |

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

# with title-block metadata
.\run.ps1 my_part.step -PartName "Mounting Bracket" -Material "AlMg3 (5754)" `
          -Author "V. Prasad" -DrawingNo "TRF-0001"
```

| Parameter | Meaning | Default |
|---|---|---|
| `-Sheet` | `A4` / `A3` / `A2` / `A1` / `A0` | `A3` |
| `-PartName` | Title-block part title | input file name |
| `-Material` | Material spec (shown under the title) | blank |
| `-Author` | "Designed by" field | blank |
| `-DrawingNo` | Drawing number field | input file name |

The launcher sets up PATH, passes parameters via environment variables, runs `freecad.exe`,
and reports the resulting PDF (or prints the log if something went wrong).

### Manual (any OS)

The FreeCAD GUI binary intercepts dashed command-line flags, so parameters are passed as
environment variables rather than arguments:

```bash
export S2D_INPUT=/abs/path/my_part.step
export S2D_OUTPUT=/abs/path/my_part.pdf    # optional
export S2D_SHEET=A3                         # optional
export S2D_TITLE="Mounting Bracket"         # optional
export S2D_MATERIAL="AlMg3 (5754)"          # optional
export S2D_AUTHOR="V. Prasad"               # optional
export S2D_DRAWING_NO="TRF-0001"            # optional
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

- **Hole table covers Z-axis (top-view) holes only.** Side-drilled holes appear in the views
  and get diameter callouts where they project as circles, but are not listed in the table.
- **Diameter callouts are per unique size** (one ⌀ per distinct diameter, capped at 8);
  counts and positions for repeated holes live in the hole table.
- **No GD&T, tolerances, surface-finish symbols or datums** — tolerance intent is not
  derivable from bare geometry, and FreeCAD's headless API doesn't expose these symbols.
- **Section hatching** is not applied (the cut face is shown without ISO hatching).
- **Hole depth is the cylindrical-face extent**; counterbores/countersinks appear as separate
  table rows rather than a combined callout.
- Very large assemblies (many solids) are fused before drawing and may be slow.

The geometry, views, section, envelope dimensions, diameter callouts, hole table and title
block are correct, to scale, and produced fully automatically.

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
