[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$ReuseCore,
    [switch]$AppOnly,
    [string]$ArtifactDirectory = "artifacts",
    [switch]$RequireCleanWorktree,
    [string]$SigningCertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bootstrapPython = Join-Path $root ".venv\Scripts\python.exe"
$releaseEnvironment = Join-Path $root "build\release-venv"
$python = Join-Path $releaseEnvironment "Scripts\python.exe"
$desktop = Join-Path $root "apps\desktop"
$tauri = Join-Path $desktop "src-tauri"
$output = Join-Path $root "build\core"
$avatarResource = Join-Path $root "apps\avatar-unity\Builds\NeuroAsistAvatar"
$avatarExecutable = Join-Path $avatarResource "NeuroAsistAvatar.exe"
$version = (Get-Content -Raw -LiteralPath (Join-Path $root "VERSION")).Trim()
$artifactRoot = if ([IO.Path]::IsPathFullyQualified($ArtifactDirectory)) {
    $ArtifactDirectory
} else {
    Join-Path $root $ArtifactDirectory
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

# Iris 1.0 ships a CPU base sidecar.  The development PyTorch wheel can carry
# several GiB of optional CUDA DLLs even though the shipped default is
# VOICE_STT_DEVICE=cpu.  NSIS cannot package an input above 2 GiB, and the CPU
# runtime must not advertise GPU support it does not contain.
$cudaLibraryPrefixes = @(
    "c10_cuda", "caffe2_nvrtc", "cublas", "cuda", "cudart", "cudnn",
    "cufft", "curand", "cusolver", "cusparse", "cupti", "nvjitlink",
    "nvperf", "nvrtc", "nvtoolsext", "torch_cuda"
)

function Remove-CudaLibraries([string]$SidecarRoot) {
    $resolvedSidecar = (Resolve-Path -LiteralPath $SidecarRoot -ErrorAction Stop).Path
    $cudaLibraries = @(
        Get-ChildItem -LiteralPath $resolvedSidecar -Recurse -File -Filter "*.dll" |
        Where-Object {
            $libraryName = $_.Name.ToLowerInvariant()
            $cudaLibraryPrefixes | Where-Object { $libraryName.StartsWith($_) } | Select-Object -First 1
        }
    )

    foreach ($library in $cudaLibraries) {
        Remove-Item -LiteralPath $library.FullName -Force
    }
    if ($cudaLibraries.Count -gt 0) {
        Write-Host "Removed $($cudaLibraries.Count) CUDA-only DLL(s) from the CPU release sidecar."
    }

    $remaining = Get-ChildItem -LiteralPath $resolvedSidecar -Recurse -File -Filter "*.dll" |
        Where-Object {
            $libraryName = $_.Name.ToLowerInvariant()
            $cudaLibraryPrefixes | Where-Object { $libraryName.StartsWith($_) } | Select-Object -First 1
        }
    if ($null -ne $remaining) {
        throw "CPU release sidecar still contains CUDA-only DLL(s): $($remaining.FullName -join '; ')"
    }
}

if ($RequireCleanWorktree) {
    $changes = @(git status --porcelain --untracked-files=all)
    Assert-LastExitCode "Checking release worktree"
    if ($changes.Count -gt 0) {
        throw "Release build requires a clean worktree. Commit, stash, or remove: $($changes -join '; ')"
    }
}

if (-not (Test-Path -LiteralPath $bootstrapPython)) {
    throw "Bootstrap Python virtual environment not found at $bootstrapPython"
}
if (-not (Test-Path -LiteralPath $avatarExecutable)) {
    throw "Release build requires the Unity avatar at $avatarExecutable. Build it with npm --prefix apps/desktop run build:avatar first."
}

& $bootstrapPython (Join-Path $root "scripts\check_docs.py")
Assert-LastExitCode "Validating release metadata and documentation"
$sourceRecord = Join-Path $root "build\preinstaller-source.json"
if ($AppOnly) {
    & $bootstrapPython (Join-Path $root "scripts\check_preinstaller_app.py") --record-source --output $sourceRecord
    Assert-LastExitCode "Recording build sources"
}

if (-not $SkipDependencyInstall) {
    # Never package from the long-lived developer environment. PyInstaller can
    # discover optional packages that are not in the application manifest, so
    # even a harmless old experiment can silently increase the installer.
    if (Test-Path -LiteralPath $releaseEnvironment) {
        $resolvedEnvironment = (Resolve-Path -LiteralPath $releaseEnvironment).Path
        $buildRoot = [IO.Path]::GetFullPath((Join-Path $root "build")) + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedEnvironment.StartsWith($buildRoot, [StringComparison]::OrdinalIgnoreCase) -or ((Get-Item -LiteralPath $releaseEnvironment).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to replace a release environment outside build/: $resolvedEnvironment"
        }
        Remove-Item -LiteralPath $releaseEnvironment -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $releaseEnvironment) | Out-Null
    & $bootstrapPython -m venv $releaseEnvironment
    Assert-LastExitCode "Creating isolated release Python environment"
    & $python -m pip install --requirement (Join-Path $root "requirements\torch-cpu.txt")
    Assert-LastExitCode "Installing CPU PyTorch runtime"
    & $python -m pip install --requirement (Join-Path $root "requirements\build.txt")
    Assert-LastExitCode "Installing release Python dependencies"
    & $python (Join-Path $root "scripts\check_python_dependencies.py") --profile runtime --profile build --strict
    Assert-LastExitCode "Validating isolated release Python dependencies"
    npm ci --prefix (Join-Path $root "apps\web")
    Assert-LastExitCode "Installing web dependencies"
    npm ci --prefix $desktop
    Assert-LastExitCode "Installing desktop dependencies"
}
elseif (-not (Test-Path -LiteralPath $python)) {
    throw "-SkipDependencyInstall requires the isolated release environment at $releaseEnvironment"
}

$coreResource = Join-Path $output "neuroasist-core"
$coreExecutable = Join-Path $coreResource "neuroasist-core.exe"
if ($ReuseCore) {
    if (-not (Test-Path -LiteralPath $coreExecutable)) {
        throw "-ReuseCore was requested but the existing PyInstaller output is missing $coreExecutable"
    }
} else {
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    & $python -m PyInstaller --noconfirm --clean --onedir --name neuroasist-core `
        --paths $root `
        --add-data "$(Join-Path $root 'VERSION');." `
        --add-data "$(Join-Path $root 'apps\protocol');apps\protocol" `
        --add-data "$(Join-Path $root 'apps\backend\app\model_manager\catalog.json');apps\backend\app\model_manager" `
        --add-data "$(Join-Path $root 'apps\backend\docker');apps\backend\docker" `
        --additional-hooks-dir (Join-Path $root "scripts\pyinstaller-hooks") `
        --collect-all silero_vad `
        --collect-all gigaam `
        --collect-all transformers `
        --collect-all huggingface_hub `
        --collect-all num2words `
        --hidden-import transformers.dynamic_module_utils `
        --collect-all onnxruntime `
        --collect-all onnx_asr `
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
    if (-not (Test-Path -LiteralPath $coreExecutable)) {
        throw "PyInstaller onedir output is missing the core executable at $coreExecutable"
    }
}

Remove-CudaLibraries $coreResource

# Add the complete onedir tree as a Tauri resource only for the release build.
# The Rust shell launches core/neuroasist-core.exe directly, so Windows does
# not unpack a 442 MB onefile executable on every cold start.
$overridePath = Join-Path $root "build\tauri-release.config.json"
$override = @{ bundle = @{ resources = @{ "../../../build/core/neuroasist-core" = "core" } } }
$override | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath $overridePath
$buildArguments = @("--config", $overridePath)
if ($AppOnly) { $buildArguments += "--no-bundle" }
npm --prefix $desktop run build -- @buildArguments
Assert-LastExitCode "Building the desktop application"

$smokeScript = Join-Path $root "scripts\smoke_packaged_runtime.ps1"
& $smokeScript -Executable $coreExecutable
Assert-LastExitCode "Smoking the packaged core"

if ($AppOnly) {
    $applicationDirectory = Join-Path $artifactRoot "iris-$version-app"
    New-Item -ItemType Directory -Force -Path $applicationDirectory | Out-Null
    if (@(Get-ChildItem -LiteralPath $applicationDirectory -Force).Count -ne 0) {
        throw "Application staging directory must be empty: $applicationDirectory. Choose a new -ArtifactDirectory."
    }
    Copy-Item -LiteralPath (Join-Path $tauri "target\release\neuroasist-desktop.exe") -Destination (Join-Path $applicationDirectory "Iris.exe")
    Copy-Item -LiteralPath $coreResource -Destination (Join-Path $applicationDirectory "core") -Recurse
    New-Item -ItemType Directory -Path (Join-Path $applicationDirectory "avatar") | Out-Null
    Get-ChildItem -LiteralPath $avatarResource -Force | Where-Object { $_.Name -ne ".gitkeep" -and $_.Name -notlike "*DoNotShip*" } | Copy-Item -Destination (Join-Path $applicationDirectory "avatar") -Recurse
    Copy-Item -LiteralPath (Join-Path $root "LICENSE"), (Join-Path $root "PRIVACY.md"), (Join-Path $root "THIRD_PARTY_ASSETS.md") -Destination $applicationDirectory
    & $python (Join-Path $root "scripts\create_dependency_inventory.py") --output (Join-Path $applicationDirectory "licenses")
    Assert-LastExitCode "Collecting dependency notices"
    & $python (Join-Path $root "scripts\check_preinstaller_app.py") --app $applicationDirectory --source-record $sourceRecord --output (Join-Path $artifactRoot "iris-$version-app-manifest.json")
    Assert-LastExitCode "Validating the staged application"
    Write-Host "Application candidate without installer: $applicationDirectory"
    return
}

$installerDirectory = Join-Path $tauri "target\release\bundle\nsis"
$installer = Get-ChildItem -LiteralPath $installerDirectory -Filter "*.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $installer) {
    throw "NSIS build did not produce an installer in $installerDirectory"
}

$signingStatus = "unsigned"
if ($SigningCertificateThumbprint) {
    $signTool = (Get-Command signtool.exe -ErrorAction Stop).Source
    & $signTool sign /sha1 $SigningCertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $installer.FullName
    Assert-LastExitCode "Authenticode-signing the NSIS installer"
    $signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
    if ($signature.Status -ne "Valid") {
        throw "Installer signature is not valid: $($signature.Status) $($signature.StatusMessage)"
    }
    $signingStatus = "authenticode"
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$publishedInstaller = Join-Path $artifactRoot $installer.Name
Copy-Item -LiteralPath $installer.FullName -Destination $publishedInstaller -Force
$manifest = Join-Path $artifactRoot "iris-$version-release-manifest.json"
& $python (Join-Path $root "scripts\check_release_artifact.py") `
    --artifact $publishedInstaller `
    --staging $coreResource `
    --staging $avatarResource `
    --version $version `
    --signing-status $signingStatus `
    --output $manifest
Assert-LastExitCode "Validating release artifact contents and manifest"

Write-Host "Release candidate installer: $publishedInstaller"
Write-Host "Release candidate manifest: $manifest"
