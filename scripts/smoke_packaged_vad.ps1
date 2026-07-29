[CmdletBinding()]
param(
    [string]$Core = ".\build\core\neuroasist-core.exe",
    [int]$Port = 18042
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
if (-not (Test-Path -LiteralPath $Core)) {
    throw "Packaged core not found at $Core"
}

$systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempRoot = Join-Path $systemTemp ("neuroasist-packaged-vad-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$coreProcess = $null

try {
    $token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:NEUROASIST_APP_DATA_DIR = $tempRoot
    $env:SQLITE_PATH = Join-Path $tempRoot "packaged.sqlite3"
    $env:NEUROASIST_PORT = $Port
    $env:NEUROASIST_DESKTOP_TOKEN = $token
    $env:VOICE_STT_PROVIDER = "mock"
    $env:VOICE_TTS_PROVIDER = "mock"
    $env:VOICE_PRELOAD_STT_MODEL = "false"
    $env:VOICE_PRELOAD_TTS_MODEL = "false"
    $env:VOICE_VAD_PROVIDER = "silero"
    $env:VOICE_SILERO_VAD_MODEL_PATH = ""
    $env:AVATAR_ENABLED = "false"
    $env:LOG_TO_FILE = "false"

    $coreProcess = Start-Process -FilePath $Core -PassThru -WindowStyle Hidden
    $headers = @{ "X-NeuroAsist-Token" = $token }
    $deadline = (Get-Date).AddSeconds(90)
    $publicSettings = $null
    do {
        if ($coreProcess.HasExited) {
            throw "Packaged core exited before the VAD status check."
        }
        try {
            $publicSettings = Invoke-RestMethod "http://127.0.0.1:$Port/settings/public" -Headers $headers -TimeoutSec 3
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ($null -eq $publicSettings -and (Get-Date) -lt $deadline)

    if ($null -eq $publicSettings) {
        throw "Packaged core did not become ready."
    }
    if (-not $publicSettings.voice_vad.ready -or $publicSettings.voice_vad.active_provider -ne "silero") {
        throw "Packaged Silero VAD is inactive: $($publicSettings.voice_vad | ConvertTo-Json -Compress)"
    }
    Write-Host "Packaged Silero VAD smoke passed: $($publicSettings.voice_vad | ConvertTo-Json -Compress)"
    Invoke-RestMethod "http://127.0.0.1:$Port/internal/shutdown" -Method Post -Headers $headers -TimeoutSec 3 | Out-Null
    if (-not $coreProcess.WaitForExit(10000)) {
        throw "Packaged core did not exit gracefully."
    }
}
finally {
    if ($null -ne $coreProcess -and -not $coreProcess.HasExited) {
        Stop-Process -Id $coreProcess.Id -Force
    }
    $resolvedTemp = [IO.Path]::GetFullPath($tempRoot)
    if ($resolvedTemp.StartsWith($systemTemp, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
