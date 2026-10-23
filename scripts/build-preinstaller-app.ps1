[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipAvatarBuild,
    [string]$AvatarPackage,
    [string]$AvatarPackageSha256,
    [switch]$RequireCleanWorktree,
    [string]$ArtifactDirectory = "artifacts"
)
$ErrorActionPreference = "Stop"
if (-not $SkipAvatarBuild -and -not $AvatarPackage) {
    & (Join-Path $PSScriptRoot "../apps/avatar-unity/scripts/build-windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Unity application preparation failed." }
}
& (Join-Path $PSScriptRoot "build-desktop-release.ps1") -AppOnly -SkipDependencyInstall:$SkipDependencyInstall -RequireCleanWorktree:$RequireCleanWorktree -ArtifactDirectory $ArtifactDirectory -AvatarPackage $AvatarPackage -AvatarPackageSha256 $AvatarPackageSha256
if ($LASTEXITCODE -ne 0) { throw "Application preparation failed." }
