# Build a Windows standalone distribution of Cryptoleaf using Nuitka.
# Run from repository root: powershell -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing .venv. Create it with: python -m venv .venv"
}
& $python -m nuitka --version
if ($LASTEXITCODE -ne 0) { throw "Nuitka is unavailable in .venv" }

& $python -m nuitka `
    --mode=standalone `
    --enable-plugin=pyqt6 `
    --windows-console-mode=disable `
    --output-dir=dist `
    --output-filename=Cryptoleaf.exe `
    --remove-output `
    Cryptoleaf.py
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed ($LASTEXITCODE)" }

$exe = Join-Path $root "dist\Cryptoleaf.dist\Cryptoleaf.exe"
if (-not (Test-Path $exe)) { throw "Expected executable missing: $exe" }
Write-Host "Build completed: $exe"
Write-Host "Distribute the entire dist\Cryptoleaf.dist directory, not just the EXE."
