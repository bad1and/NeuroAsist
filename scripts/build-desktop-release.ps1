[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$desktop = Join-Path $root "apps\desktop"
$tauri = Join-Path $desktop "src-tauri"
$binaries = Join-Path $tauri "binaries"
$output = Join-Path $root "build\core"

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found at $python"
}

if (-not $SkipDependencyInstall) {
    # requirements.txt is UTF-16 in the existing repository. pip expects UTF-8.
    $releaseRequirements = Join-Path $root "build\requirements-release.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $releaseRequirements) | Out-Null
    Get-Content -LiteralPath (Join-Path $root "requirements.txt") | Set-Content -Encoding utf8 -LiteralPath $releaseRequirements
    Add-Content -Encoding utf8 -LiteralPath $releaseRequirements "pyinstaller==6.21.0"
    & $python -m pip install --requirement $releaseRequirements
    Assert-LastExitCode "Installing release Python dependencies"
    & (Join-Path $root "scripts\install-openvoice.ps1") -Python $python
    Assert-LastExitCode "Installing OpenVoice tone converter"
    npm ci --prefix (Join-Path $root "apps\web")
    Assert-LastExitCode "Installing web dependencies"
    npm ci --prefix $desktop
    Assert-LastExitCode "Installing desktop dependencies"
}

$triple = ((rustc -Vv | Select-String '^host:').Line -replace '^host:\s*', '').Trim()
if (-not $triple) {
    throw "Could not determine the Rust target triple."
}

New-Item -ItemType Directory -Force -Path $binaries, $output | Out-Null
& $python -m PyInstaller --noconfirm --clean --onefile --name neuroasist-core `
    --paths $root `
    --add-data "$(Join-Path $root 'apps\protocol');apps\protocol" `
    --collect-all silero `
    --collect-all silero_vad `
    --collect-all gigaam `
    --collect-all openvoice `
    --collect-all onnxruntime `
    --collect-all torchaudio `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all av `
    --exclude-module matplotlib `
    --distpath $output `
    --workpath (Join-Path $root "build\pyinstaller-work") `
    --specpath (Join-Path $root "build\pyinstaller-spec") `
    (Join-Path $root "apps\backend\desktop_entry.py")
Assert-LastExitCode "Building the Neuro Core sidecar"

$sidecar = Join-Path $binaries "neuroasist-core-$triple.exe"
Copy-Item -Force (Join-Path $output "neuroasist-core.exe") $sidecar

# externalBin must exist when Tauri parses its config. Keep it release-only so
# cargo check and ordinary desktop development do not require a binary artifact.
$configPath = Join-Path $tauri "tauri.conf.json"
$originalConfig = Get-Content -Raw -LiteralPath $configPath
try {
    $config = $originalConfig | ConvertFrom-Json
    $config.bundle | Add-Member -NotePropertyName externalBin -NotePropertyValue @("binaries/neuroasist-core")
    $config | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $configPath
    npm --prefix $desktop run build
    Assert-LastExitCode "Building the NSIS installer"
}
finally {
    $originalConfig | Set-Content -Encoding utf8 -NoNewline -LiteralPath $configPath
}

Write-Host "Installer is in $tauri\target\release\bundle\nsis"
