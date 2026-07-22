[CmdletBinding()]
param(
    [string]$Python
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $Python = Join-Path $root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found at $Python"
}

$revision = "74a1d147b17a8c3092dd5430504bd83ef6c7eb23"
$package = "git+https://github.com/myshell-ai/OpenVoice.git@$revision"
& $Python -m pip install --no-deps --force-reinstall $package
if ($LASTEXITCODE -ne 0) {
    throw "Installing the pinned OpenVoice tone converter failed with exit code $LASTEXITCODE"
}

Write-Host "OpenVoice tone converter installed."
