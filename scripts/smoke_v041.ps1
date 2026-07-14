[CmdletBinding()]
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [int]$BackendPort = 18000,
    [int]$WebPort = 15173,
    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

if ($InstallDependencies) {
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Root npm dependency installation failed." }
    npm --prefix apps/web ci
    if ($LASTEXITCODE -ne 0) { throw "Web npm dependency installation failed." }
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("neuroasist-v041-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$backend = $null
$web = $null

try {
    $env:SQLITE_PATH = Join-Path $tempRoot "smoke.sqlite3"
    $env:VOICE_STT_PROVIDER = "mock"
    $env:VOICE_TTS_PROVIDER = "mock"
    $env:VOICE_PRELOAD_STT_MODEL = "false"
    $env:VOICE_PRELOAD_TTS_MODEL = "false"
    $env:AVATAR_ENABLED = "false"
    $env:LOG_TO_FILE = "false"

    $backend = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "$BackendPort") -PassThru -WindowStyle Hidden
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $web = Start-Process -FilePath $npm -ArgumentList @("--prefix", "apps/web", "run", "dev", "--", "--port", "$WebPort") -PassThru -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(30)
    do {
        if ($backend.HasExited) { throw "Backend process exited before health check." }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $deadline)
    if ($null -eq $health -or $health.status -ne "ok") { throw "Backend health check failed." }

    $deadline = (Get-Date).AddSeconds(30)
    do {
        if ($web.HasExited) { throw "Web process exited before its entrypoint became available." }
        try {
            $webResponse = Invoke-WebRequest "http://127.0.0.1:$WebPort" -UseBasicParsing -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $deadline)
    if ($null -eq $webResponse) { throw "Web entrypoint did not start." }
    if ($webResponse.StatusCode -ne 200) { throw "Web entrypoint returned $($webResponse.StatusCode)." }
    Write-Host "V0.4.1 smoke passed: backend and web started on loopback."
} finally {
    foreach ($child in @($web, $backend)) {
        if ($null -ne $child) {
            & taskkill.exe /PID $child.Id /T /F *> $null
        }
    }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
