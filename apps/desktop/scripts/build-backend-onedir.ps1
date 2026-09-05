[CmdletBinding()]
param(
    [string]$Python,
    [string]$Output
)

$ErrorActionPreference = "Stop"
$desktopRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repositoryRoot = Resolve-Path (Join-Path $desktopRoot "..\..")
Set-Location $repositoryRoot

if (-not $Python) {
    $releaseEnvironment = Join-Path $repositoryRoot "build\release-venv"
    $Python = Join-Path $releaseEnvironment "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        $bootstrapPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $bootstrapPython)) {
            throw "Bootstrap Python virtual environment was not found at $bootstrapPython."
        }
        & $bootstrapPython -m venv $releaseEnvironment
        if ($LASTEXITCODE -ne 0) { throw "Creating the isolated release environment failed." }
        & $Python -m pip install --requirement (Join-Path $repositoryRoot "requirements\torch-cpu.txt")
        if ($LASTEXITCODE -ne 0) { throw "Installing the CPU PyTorch runtime failed." }
        & $Python -m pip install --requirement (Join-Path $repositoryRoot "requirements\build.txt")
        if ($LASTEXITCODE -ne 0) { throw "Installing isolated release dependencies failed." }
        & $Python (Join-Path $repositoryRoot "scripts\check_python_dependencies.py") --profile runtime --profile build --strict
        if ($LASTEXITCODE -ne 0) { throw "Validating isolated release dependencies failed." }
    }
}
if (-not $Output) { $Output = Join-Path $desktopRoot "src-tauri\resources\core" }
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python was not found at $Python."
}
& $Python -m PyInstaller --noconfirm --clean --onedir --name neuroasist-core --distpath $Output `
    --paths $repositoryRoot `
    --add-data "$(Join-Path $repositoryRoot 'VERSION');." `
    --add-data "$(Join-Path $repositoryRoot 'apps\protocol');apps\protocol" `
    --additional-hooks-dir (Join-Path $repositoryRoot "scripts\pyinstaller-hooks") `
    --collect-all gigaam `
    --collect-all transformers `
    --collect-all huggingface_hub `
    --collect-all num2words `
    --collect-all silero_vad `
    --collect-all onnxruntime `
    --collect-all torchaudio `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all av `
    --hidden-import transformers.dynamic_module_utils `
    --exclude-module matplotlib `
    apps/backend/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller onedir build failed." }
