param(
    [string]$UnityEditor = $env:NEUROASIST_UNITY_EDITOR
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
if (-not $UnityEditor) {
    throw "Set NEUROASIST_UNITY_EDITOR to Unity.exe (Unity 2022.3.62f3)."
}
if (-not (Test-Path -LiteralPath $UnityEditor)) {
    throw "Unity editor was not found: $UnityEditor"
}

$arguments = @(
    '-batchmode',
    '-nographics',
    '-quit',
    '-projectPath', "`"$project`"",
    '-executeMethod', 'NeuroAsist.AvatarEditor.AvatarBuild.BuildWindows',
    '-logFile', "`"$project\Builds\avatar-build.log`""
)
$process = Start-Process -FilePath $UnityEditor -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Unity avatar build failed with exit code $($process.ExitCode). See $project\Builds\avatar-build.log" }
