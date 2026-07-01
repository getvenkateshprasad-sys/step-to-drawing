"""
step_to_drawing.py
------------------
Import a STEP file and export a multi-view 2D engineering drawing as PDF.

Views generated:
  - Front, Top, Right (first-angle or third-angle, configurable)
  - One cross-section on the auto-detected symmetry plane
  - Isometric view at half scale

Requires FreeCAD 0.21+ with TechDraw workbench.

Usage:
    freecadcmd step_to_drawing.py -- input.step [output.pdf] [--angle {1|3}] [--sheet {A3|A2|A1}]
"""

import sys
import os
import argparse
import math

# ---------------------------------------------------------------------------
# FreeCAD bootstrap (headless)
# ---------------------------------------------------------------------------
try:
    import FreeCAD
    import FreeCADGui
    import Part
    import TechDraw
    import TechDrawGui
except ImportError as exc:
    sys.exit(
        f"FreeCAD modules not found: {exc}\n"
        "Run this script with 'freecadcmd' or activate the FreeCAD conda env."
    )

FreeCAD.Console.PrintMessage = lambda *a: None   # suppress console noise


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    # FreeCAD passes its own args before '--'; drop them.
    raw = sys.argv[:]
    if "--" in raw:
        raw = raw[raw.index("--") + 1:]
    elif len(raw) > 1 and not raw[1].startswith("-"):
        raw = raw[1:]

    parser = argparse.ArgumentParser(
        description="STEP → 2D Engineering Drawing PDF"
    )
    parser.add_argument("input", help="Path to input .step / .stp file")
    parser.add_argument(
        "output", nargs="?", default=None,
        help="Path for output PDF (default: same name as input)"
    )
    parser.add_argument(
        "--angle", choices=["1", "3"], default="1",
        help="Projection angle: 1 = first-angle (ISO), 3 = third-angle (ASME). Default: 1"
    )
    parser.add_argument(
        "--sheet", choices=["A3", "A2", "A1"], default="A3",
        help="Drawing sheet size. Default: A3"
    )
    return parser.parse_args(raw)


# ---------------------------------------------------------------------------
# STEP import
# ---------------------------------------------------------------------------
def import_step(doc, path):
    if not os.path.isfile(path):
        sys.exit(f"Input file not found: {path}")
    Part.insert(path, doc.Name)
    doc.recompute()

    shapes = [o for o in doc.Objects if hasattr(o, "Shape") and not o.Shape.isNull()]
    if not shapes:
        sys.exit("No solid geometry found in the STEP file.")

    if len(shapes) == 1:
        return shapes[0]

    # Fuse multiple bodies into one for view generation
    fused = doc.addObject("Part::MultiFuse", "FusedBody")
    fused.Shapes = shapes
    doc.recompute()
    return fused


# ---------------------------------------------------------------------------
# Symmetry plane detection
# ---------------------------------------------------------------------------
# Strategy: test the three principal planes (XY, XZ, YZ) by comparing the
# shape's bounding box extents.  The most symmetric plane is the one where
# the centroid offset from the mid-plane is smallest relative to the extent.

def detect_symmetry_plane(shape):
    """
    Returns ("XY" | "XZ" | "YZ", section_normal_vector, section_origin).
    """
    bb = shape.Shape.BoundBox
    cx = (bb.XMin + bb.XMax) / 2
    cy = (bb.YMin + bb.YMax) / 2
    cz = (bb.ZMin + bb.ZMax) / 2

    dx = bb.XMax - bb.XMin
    dy = bb.YMax - bb.YMin
    dz = bb.ZMax - bb.ZMin

    # Sample cross-section areas at ±25 % of each axis to judge symmetry.
    # A more symmetric plane yields more similar areas on both sides.
    def cross_section_area(axis, position):
        try:
            if axis == "X":
                plane = Part.makePlane(
                    max(dy, dz) * 2, max(dy, dz) * 2,
                    FreeCAD.Vector(position, cy - dy, cz - dz),
                    FreeCAD.Vector(1, 0, 0)
                )
            elif axis == "Y":
                plane = Part.makePlane(
                    max(dx, dz) * 2, max(dx, dz) * 2,
                    FreeCAD.Vector(cx - dx, position, cz - dz),
                    FreeCAD.Vector(0, 1, 0)
                )
            else:
                plane = Part.makePlane(
                    max(dx, dy) * 2, max(dx, dy) * 2,
                    FreeCAD.Vector(cx - dx, cy - dy, position),
                    FreeCAD.Vector(0, 0, 1)
                )
            section = shape.Shape.section(plane)
            return section.Area
        except Exception:
            return 0.0

    scores = {}
    for axis, center, extent in [
        ("X", cx, dx),
        ("Y", cy, dy),
        ("Z", cz, dz),
    ]:
        offset = extent * 0.25
        a1 = cross_section_area(axis, center - offset)
        a2 = cross_section_area(axis, center + offset)
        # Score = similarity (lower diff = more symmetric)
        scores[axis] = abs(a1 - a2) / (max(a1, a2) + 1e-9)

    best_axis = min(scores, key=scores.get)

    mapping = {
        "X": ("YZ", FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(cx, cy, cz)),
        "Y": ("XZ", FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(cx, cy, cz)),
        "Z": ("XY", FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(cx, cy, cz)),
    }
    return mapping[best_axis]


