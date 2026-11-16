# Build a Windows standalone distribution of Cryptoleaf.
# Run from the repository root: powershell -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing .venv. Create it with: python -m venv .venv"
}
& $python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) { throw "PyInstaller is unavailable in .venv" }

& $python -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name Cryptoleaf `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build\pyinstaller") `
    --specpath (Join-Path $root "build") `
    --collect-all soundfile `
    --collect-all pydub `
    --collect-all pywt `
    (Join-Path $root "Cryptoleaf.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed ($LASTEXITCODE)" }

$exe = Join-Path $root "dist\Cryptoleaf\Cryptoleaf.exe"
if (-not (Test-Path $exe)) { throw "Expected executable missing: $exe" }
Write-Host "Build completed: $exe"
Write-Host "Distribute the entire dist\Cryptoleaf directory, not just the EXE."
