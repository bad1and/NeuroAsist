[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipAvatarBuild,
    [switch]$RequireCleanWorktree,
    [string]$ArtifactDirectory = "artifacts"
)
$ErrorActionPreference = "Stop"
if (-not $SkipAvatarBuild) {
    & (Join-Path $PSScriptRoot "../apps/avatar-unity/scripts/build-windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Unity application preparation failed." }
}
& (Join-Path $PSScriptRoot "build-desktop-release.ps1") -AppOnly -SkipDependencyInstall:$SkipDependencyInstall -RequireCleanWorktree:$RequireCleanWorktree -ArtifactDirectory $ArtifactDirectory
if ($LASTEXITCODE -ne 0) { throw "Application preparation failed." }
