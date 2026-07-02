"""
step_to_drawing.py
------------------
Import a STEP file and export a multi-view 2D engineering drawing as PDF.

Views generated:
  - Front, Top, Right orthographic projections
  - One cross-section on the auto-detected plane of symmetry
  - Isometric view at half scale

IMPORTANT — must be run with the FreeCAD **GUI** binary (freecad.exe / FreeCAD),
NOT freecadcmd.  PDF export in FreeCAD 1.1 requires the Gui module, which the
console binary cannot load.  The script closes itself when finished.

The easiest way to run it is the bundled launcher, which sets PATH and passes
parameters correctly:

    ./run.ps1 <input.step> [output.pdf] [-Sheet A3]

Parameters are read from environment variables (set by run.ps1) so the FreeCAD
GUI binary's own command-line parser does not intercept them:

    S2D_INPUT   absolute path to the .step file    (required)
    S2D_OUTPUT  absolute path to the output .pdf    (optional)
    S2D_SHEET   A4 | A3 | A2 | A1 | A0             (default A3)

    freecad.exe step_to_drawing.py

Requires FreeCAD 1.0+ with the TechDraw workbench (bundled by default).
"""

import sys
import os
import argparse
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# FreeCAD bootstrap
# ---------------------------------------------------------------------------
try:
    import FreeCAD
    import Part
except ImportError as exc:
    sys.exit(
        f"FreeCAD modules not found: {exc}\n"
        "Run this script with the FreeCAD GUI binary (freecad.exe), not plain python."
    )


# ---------------------------------------------------------------------------
# Logging — GUI binary stdout is unreliable, so mirror progress to a .log file
# ---------------------------------------------------------------------------
_LOG_PATH = None

