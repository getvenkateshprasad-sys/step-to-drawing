<#
    run.ps1 - fool-proof launcher for step_to_drawing.py
    -----------------------------------------------------
    Handles everything the FreeCAD GUI binary needs to run head-less:
      * puts FreeCAD's DLL folders on PATH
      * forces Qt offscreen mode (no window ever appears)
      * invokes freecad.exe (required for PDF export) with your arguments

    USAGE:
        .\run.ps1 <input.step> [output.pdf] [-Sheet A3]

    EXAMPLES:
        .\run.ps1 mypart.step
        .\run.ps1 mypart.step drawings\out.pdf -Sheet A2

    If FreeCAD is installed somewhere else, set the FREECAD_HOME environment
    variable to its root (the folder that contains Library\bin\freecad.exe),
    or edit $DefaultFreeCadHome below.
#>

param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $StepFile,
    [Parameter(Position = 1)] [string] $Output = "",
    [ValidateSet("A4","A3","A2","A1","A0")] [string] $Sheet = "A3",
    [string] $PartName  = "",   # title block: part title (default: file name)
    [string] $Material  = "",   # title block: material spec
    [string] $Author    = "",   # title block: designed-by
    [string] $DrawingNo = "",   # title block: drawing number (default: file name)
    [string] $Tolerance = ""    # general-tolerance note (default: ISO 2768-mK)
)

$ErrorActionPreference = "Stop"

# --- locate FreeCAD -------------------------------------------------------
# Search order: FREECAD_HOME, standard Windows installs, then a conda env.
$candidates = @()
if ($env:FREECAD_HOME) {
    $candidates += (Join-Path $env:FREECAD_HOME "bin\freecad.exe")
    $candidates += (Join-Path $env:FREECAD_HOME "Library\bin\freecad.exe")
}
$candidates += "C:\Program Files\FreeCAD 1.1\bin\freecad.exe"
$candidates += "C:\Program Files\FreeCAD 1.0\bin\freecad.exe"
$candidates += "D:\conda-envs\freecad\Library\bin\freecad.exe"
$FreeCadExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $FreeCadExe) {
    throw "freecad.exe not found. Install FreeCAD or set FREECAD_HOME to its root."
}
$BinDir = Split-Path $FreeCadExe

# --- environment ----------------------------------------------------------
# Put the FreeCAD binaries on PATH.  A conda env additionally needs its Library
# DLL folders and the env root (python3xx.dll lives there) or the GUI binary
# starts but silently fails to run the script; a standard install is
# self-contained in its bin folder.
$parts = @($BinDir)
if ($BinDir -match "Library\\bin$") {            # conda layout
    $libRoot = Split-Path $BinDir
    $envRoot = Split-Path $libRoot
    $parts += (Join-Path $libRoot "mingw-w64\bin")
    $parts += (Join-Path $libRoot "usr\bin")
    $parts += (Join-Path $envRoot "Scripts")
    $parts += $envRoot
}
$env:PATH = ($parts + $env:PATH) -join ";"
# NOTE on headless operation: FreeCAD 1.1's PDF export needs the Gui module,
# so it must run under freecad.exe (not freecadcmd).  Qt's "offscreen" platform
# would avoid a visible window but DEADLOCKS this build during TechDraw export,
# so it is NOT used.  A FreeCAD window therefore appears briefly (a few seconds)
# and closes itself automatically when the drawing is done.
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue

# --- resolve paths --------------------------------------------------------
# IMPORTANT: FreeCAD's script loader mishandles paths containing a backtick
# (e.g. "D:\`AI_Models\...") and silently runs a cached/older script instead.
# Copy the engine to a clean temp path and run that copy.  Parameters travel
# via environment variables and the engine is self-contained, so location
# doesn't matter.
$ScriptSrc = Join-Path $PSScriptRoot "step_to_drawing.py"
$runDir = Join-Path $env:TEMP "s2d_run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Remove-Item (Join-Path $runDir "__pycache__") -Recurse -Force -ErrorAction SilentlyContinue
# Use a UNIQUE basename: FreeCAD caches scripts by name, so a name it hasn't
# seen guarantees the current code runs (and avoids the 'step_to_drawing' cache).
$Script = Join-Path $runDir "s2d_engine.py"
Copy-Item $ScriptSrc $Script -Force
$InputFull = (Resolve-Path $StepFile).Path

# Pass parameters via environment variables, NOT command-line flags: the
# FreeCAD GUI binary parses dashed tokens itself and would abort on "--sheet".
$env:S2D_INPUT      = $InputFull
$env:S2D_OUTPUT     = if ($Output -ne "") { [System.IO.Path]::GetFullPath($Output) } else { "" }
$env:S2D_SHEET      = $Sheet
$env:S2D_TITLE      = $PartName
$env:S2D_MATERIAL   = $Material
$env:S2D_AUTHOR     = $Author
$env:S2D_DRAWING_NO = $DrawingNo
if ($Tolerance -ne "") { $env:S2D_TOLERANCE = $Tolerance } else { Remove-Item Env:\S2D_TOLERANCE -ErrorAction SilentlyContinue }

Write-Host "FreeCAD : $FreeCadExe"
Write-Host "Script  : $Script  (exists=$(Test-Path $Script))"
Write-Host "Input   : $InputFull"
Write-Host "Sheet   : $Sheet"
Write-Host "Running... (a FreeCAD window may flash briefly, then close itself)"

# NOTE: pass ONLY -PassThru.  The FreeCAD GUI binary refuses to run the script
# if its standard handles are redirected (-RedirectStandard*) or if it is
# attached to the parent console (-NoNewWindow).  Progress is captured in the
# .log file next to the output PDF instead.
$proc = Start-Process -FilePath $FreeCadExe -ArgumentList @("`"$Script`"") -PassThru
Wait-Process -Id $proc.Id -Timeout 300 -ErrorAction SilentlyContinue
if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
    throw "FreeCAD timed out (>300s) and was terminated."
}

# --- report ---------------------------------------------------------------
if ($Output -ne "") { $pdf = [System.IO.Path]::GetFullPath($Output) }
else { $pdf = [System.IO.Path]::ChangeExtension($InputFull, ".pdf") }

if (Test-Path $pdf) {
    Write-Host ("Done. PDF: {0} ({1:N0} bytes)" -f $pdf, (Get-Item $pdf).Length) -ForegroundColor Green
} else {
    $log = [System.IO.Path]::ChangeExtension($pdf, ".log")
    Write-Host "No PDF produced. Log follows:" -ForegroundColor Red
    if (Test-Path $log) { Get-Content $log }
    exit 1
}
