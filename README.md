# step-to-drawing

Automatically convert a STEP file into a fully dimensioned 2D engineering drawing PDF.

---

## What it produces

Given any `.step` or `.stp` file the tool outputs a single PDF containing:

| View | Description |
|---|---|
| **Front** | Standard front orthographic projection |
| **Top** | Top orthographic projection |
| **Right** | Right-side orthographic projection |
| **Section** | Cross-section on the auto-detected plane of symmetry |
| **Isometric** | Small-scale ISO view for spatial reference |

Dimensions are added automatically:
- Overall width, height, and depth (bounding-box envelope)
- Diameter / radius for every unique circular feature (holes, bosses, fillets)

---

## Requirements

| Requirement | Version |
|---|---|
| FreeCAD | 0.21 or later |
| Python | 3.10+ (bundled with FreeCAD) |
| OS | Windows 10/11, Ubuntu 20.04+, macOS 12+ |

No additional Python packages are needed beyond what FreeCAD ships with.

---

## Installation

### Option A — Conda (recommended for scripting)

```bash
conda create -n freecad python=3.11
conda activate freecad
conda install -c conda-forge freecad
```

### Option B — Windows installer

1. Download FreeCAD 0.21 from https://www.freecad.org/downloads.php  
2. Install to the default location  
3. The command `freecadcmd` will be at `C:\Program Files\FreeCAD 0.21\bin\freecadcmd.exe`

### Option C — Linux AppImage

```bash
chmod +x FreeCAD_0.21.AppImage
# Run headless via:
./FreeCAD_0.21.AppImage --appimage-extract-and-run freecadcmd step_to_drawing.py -- input.step
```

### Verify your install

```bash
freecadcmd install.py
```

Expected output:
```
  [OK]  FreeCAD
  [OK]  Part
  [OK]  TechDraw
All dependencies satisfied.
```

---

## Usage

### Basic (output PDF next to input file)

```bash
freecadcmd step_to_drawing.py -- my_part.step
# → my_part.pdf
```

### Specify output path

```bash
freecadcmd step_to_drawing.py -- my_part.step drawings/output.pdf
```

### Full options

```
freecadcmd step_to_drawing.py -- <input.step> [output.pdf] [--angle {1|3}] [--sheet {A3|A2|A1}]

positional arguments:
  input         Path to the .step or .stp file
  output        Output PDF path (optional, defaults to input filename + .pdf)

options:
  --angle {1,3}          Projection standard: 1 = first-angle / ISO (default)
                                               3 = third-angle / ASME
  --sheet {A3,A2,A1}     Sheet size (default: A3)
```

### Examples

```bash
# First-angle projection, A3 sheet (ISO default)
freecadcmd step_to_drawing.py -- bracket.step

# Third-angle projection (ASME), A2 sheet
freecadcmd step_to_drawing.py -- bracket.step bracket_drawing.pdf --angle 3 --sheet A2

# Large part on A1
freecadcmd step_to_drawing.py -- housing.step housing_drawing.pdf --sheet A1
```

---

## How symmetry detection works

The script tests all three principal planes (XY, XZ, YZ) by sampling cross-section areas at ±25 % offsets on each axis. The plane where the two sampled areas are most similar is chosen as the section plane. For parts with no dominant symmetry the YZ plane (cutting along depth) is used as the fallback.

This heuristic works well for:
- Prismatic parts (brackets, plates, blocks)
- Rotational parts (shafts, flanges, hubs)
- Housings with one dominant symmetry plane

It may not pick the ideal plane for highly complex organic shapes — in that case use a CAD tool to manually set the section after generation.

---

## Scale selection

The script picks the nearest standard scale from the series:

```
1:20, 1:10, 1:5, 1:4, 1:2, 1:1, 2:1, 5:1, 10:1, 20:1, 50:1
```

so the part fills roughly 80 % of each view cell. The isometric view is always half the main scale.

---

## Output layout (A3 example)

```
┌─────────────────────────────────────────────────┐
│  Front view   │  Top view     │  ISO (half scale)│
│               │               │                  │
├───────────────┼───────────────┤                  │
│  Right view   │ Section view  │                  │
│               │  (auto-plane) │                  │
├───────────────┴───────────────┴──────────────────┤
│  Title block                                      │
└──────────────────────────────────────────────────┘
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `FreeCAD modules not found` | Wrong Python interpreter | Use `freecadcmd`, not `python` |
| `No solid geometry found` | STEP file is surface-only or empty | Check the STEP file in a viewer; ensure it contains solids |
| PDF is blank / views missing | FreeCAD TechDraw recompute timeout | Re-run; large assemblies may need more time |
| Section view shows wrong plane | Low-symmetry part | Acceptable; or manually edit the script's `detect_symmetry_plane()` return value |
| Dimensions overlap | Very dense feature set | Reduce via `auto_dimension()` seen_radii threshold in the script |

---

## File structure

```
step-to-drawing/
├── step_to_drawing.py   # Main script
├── install.py           # Dependency checker
└── README.md            # This file
```

---

## Limitations

- Auto-dimensioning covers the bounding envelope and circular features only. GD&T callouts, surface finish symbols, and datum references must be added manually.
- FreeCAD's TechDraw API does not expose full ASME Y14.5 / ISO 1101 GD&T symbols through the headless API; this is a FreeCAD limitation, not the script's.
- Assembly STEP files with many components may be slow; the script fuses all bodies before view creation.

---

## License

MIT — use freely, attribution appreciated.