def log(msg):
    print(msg)
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(str(msg) + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def get_params():
    """
    Parameters arrive via environment variables (set by run.ps1) because the
    FreeCAD GUI binary parses any dashed command-line tokens itself and aborts
    before the script runs.  Falls back to argv parsing when the script is run
    directly (e.g. under freecadcmd for testing).
    """
    env_input = os.environ.get("S2D_INPUT")
    if env_input:
        sheet = os.environ.get("S2D_SHEET", "A3").upper()
        if sheet not in SHEET_SIZES:
            sheet = "A3"
        return SimpleNamespace(
            input=env_input,
            output=os.environ.get("S2D_OUTPUT") or None,
            sheet=sheet,
            title=os.environ.get("S2D_TITLE") or None,
            material=os.environ.get("S2D_MATERIAL") or None,
            author=os.environ.get("S2D_AUTHOR") or None,
            drawing_no=os.environ.get("S2D_DRAWING_NO") or None,
        )

    raw = sys.argv[:]
    if "--" in raw:
        raw = raw[raw.index("--") + 1:]
    else:
        raw = [a for a in raw[1:] if not a.lower().endswith((".py", ".exe"))]

    parser = argparse.ArgumentParser(description="STEP -> 2D Engineering Drawing PDF")
    parser.add_argument("input", help="Path to input .step / .stp file")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output PDF path (default: input name + .pdf)")
    parser.add_argument("--sheet", choices=list(SHEET_SIZES),
                        default="A3", help="Drawing sheet size. Default: A3")
    parser.add_argument("--title", default=None)
    parser.add_argument("--material", default=None)
    parser.add_argument("--author", default=None)
    parser.add_argument("--drawing-no", dest="drawing_no", default=None)
    return parser.parse_args(raw)


# ---------------------------------------------------------------------------
# STEP import
# ---------------------------------------------------------------------------
def import_step(doc, path):
    if not os.path.isfile(path):
        sys.exit(f"Input file not found: {path}")

    Part.insert(path, doc.Name)
    doc.recompute()

    shapes = [o for o in doc.Objects
              if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()
              and o.Shape.Solids]
    if not shapes:
        # fall back to any non-null shape (surface models)
        shapes = [o for o in doc.Objects
                  if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
    if not shapes:
        sys.exit("No geometry found in the STEP file.")

    if len(shapes) == 1:
        return shapes[0]

    fused = doc.addObject("Part::MultiFuse", "FusedBody")
    fused.Shapes = shapes
    doc.recompute()
    return fused


# ---------------------------------------------------------------------------
# Symmetry-plane detection
#
# For each principal mid-plane, mirror the solid across it and measure the
# volume of the intersection with the original.  ratio = common / original;
# ratio == 1.0 means perfect mirror symmetry about that plane.
# The plane with the highest ratio is chosen; ties are broken by picking the
# normal along the SMALLEST extent so the cut face spans the two largest
# dimensions (the most informative section).
# ---------------------------------------------------------------------------
def detect_symmetry_plane(shape):
    """Return (plane_label, normal_vector, origin_vector)."""
    solid = shape.Shape
    bb = solid.BoundBox
    center = FreeCAD.Vector(
        (bb.XMin + bb.XMax) / 2.0,
        (bb.YMin + bb.YMax) / 2.0,
        (bb.ZMin + bb.ZMax) / 2.0,
    )
    extents = {"X": bb.XLength, "Y": bb.YLength, "Z": bb.ZLength}
    normals = {
        "X": FreeCAD.Vector(1, 0, 0),
        "Y": FreeCAD.Vector(0, 1, 0),
        "Z": FreeCAD.Vector(0, 0, 1),
    }
    total_vol = solid.Volume if solid.Volume > 1e-9 else 1e-9

    scores = {}
    for axis, n in normals.items():
        try:
            mirrored = solid.mirror(center, n)
            common = solid.common(mirrored)
            scores[axis] = common.Volume / total_vol
        except Exception as exc:
            log(f"  symmetry probe {axis} failed ({exc}); scoring 0")
            scores[axis] = 0.0

    # Highest symmetry wins; tie-break by smallest extent (normal along short axis).
    best_axis = max(scores, key=lambda a: (round(scores[a], 4), -extents[a]))
    log(f"  symmetry ratios: " +
        ", ".join(f"{a}={scores[a]:.3f}" for a in ("X", "Y", "Z")) +
        f"  -> section normal along {best_axis}")

    label = {"X": "A", "Y": "B", "Z": "C"}[best_axis]
    return label, normals[best_axis], center


# ---------------------------------------------------------------------------
# Sheet sizes (mm, landscape) and blank template lookup
# ---------------------------------------------------------------------------
SHEET_SIZES = {
    "A4": (297, 210), "A3": (420, 297), "A2": (594, 420),
    "A1": (841, 594), "A0": (1189, 841),
}

def template_path(sheet):
    """Prefer a template with a title block; fall back to the blank sheet."""
    base = FreeCAD.getResourceDir() + "Mod/TechDraw/Templates/ISO/"
    for name in (f"{sheet}_Landscape_TD.svg",
                 f"{sheet}_Landscape_ISO5457_advanced.svg",
                 f"{sheet}_Landscape_blank.svg"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    sys.exit(f"No TechDraw template found for {sheet} under {base}\n"
             "Your FreeCAD install may be missing bundled templates.")


def fill_title_block(template, args, scale):
    """
    Populate the template's editable text fields.  Field names differ between
    templates, so match by keyword rather than exact key.
    """
    import datetime
    title = args.title or os.path.splitext(os.path.basename(args.input))[0]
    number = args.drawing_no or title
    today = datetime.date.today().isoformat()
    try:
        texts = dict(template.EditableTexts)
    except Exception:
        return
    filled = []
    for key in texts:
        k = key.lower()
        val = None
        if "subtitle" in k:
            val = f"Material: {args.material}" if args.material else ""
        elif "title" in k:
            val = title
        elif "material" in k:
            val = args.material or ""
        elif any(s in k for s in ("author", "creator", "designed")):
            val = args.author or ""
        elif "drawing_number" in k or k == "number":
            val = number
        elif "scale" in k:
            val = fmt_scale(scale)
        elif "creation" in k or "date_of_issue" in k:
            val = today
        elif "sheet" in k:
            val = "1 / 1"
        if val is not None:
            texts[key] = val
            if val:
                filled.append(key)
    try:
        template.EditableTexts = texts
        if filled:
            log(f"  title block: {', '.join(filled)}")
    except Exception as exc:
        log(f"  (title block fill failed: {exc})")


# ---------------------------------------------------------------------------
# Scale helpers
# ---------------------------------------------------------------------------
STD_SCALES = [0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100]

def compute_scale(shape, max_w, max_h):
    bb = shape.Shape.BoundBox
    part_w = max(bb.XLength, 1e-6)
    part_h = max(bb.ZLength, 1e-6)   # front view shows X (width) and Z (height)
    raw = min(max_w / part_w, max_h / part_h)
    fit = STD_SCALES[0]
    for s in STD_SCALES:
        if s <= raw:
            fit = s
    return fit

def fmt_scale(s):
    if s >= 1:
        return f"{int(s)}:1" if float(s).is_integer() else f"{s:g}:1"
    return f"1:{int(round(1 / s))}"


# ---------------------------------------------------------------------------
# Drawing assembly
# ---------------------------------------------------------------------------
def build_drawing(doc, shape, args):
    sheet_w, sheet_h = SHEET_SIZES[args.sheet]

    page = doc.addObject("TechDraw::DrawPage", "Page")
    template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    template.Template = template_path(args.sheet)
    page.Template = template
    doc.recompute()

    # ---- layout ------------------------------------------------------------
    # TechDraw page coordinates: origin at BOTTOM-LEFT, +X right, +Y up,
    # ranging 0..sheet_w by 0..sheet_h.  view.X / view.Y is the view centre.
    # (Verified empirically against exported SVG transforms.)
    title_h = 30.0                                   # title block band at bottom
    usable_h = sheet_h - title_h
    col_w = sheet_w / 3.0
    row_h = usable_h / 2.0
    col_x = {0: sheet_w / 6.0, 1: sheet_w / 2.0, 2: 5.0 * sheet_w / 6.0}
    top_y = title_h + usable_h * 0.72                 # upper row centre
    bot_y = title_h + usable_h * 0.28                 # lower row centre

    def cell(col, row):
        return col_x[int(col)], (top_y if row < 0.5 else bot_y)

    scale = compute_scale(shape, col_w * 0.75, row_h * 0.75)
    iso_scale = scale / 2.0
    log(f"  main scale {fmt_scale(scale)}, iso scale {fmt_scale(iso_scale)}")
    fill_title_block(template, args, scale)

    V = FreeCAD.Vector
    # Standard TechDraw viewing directions (normal points from part to viewer)
    front = add_view(doc, page, shape, "Front", *cell(0, 0), scale,
                     V(0, -1, 0), V(1, 0, 0))
    top = add_view(doc, page, shape, "Top", *cell(1, 0), scale,
                   V(0, 0, 1), V(1, 0, 0))
    right = add_view(doc, page, shape, "Right", *cell(0, 1), scale,
                     V(1, 0, 0), V(0, 1, 0))
    iso = add_view(doc, page, shape, "Isometric", *cell(2, 0), iso_scale,
                   V(1, -1, 1), V(1, 0, -1))
    ix, iy = cell(2, 0)
    add_annotation(doc, page, f"ISO  {fmt_scale(iso_scale)}", ix, iy - row_h * 0.42)
    doc.recompute()

    # ---- section on the detected symmetry plane -----------------------------
    label, normal, origin = detect_symmetry_plane(shape)
    sx, sy = cell(1, 1)
    build_section(doc, page, shape, normal, origin, label, scale, sx, sy)
    doc.recompute()

    # ---- dimensions ---------------------------------------------------------
    # The view's 2D projected geometry only exists once the page's graphics
    # scene has been built, so open the page in the GUI FIRST; otherwise the
    # extent dimensions measure zero edges and render as "0".
    open_page_scene(doc, page)
    auto_dimension(doc, page, front, right, shape)
    add_diameter_dims(doc, page, [top, front, right])

    # ---- hole table ----------------------------------------------------------
    holes = detect_holes(shape)
    if holes:
        add_hole_table(doc, page, shape, holes, *cell(2, 1))

    doc.recompute()
    return page


def open_page_scene(doc, page):
    """Build the page's QGraphicsScene so projected 2D geometry is available."""
    try:
        import FreeCADGui as Gui
        Gui.getDocument(doc.Name).getObject(page.Name).doubleClicked()
        Gui.updateGui()
    except Exception as exc:
        log(f"  (could not open page scene: {exc})")


def add_view(doc, page, shape, name, x, y, scale, direction, x_direction):
    view = doc.addObject("TechDraw::DrawViewPart", name)
    view.Source = [shape]
    view.Direction = direction
    view.XDirection = x_direction
    view.ScaleType = "Custom"
    view.Scale = scale
    page.addView(view)
    # Position must be set AFTER the view is registered on the page, otherwise
    # it is reset to (0,0) = page centre during the first recompute.
    view.X = x
    view.Y = y
    log(f"  view {name:10s} -> ({x:.0f}, {y:.0f}) scale {scale}")
    return view


def add_annotation(doc, page, text, x, y):
    safe = "Ann_" + "".join(c for c in text if c.isalnum())[:12]
    ann = doc.addObject("TechDraw::DrawViewAnnotation", safe)
    ann.Text = [text]
    try:
        ann.TextSize = 3.5
    except Exception:
        pass
    page.addView(ann)
    # Position after addView (see add_view note) or it snaps to page centre.
    ann.X = x
    ann.Y = y
    return ann


def build_section(doc, page, shape, normal, origin, label, scale, x, y):
    """
    Build a cross-section by cutting away the half-space on the +normal side of
    the symmetry plane, then projecting the remaining solid ALONG the normal so
    the cut face (with any internal features it passes through) is shown.

    This is done with a plain DrawViewPart of the cut solid rather than a
    TechDraw DrawViewSection: the latter is unreliable in headless mode
    ("failed to create section CS") whereas a cut-solid view always renders.
    The detected symmetry normal is always axis-aligned (X, Y or Z).
    """
    solid = shape.Shape
    bb = solid.BoundBox
    pad = 10.0
    V = FreeCAD.Vector
    if abs(normal.x) > 0.5:            # cut plane normal along X
        cutbox = Part.makeBox(bb.XLength + 2 * pad, bb.YLength + 2 * pad,
                              bb.ZLength + 2 * pad,
                              V(origin.x, bb.YMin - pad, bb.ZMin - pad))
        direction, xdir = V(1, 0, 0), V(0, 1, 0)
    elif abs(normal.y) > 0.5:          # normal along Y
        cutbox = Part.makeBox(bb.XLength + 2 * pad, bb.YLength + 2 * pad,
                              bb.ZLength + 2 * pad,
                              V(bb.XMin - pad, origin.y, bb.ZMin - pad))
        direction, xdir = V(0, 1, 0), V(1, 0, 0)
    else:                              # normal along Z
        cutbox = Part.makeBox(bb.XLength + 2 * pad, bb.YLength + 2 * pad,
                              bb.ZLength + 2 * pad,
                              V(bb.XMin - pad, bb.YMin - pad, origin.z))
        direction, xdir = V(0, 0, 1), V(1, 0, 0)

    try:
        half = solid.cut(cutbox)
        if half.Volume < 1e-6:
            half = solid.common(cutbox)
    except Exception as exc:
        log(f"  section cut failed ({exc}); skipping section view")
        return None

    sobj = doc.addObject("Part::Feature", "SectionBody")
    sobj.Shape = half
    doc.recompute()

    sview = add_view(doc, page, sobj, "SectionView", x, y, scale, direction, xdir)
    # Label goes just under the section's actual projected height (the paper
    # height is the Z extent unless we're looking down the Z axis), clamped so
    # it can never reach down into the title block band.
    paper_h = (bb.YLength if abs(normal.z) > 0.5 else bb.ZLength) * scale
    label_y = max(y - paper_h / 2.0 - 10.0, 68.0)
    add_annotation(doc, page, f"SECTION {label}-{label}", x, label_y)
    return sview


# ---------------------------------------------------------------------------
# Auto-dimensioning via TechDraw.makeExtentDim
#
# makeExtentDim(view, [], direction) dimensions the whole view's envelope
# (0 = horizontal, 1 = vertical).  This is the one dimensioning call that
# renders reliably in headless mode; per-edge References3D dimensions do not
# associate to a view and produce nothing.  The created dimension is then
# nudged outside the view outline so it does not sit on top of the geometry.
# ---------------------------------------------------------------------------
def _extent_dim(doc, view, direction, tag, half_w, half_h):
    import TechDraw
    try:
        dim = TechDraw.makeExtentDim(view, [], direction)
        doc.recompute()
        # dim.X / dim.Y are offsets RELATIVE TO THE VIEW CENTRE (not the page).
        gap = 15.0
        if direction == 0:                 # horizontal extent -> below the view
            dim.X, dim.Y = 0.0, -(half_h + gap)
        else:                              # vertical extent -> left of the view
            dim.X, dim.Y = -(half_w + gap), 0.0
        return dim
    except Exception as exc:
        log(f"  extent dim {tag} skipped ({exc})")
        return None


def projected_circles(view):
    """
    Enumerate the view's projected 2D edges and return circles as
    (edge_index, radius, centre) in view-relative paper coordinates.
    Only available after the page scene has been built (open_page_scene).
    """
    out = []
    i = 0
    while i < 300:
        try:
            e = view.getEdgeByIndex(i)
        except Exception:
            break
        if e is None:
            break
        try:
            if type(e.Curve).__name__ == "Circle":
                out.append((i, float(e.Curve.Radius), e.Curve.Center))
        except Exception:
            pass
        i += 1
    return out


def add_diameter_dims(doc, page, views, max_dims=8):
    """
    Add a diameter dimension for each UNIQUE hole diameter, on the first view
    where a circle of that size projects.  Repeated diameters are dimensioned
    once (counts are listed in the hole table instead), and the total is capped
    to keep the sheet readable.
    """
    import math
    seen = set()
    count = 0
    for view in views:
        for idx, r, ctr in projected_circles(view):
            key = round(2 * r, 2)
            if key in seen:
                continue
            if count >= max_dims:
                log(f"  (diameter dims capped at {max_dims})")
                return
            seen.add(key)
            try:
                dim = doc.addObject("TechDraw::DrawViewDimension",
                                    f"Dia_{view.Name}_{idx}")
                dim.Type = "Diameter"
                dim.References2D = [(view, f"Edge{idx}")]
                page.addView(dim)
                # Place the label outward from the view centre.  Circles whose
                # centre sits near the view origin (concentric bores/rims) all
                # share the same radial direction, so rotate the angle per dim
                # to fan their labels apart instead of stacking them.
                n = math.hypot(ctr.x, ctr.y)
                if n > 5.0:
                    ux, uy = ctr.x / n, ctr.y / n
                else:
                    ang = math.radians(30 + 55 * count)
                    ux, uy = math.cos(ang), math.sin(ang)
                dim.X = ctr.x + (r + 12) * ux
                dim.Y = ctr.y + (r + 10) * uy
                count += 1
            except Exception as exc:
                log(f"  diameter dim on {view.Name} Edge{idx} skipped ({exc})")
    log(f"  {count} diameter dimension(s) added")


# ---------------------------------------------------------------------------
# Hole table (from the 3D geometry, independent of what renders)
# ---------------------------------------------------------------------------
def detect_holes(shape):
    """
    Find Z-axis-aligned cylindrical holes: group cylindrical faces by
    (axis position, radius), then keep only groups whose axis runs through
    empty space (a point on the axis is NOT inside the solid) — this
    distinguishes holes from bosses/hubs.
    """
    import math
    solid = shape.Shape
    groups = {}
    for f in solid.Faces:
        surf = f.Surface
        if type(surf).__name__ != "Cylinder":
            continue
        if abs(surf.Axis.z) < 0.99:        # only vertical (top-view) holes
            continue
        c = surf.Center
        key = (round(c.x, 2), round(c.y, 2), round(surf.Radius, 2))
        zmin, zmax = f.BoundBox.ZMin, f.BoundBox.ZMax
        com = f.CenterOfMass
        if key in groups:
            groups[key][0] = min(groups[key][0], zmin)
            groups[key][1] = max(groups[key][1], zmax)
        else:
            groups[key] = [zmin, zmax, com]

    holes = []
    for (x, y, r), (z0, z1, com) in groups.items():
        # Hole-vs-boss test: probe a point just INSIDE the cylindrical surface
        # (between surface and axis, near the face's own angular position).
        # Hole -> void there; boss -> solid material.  Probing the axis itself
        # would misclassify hollow bosses (e.g. a hub around a bore).
        rx, ry = com.x - x, com.y - y
        n = math.hypot(rx, ry)
        ux, uy = (rx / n, ry / n) if n > 1e-6 else (1.0, 0.0)
        eps = min(0.2, r * 0.1)
        probe = FreeCAD.Vector(x + ux * (r - eps), y + uy * (r - eps), com.z)
        try:
            if solid.isInside(probe, 1e-6, True):
                continue                    # material inside surface -> a boss
        except Exception:
            pass
        depth = z1 - z0
        thru = depth >= solid.BoundBox.ZLength - 1e-3
        holes.append({"x": x, "y": y, "dia": 2 * r, "depth": depth, "thru": thru})

    holes.sort(key=lambda h: (h["dia"], h["x"], h["y"]))
    log(f"  {len(holes)} hole(s) detected for hole table")
    return holes


def add_hole_table(doc, page, shape, holes, x, y):
    bb = shape.Shape.BoundBox
    lines = ["HOLE TABLE (X,Y FROM BOTTOM-LEFT, TOP VIEW)",
             "TAG    DIA     X       Y       DEPTH"]
    for i, h in enumerate(holes, 1):
        depth = "THRU" if h["thru"] else f"{h['depth']:.1f}"
        lines.append(f"H{i:<5} {h['dia']:<7.1f} {h['x'] - bb.XMin:<7.1f} "
                     f"{h['y'] - bb.YMin:<7.1f} {depth}")
    ann = doc.addObject("TechDraw::DrawViewAnnotation", "HoleTable")
    ann.Text = lines
    try:
        ann.TextSize = 3.0
    except Exception:
        pass
    page.addView(ann)
    ann.X = x
    ann.Y = y


def auto_dimension(doc, page, front, right, shape):
    bb = shape.Shape.BoundBox
    fs = float(front.Scale)
    rs = float(right.Scale)

    # On-paper half sizes of each view (front shows X x Z; right shows Y x Z).
    f_hw, f_hh = bb.XLength * fs / 2.0, bb.ZLength * fs / 2.0
    r_hw, r_hh = bb.YLength * rs / 2.0, bb.ZLength * rs / 2.0

    # Front view: overall width (horizontal) + overall height (vertical).
    _extent_dim(doc, front, 0, "Width", f_hw, f_hh)
    _extent_dim(doc, front, 1, "Height", f_hw, f_hh)
    # Right view: overall depth (its horizontal extent = Y).
    _extent_dim(doc, right, 0, "Depth", r_hw, r_hh)
    doc.recompute()


# ---------------------------------------------------------------------------
# PDF export (requires the GUI module -> run under freecad.exe)
# ---------------------------------------------------------------------------
def export_pdf(doc, page, path):
    try:
        import FreeCADGui as Gui
        import TechDrawGui
    except ImportError:
        sys.exit(
            "PDF export needs the FreeCAD Gui module.\n"
            "Run this script with the GUI binary 'freecad.exe', not 'freecadcmd'."
        )
    # CRITICAL: exportPageAsPdf renders the page's graphics scene, which is only
    # built when the page is opened in the GUI.  Without this the PDF contains
    # the template and labels but NONE of the projected view geometry.
    try:
        gdoc = Gui.getDocument(doc.Name)
        gpage = gdoc.getObject(page.Name)
        gpage.doubleClicked()      # opens the page -> builds the QGraphicsScene
        Gui.updateGui()
    except Exception as exc:
        log(f"  (warning: could not open page in GUI: {exc})")
    TechDrawGui.exportPageAsPdf(page, path)
    if os.environ.get("S2D_DEBUG_SVG"):
        try:
            TechDrawGui.exportPageAsSvg(page, os.path.splitext(path)[0] + ".svg")
        except Exception as exc:
            log(f"  (svg debug export failed: {exc})")
    if not os.path.isfile(path):
        sys.exit("PDF export reported success but no file was written.")
    log(f"PDF exported -> {path}  ({os.path.getsize(path)} bytes)")


def hard_exit(code=0):
    """
    Terminate immediately.  Under the GUI binary in offscreen mode the Qt event
    loop keeps the process alive after the script finishes; closing the main
    window does not reliably stop it.  A hard exit is the robust way to end a
    one-shot batch run.  The document is already saved/closed and the log file
    is flushed on every write, so nothing is lost.
    """
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(code)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    global _LOG_PATH
    args = get_params()

    step_path = os.path.abspath(args.input)
    pdf_path = (os.path.abspath(args.output) if args.output
                else os.path.splitext(step_path)[0] + ".pdf")
    _LOG_PATH = os.path.splitext(pdf_path)[0] + ".log"
    open(_LOG_PATH, "w", encoding="utf-8").close()

    log(f"Importing {step_path}")
    doc = FreeCAD.newDocument("StepDrawing")
    shape = import_step(doc, step_path)

    log("Building drawing")
    page = build_drawing(doc, shape, args)

    log("Exporting PDF")
    export_pdf(doc, page, pdf_path)

    FreeCAD.closeDocument(doc.Name)
    log("Done.")
    hard_exit(0)


# NOTE: FreeCAD's binaries execute a passed script with __name__ set to the
# module name, NOT "__main__", so a normal `if __name__ == "__main__"` guard
# would never fire.  Run unconditionally (this file is only ever an entry point).
try:
    main()
except SystemExit:
    raise
except BaseException as exc:
    log(f"FATAL: {exc!r}")
    hard_exit(1)