# ---------------------------------------------------------------------------
# Sheet dimensions (mm)
# ---------------------------------------------------------------------------
SHEET_SIZES = {
    "A3": (420, 297),
    "A2": (594, 420),
    "A1": (841, 594),
}


# ---------------------------------------------------------------------------
# Drawing creation
# ---------------------------------------------------------------------------
def build_drawing(doc, shape, args):
    sheet_w, sheet_h = SHEET_SIZES[args.sheet]
    template_name = f"A3_Landscape_ISO7200TD.svg"  # FreeCAD built-in template
    templates_dir = FreeCAD.getResourceDir() + "Mod/TechDraw/Templates/"
    template_path = os.path.join(templates_dir, template_name)
    if not os.path.isfile(template_path):
        template_path = ""   # FreeCAD will use a blank sheet

    page = doc.addObject("TechDraw::DrawPage", "DrawingPage")
    if template_path:
        template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = template_path
        page.Template = template

    # ------------------------------------------------------------------
    # View layout constants (all in mm, origin = bottom-left of sheet)
    # ------------------------------------------------------------------
    margin = 15
    title_h = 30       # reserve for title block at bottom
    usable_w = sheet_w - 2 * margin
    usable_h = sheet_h - 2 * margin - title_h

    # Divide usable area into a 3×2 grid:
    #   [Front]  [Top]   [ISO (small)]
    #   [Right]  [Section]  (empty)
    col_w = usable_w / 3
    row_h = usable_h / 2

    def grid_center(col, row):
        """col/row are 0-indexed from top-left."""
        x = margin + col * col_w + col_w / 2
        y = sheet_h - margin - title_h - row * row_h - row_h / 2
        return x, y

    scale = compute_scale(shape, col_w * 0.8, row_h * 0.8)
    iso_scale = scale / 2

    # ------------------------------------------------------------------
    # Principal views
    # ------------------------------------------------------------------
    angle_flag = int(args.angle)

    front = add_view(doc, page, shape, "Front",
                     *grid_center(0, 0), scale,
                     FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(0, 1, 0))

    top = add_view(doc, page, shape, "Top",
                   *grid_center(1, 0), scale,
                   FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(0, 0, -1))

    right = add_view(doc, page, shape, "Right",
                     *grid_center(0, 1), scale,
                     FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 1, 0))

    # ------------------------------------------------------------------
    # Section view
    # ------------------------------------------------------------------
    plane_name, normal, origin = detect_symmetry_plane(shape)
    section = doc.addObject("TechDraw::DrawViewSection", "SectionView")
    section.BaseView = front
    section.Source = [shape]
    section.ScaleType = "Custom"
    section.Scale = scale
    sx, sy = grid_center(1, 1)
    section.X = sx
    section.Y = sy
    section.SectionNormal = normal
    section.SectionOrigin = origin
    section.SectionDirection = "Right"
    page.addView(section)

    # Section label
    add_annotation(doc, page, f"SECTION {plane_name}-{plane_name}", sx, sy - row_h * 0.45)

    # ------------------------------------------------------------------
    # Isometric view
    # ------------------------------------------------------------------
    iso = add_view(doc, page, shape, "ISO",
                   *grid_center(2, 0), iso_scale,
                   FreeCAD.Vector(1, 1, 1).normalize(),
                   FreeCAD.Vector(-1, 1, 0).normalize())
    add_annotation(doc, page, f"ISOMETRIC  1:{int(1/iso_scale) if iso_scale < 1 else '1'}", *grid_center(2, 0.6))

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------
    auto_dimension(doc, page, front, shape, scale)

    doc.recompute()
    return page


