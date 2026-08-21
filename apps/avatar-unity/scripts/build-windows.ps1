param(
    [string]$UnityEditor = $env:NEUROASIST_UNITY_EDITOR
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$logFile = Join-Path $project "Builds\avatar-build.log"
$root = (Resolve-Path (Join-Path $project "..\..")).Path
$expectedVersion = (Get-Content -Raw -LiteralPath (Join-Path $root "VERSION")).Trim()
$playerSettings = Get-Content -Raw -LiteralPath (Join-Path $project "ProjectSettings\ProjectSettings.asset")
if ($playerSettings -notmatch "(?m)^\s*bundleVersion:\s*$([regex]::Escape($expectedVersion))\s*$") {
    throw "Unity bundleVersion does not match Iris $expectedVersion. Run scripts/check_docs.py."
}

function Show-BuildLog {
    if (Test-Path -LiteralPath $logFile) {
        Write-Host "`n--- Unity build log (last 100 lines): $logFile ---" -ForegroundColor Yellow
        Get-Content -LiteralPath $logFile -Tail 100
    }
    else {
        Write-Host "Unity did not create a build log: $logFile" -ForegroundColor Yellow
    }
}

if (-not $UnityEditor) {
    throw "NEUROASIST_UNITY_EDITOR is not set. Example: `$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'"
}
if (-not (Test-Path -LiteralPath $UnityEditor)) {
    throw "Unity editor was not found: $UnityEditor"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH. Unity needs Git to restore the uLipSync package from Packages/manifest.json. Install Git for Windows, reopen PowerShell, then run the build again."
}
if (Test-Path -LiteralPath (Join-Path $project "Temp\UnityLockfile")) {
    throw "The Unity project is locked. Close Unity Editor and every running build of NeuroAsistAvatar, then run the build again."
}

$arguments = @(
    '-batchmode',
    '-nographics',
    '-quit',
    '-projectPath', "`"$project`"",
    '-executeMethod', 'NeuroAsist.AvatarEditor.AvatarBuild.BuildWindows',
    '-logFile', "`"$logFile`""
)
Write-Host "Building Unity avatar with: $UnityEditor"
try {
    $process = Start-Process -FilePath $UnityEditor -ArgumentList $arguments -Wait -PassThru
}
catch {
    Show-BuildLog
    throw
}
if ($process.ExitCode -ne 0) {
    Show-BuildLog
    throw "Unity avatar build failed with exit code $($process.ExitCode)."
}
Write-Host "Avatar build completed: $project\Builds\NeuroAsistAvatar\NeuroAsistAvatar.exe" -ForegroundColor Green
