[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$desktop = Join-Path $root "apps\desktop"
$tauri = Join-Path $desktop "src-tauri"
$output = Join-Path $root "build\core"

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found at $python"
}

& $python (Join-Path $root "scripts\check_docs.py")
Assert-LastExitCode "Validating release metadata and documentation"

if (-not $SkipDependencyInstall) {
    # Keep the generated release requirements separate so PyInstaller remains
    # a build-only dependency and the pinned runtime file stays unchanged.
    $releaseRequirements = Join-Path $root "build\requirements-release.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $releaseRequirements) | Out-Null
    Get-Content -LiteralPath (Join-Path $root "requirements.txt") | Set-Content -Encoding utf8 -LiteralPath $releaseRequirements
    Add-Content -Encoding utf8 -LiteralPath $releaseRequirements "pyinstaller==6.21.0"
    & $python -m pip install --requirement $releaseRequirements
    Assert-LastExitCode "Installing release Python dependencies"
    npm ci --prefix (Join-Path $root "apps\web")
    Assert-LastExitCode "Installing web dependencies"
    npm ci --prefix $desktop
    Assert-LastExitCode "Installing desktop dependencies"
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
& $python -m PyInstaller --noconfirm --clean --onedir --name neuroasist-core `
    --paths $root `
    --add-data "$(Join-Path $root 'VERSION');." `
    --add-data "$(Join-Path $root 'apps\protocol');apps\protocol" `
    --collect-all silero_vad `
    --collect-all gigaam `
    --collect-all transformers `
    --collect-all huggingface_hub `
    --collect-all num2words `
    --hidden-import transformers.dynamic_module_utils `
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

$coreResource = Join-Path $output "neuroasist-core"
$coreExecutable = Join-Path $coreResource "neuroasist-core.exe"
if (-not (Test-Path -LiteralPath $coreExecutable)) {
    throw "PyInstaller onedir output is missing the core executable at $coreExecutable"
}

# Add the complete onedir tree as a Tauri resource only for the release build.
# The Rust shell launches core/neuroasist-core.exe directly, so Windows does
# not unpack a 442 MB onefile executable on every cold start.
$configPath = Join-Path $tauri "tauri.conf.json"
$originalConfig = Get-Content -Raw -LiteralPath $configPath
try {
    $config = $originalConfig | ConvertFrom-Json
    $config.bundle.resources | Add-Member -NotePropertyName "../../build/core/neuroasist-core" -NotePropertyValue "core"
    $config | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $configPath
    npm --prefix $desktop run build
    Assert-LastExitCode "Building the NSIS installer"
}
finally {
    $originalConfig | Set-Content -Encoding utf8 -NoNewline -LiteralPath $configPath
}

Write-Host "Installer is in $tauri\target\release\bundle\nsis"
