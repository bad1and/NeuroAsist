[CmdletBinding()]
param(
    [string]$Python = "..\..\.venv\Scripts\python.exe",
    [string]$Output = "..\src-tauri\resources\core"
)

$ErrorActionPreference = "Stop"
$desktopRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repositoryRoot = Resolve-Path (Join-Path $desktopRoot "..\..")
Set-Location $repositoryRoot

if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
& $Python -m PyInstaller --noconfirm --clean --onedir --name neuroasist-core --distpath $Output `
    --collect-all openvoice `
    apps/backend/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller onedir build failed." }
