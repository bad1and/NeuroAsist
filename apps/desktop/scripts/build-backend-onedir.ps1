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
    --collect-all transformers `
    --collect-all huggingface_hub `
    --collect-all num2words `
    --collect-all silero_vad `
    --collect-all onnxruntime `
    --hidden-import transformers.dynamic_module_utils `
    --exclude-module matplotlib `
    --exclude-module tensorboard `
    apps/backend/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller onedir build failed." }
