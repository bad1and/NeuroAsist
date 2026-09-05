[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$ReuseCore,
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

if (-not $SkipDependencyInstall) {
    # Never package from the long-lived developer environment. PyInstaller can
    # discover optional packages that are not in the application manifest, so
    # even a harmless old experiment can silently increase the installer.
    if (Test-Path -LiteralPath $releaseEnvironment) {
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
        --additional-hooks-dir (Join-Path $root "scripts\pyinstaller-hooks") `
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
    if (-not (Test-Path -LiteralPath $coreExecutable)) {
        throw "PyInstaller onedir output is missing the core executable at $coreExecutable"
    }
}

Remove-CudaLibraries $coreResource

# Add the complete onedir tree as a Tauri resource only for the release build.
# The Rust shell launches core/neuroasist-core.exe directly, so Windows does
# not unpack a 442 MB onefile executable on every cold start.
$configPath = Join-Path $tauri "tauri.conf.json"
$originalConfig = Get-Content -Raw -LiteralPath $configPath
try {
    $config = $originalConfig | ConvertFrom-Json
    $config.bundle.resources | Add-Member -NotePropertyName "../../../build/core/neuroasist-core" -NotePropertyValue "core"
    $config | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $configPath
    npm --prefix $desktop run build
    Assert-LastExitCode "Building the NSIS installer"
}
finally {
    $originalConfig | Set-Content -Encoding utf8 -NoNewline -LiteralPath $configPath
}

$smokeScript = Join-Path $root "scripts\smoke_packaged_runtime.ps1"
& $smokeScript -Executable $coreExecutable
Assert-LastExitCode "Smoking the packaged core"

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
