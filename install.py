"""
install.py
----------
Verify the FreeCAD environment and required modules are available.
Run this once before using step_to_drawing.py.
"""

import sys
import subprocess
import importlib

REQUIRED = ["FreeCAD", "Part", "TechDraw"]

def check():
    ok = True
    for mod in REQUIRED:
        try:
            importlib.import_module(mod)
            print(f"  [OK]  {mod}")
        except ImportError:
            print(f"  [MISSING]  {mod}")
            ok = False

    if not ok:
        print(
            "\nFreeCAD modules not found. Options:\n"
            "  1. Conda:    conda install -c conda-forge freecad\n"
            "  2. AppImage: download from https://www.freecad.org/downloads.php\n"
            "               then run:  ./FreeCAD.AppImage --appimage-extract-and-run freecadcmd install.py\n"
            "  3. Windows:  install FreeCAD, then run this script with\n"
            "               C:\\Program Files\\FreeCAD 0.21\\bin\\freecadcmd.exe install.py\n"
        )
        sys.exit(1)

    print("\nAll dependencies satisfied. You are ready to use step_to_drawing.py.")


# FreeCAD runs a passed script with __name__ set to the module name (not
# "__main__"), so call unconditionally.
check()