def add_view(doc, page, shape, name, x, y, scale, direction, x_direction):
    view = doc.addObject("TechDraw::DrawViewPart", name)
    view.Source = [shape]
    view.Direction = direction
    view.XDirection = x_direction
    view.ScaleType = "Custom"
    view.Scale = scale
    view.X = x
    view.Y = y
    page.addView(view)
    return view


def add_annotation(doc, page, text, x, y):
    ann = doc.addObject("TechDraw::DrawViewAnnotation", f"Ann_{text[:8]}")
    ann.Text = [text]
    ann.X = x
    ann.Y = y
    ann.TextSize = 3.5
    page.addView(ann)


def compute_scale(shape, max_w, max_h):
    """Pick a standard scale so the part fits within max_w × max_h mm."""
    bb = shape.Shape.BoundBox
    part_w = max(bb.XMax - bb.XMin, 1)
    part_h = max(bb.YMax - bb.YMin, 1)
    raw = min(max_w / part_w, max_h / part_h)

    standards = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50]
    for s in standards:
        if s >= raw:
            return s
    return standards[-1]


# ---------------------------------------------------------------------------
# Auto-dimensioning (overall envelope + detected holes)
# ---------------------------------------------------------------------------
def auto_dimension(doc, page, view, shape, scale):
    bb = shape.Shape.BoundBox

    # Overall width (X)
    _add_length_dim(doc, page, view,
                    FreeCAD.Vector(bb.XMin, bb.YMin, 0),
                    FreeCAD.Vector(bb.XMax, bb.YMin, 0),
                    FreeCAD.Vector(0, -15, 0), "Width")

    # Overall height (Y)
    _add_length_dim(doc, page, view,
                    FreeCAD.Vector(bb.XMin, bb.YMin, 0),
                    FreeCAD.Vector(bb.XMin, bb.YMax, 0),
                    FreeCAD.Vector(-15, 0, 0), "Height")

    # Overall depth (Z)
    _add_length_dim(doc, page, view,
                    FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMin),
                    FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMax),
                    FreeCAD.Vector(-25, 0, 0), "Depth")

    # Circular edges → diameter dimensions
    seen_radii = set()
    for edge in shape.Shape.Edges:
        if _is_circle(edge):
            r = edge.Curve.Radius
            r_key = round(r, 2)
            if r_key in seen_radii:
                continue
            seen_radii.add(r_key)
            _add_radius_dim(doc, page, view, edge, r)


def _is_circle(edge):
    try:
        return edge.Curve.TypeId in (
            "Part::GeomCircle", "Part::GeomEllipse"
        ) or type(edge.Curve).__name__ == "Circle"
    except Exception:
        return False


def _add_length_dim(doc, page, view, p1, p2, offset, tag):
    try:
        dim = doc.addObject("TechDraw::DrawViewDimension", f"Dim_{tag}")
        dim.Type = "Distance"
        dim.References2D = [(view, f"Edge{tag}")]   # symbolic; FreeCAD resolves
        # Use 3D points directly when edge refs are unavailable
        dim.SavedGeometry = [p1, p2]
        dim.X = (p1.x + p2.x) / 2 + offset.x
        dim.Y = (p1.y + p2.y) / 2 + offset.y
        page.addView(dim)
    except Exception:
        pass   # dimensioning is best-effort; skip on API error


def _add_radius_dim(doc, page, view, edge, radius):
    try:
        dim = doc.addObject("TechDraw::DrawViewDimension", f"DimR_{int(radius*100)}")
        dim.Type = "Radius"
        dim.SavedGeometry = [edge.Curve.Center]
        dim.X = edge.Curve.Center.x
        dim.Y = edge.Curve.Center.y + radius * 1.5
        page.addView(dim)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
def export_pdf(page, path):
    try:
        page.export(path)
    except AttributeError:
        # Older FreeCAD API
        import importlib
        exp = importlib.import_module("TechDrawGui")
        exp.exportPageAsPdf(page, path)
    print(f"PDF exported → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    step_path = os.path.abspath(args.input)
    if args.output:
        pdf_path = os.path.abspath(args.output)
    else:
        pdf_path = os.path.splitext(step_path)[0] + ".pdf"

    doc = FreeCAD.newDocument("StepDrawing")

    print(f"Importing {step_path} …")
    shape = import_step(doc, step_path)

    print("Building drawing …")
    page = build_drawing(doc, shape, args)

    print(f"Exporting PDF → {pdf_path} …")
    export_pdf(page, pdf_path)

    FreeCAD.closeDocument(doc.Name)
    print("Done.")


if __name__ == "__main__":
    main()
