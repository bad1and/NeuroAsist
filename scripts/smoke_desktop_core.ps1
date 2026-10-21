[CmdletBinding()]
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [int]$Port = 18041
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("neuroasist-desktop-core-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$core = $null
$loopbackRequest = @{}
$originalProxy = [System.Net.WebRequest]::DefaultWebProxy
if ((Get-Command Invoke-RestMethod).Parameters.ContainsKey("NoProxy")) {
    $loopbackRequest.NoProxy = $true
} else {
    [System.Net.WebRequest]::DefaultWebProxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
}

try {
    $token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:NEUROASIST_APP_DATA_DIR = $tempRoot
    $env:SQLITE_PATH = Join-Path $tempRoot "desktop.sqlite3"
    $env:NEUROASIST_PORT = $Port
    $env:NEUROASIST_DESKTOP_TOKEN = $token
    $env:VOICE_STT_PROVIDER = "mock"
    $env:VOICE_TTS_PROVIDER = "mock"
    $env:VOICE_PRELOAD_STT_MODEL = "false"
    $env:VOICE_PRELOAD_TTS_MODEL = "false"
    $env:AVATAR_ENABLED = "false"
    $env:LOG_TO_FILE = "false"

    $core = Start-Process -FilePath $Python -ArgumentList @("-m", "apps.backend.desktop_entry") -PassThru -WindowStyle Hidden
    $headers = @{ "X-NeuroAsist-Token" = $token }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        if ($core.HasExited) { throw "Desktop core exited before health check." }
        try {
            $health = Invoke-RestMethod @loopbackRequest "http://127.0.0.1:$Port/health" -Headers $headers -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $deadline)
    if ($null -eq $health -or $health.status -ne "ok") { throw "Authenticated desktop health check failed." }

    $unauthorized = $false
    try { Invoke-RestMethod @loopbackRequest "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null } catch { $unauthorized = [int]$_.Exception.Response.StatusCode -eq 401 }
    if (-not $unauthorized) { throw "Desktop core accepted an unauthenticated request." }

    Invoke-RestMethod @loopbackRequest "http://127.0.0.1:$Port/internal/shutdown" -Method Post -Headers $headers -TimeoutSec 2 | Out-Null
    if (-not $core.WaitForExit(8000)) { throw "Desktop core did not exit gracefully." }
    $core.WaitForExit()
    if ($null -eq $core.ExitCode -or $core.ExitCode -ne 0) { throw "Desktop core exited with code $($core.ExitCode) after shutdown; expected 0." }
    Write-Host "Desktop core smoke passed: authenticated startup and graceful shutdown."
} finally {
    [System.Net.WebRequest]::DefaultWebProxy = $originalProxy
    if ($null -ne $core -and -not $core.HasExited) { & taskkill.exe /PID $core.Id /T /F *> $null }
    $resolvedTemporary = [IO.Path]::GetFullPath($tempRoot)
    $temporaryParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($resolvedTemporary.StartsWith($temporaryParent, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
