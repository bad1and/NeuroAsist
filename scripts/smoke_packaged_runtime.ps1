[CmdletBinding()]
param(
    [string]$Executable = "build\core-smoke\neuroasist-core\neuroasist-core.exe",
    [int]$Port = 18987
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$workingDirectory = Split-Path -Parent $resolvedExecutable
$previousSafeMode = $env:NEUROASIST_SAFE_MODE
$previousPort = $env:NEUROASIST_PORT
$process = $null

try {
    $env:NEUROASIST_SAFE_MODE = "1"
    $env:NEUROASIST_PORT = [string]$Port
    $process = Start-Process -FilePath $resolvedExecutable -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru
    $health = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.StatusCode -eq 200) { break }
        } catch {
            if ($process.HasExited) { throw "Packaged runtime exited before /health became ready (exit code $($process.ExitCode))." }
        }
    }
    if ($null -eq $health -or $health.StatusCode -ne 200) { throw "Packaged runtime /health check timed out." }

    $shutdown = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$Port/internal/shutdown" -TimeoutSec 5
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
    $env:NEUROASIST_SAFE_MODE = $previousSafeMode
    $env:NEUROASIST_PORT = $previousPort
}
