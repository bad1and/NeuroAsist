[CmdletBinding()]
param(
    [string]$Executable = "build\core\neuroasist-core\neuroasist-core.exe",
    [int]$Port = 18987
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$workingDirectory = Split-Path -Parent $resolvedExecutable
$environmentKeys = @(
    "NEUROASIST_SAFE_MODE",
    "NEUROASIST_PORT",
    "NEUROASIST_DESKTOP_TOKEN",
    "NEUROASIST_APP_DATA_DIR",
    "SQLITE_PATH",
    "VOICE_STT_PROVIDER",
    "VOICE_TTS_PROVIDER",
    "VOICE_PRELOAD_STT_MODEL",
    "VOICE_PRELOAD_TTS_MODEL",
    "AVATAR_ENABLED",
    "LOG_TO_FILE"
)
$previousEnvironment = @{}
foreach ($key in $environmentKeys) { $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process") }
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("neuroasist-packaged-runtime-" + [guid]::NewGuid())
$process = $null

try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:NEUROASIST_SAFE_MODE = "1"
    $env:NEUROASIST_PORT = [string]$Port
    $env:NEUROASIST_DESKTOP_TOKEN = $token
    $env:NEUROASIST_APP_DATA_DIR = $tempRoot
    $env:SQLITE_PATH = Join-Path $tempRoot "packaged.sqlite3"
    $env:VOICE_STT_PROVIDER = "mock"
    $env:VOICE_TTS_PROVIDER = "mock"
    $env:VOICE_PRELOAD_STT_MODEL = "false"
    $env:VOICE_PRELOAD_TTS_MODEL = "false"
    $env:AVATAR_ENABLED = "false"
    $env:LOG_TO_FILE = "false"
    $process = Start-Process -FilePath $resolvedExecutable -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru
    $health = $null
    $headers = @{ "X-NeuroAsist-Token" = $token }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -Headers $headers -TimeoutSec 2
            if ($health.StatusCode -eq 200) { break }
        } catch {
            if ($process.HasExited) { throw "Packaged runtime exited before /health became ready (exit code $($process.ExitCode))." }
        }
    }
    if ($null -eq $health -or $health.StatusCode -ne 200) { throw "Packaged runtime /health check timed out." }

    $unauthorized = $false
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null
    } catch {
        $response = $_.Exception.Response
        $unauthorized = $null -ne $response -and [int]$response.StatusCode -eq 401
    }
    if (-not $unauthorized) { throw "Packaged runtime accepted an unauthenticated request." }

    $shutdown = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$Port/internal/shutdown" -Headers $headers -TimeoutSec 5
    if (-not $process.WaitForExit(15000)) { throw "Packaged runtime did not exit after graceful shutdown." }
    [pscustomobject]@{
        health = $health.Content
        shutdown = $shutdown.Content
        exited = $process.HasExited
        exit_code = $process.ExitCode
    } | ConvertTo-Json -Compress
} finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    foreach ($key in $environmentKeys) {
        if ($null -eq $previousEnvironment[$key]) {
            Remove-Item "Env:$key" -ErrorAction SilentlyContinue
        } else {
            Set-Item "Env:$key" $previousEnvironment[$key]
        }
    }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
