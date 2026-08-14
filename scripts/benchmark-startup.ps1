[CmdletBinding()]
param(
    [ValidateSet("both", "clean", "cached")]
    [string]$Scenario = "both",
    [int]$TimeoutSeconds = 90,
    [string]$CoreExecutable,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$token = "startup-benchmark-token"

function Wait-Readiness {
    param(
        [System.Net.Http.HttpClient]$Client,
        [string]$BaseUrl,
        [string]$Target,
        [System.Diagnostics.Stopwatch]$Clock,
        [hashtable]$Times,
        [int]$TimeoutSeconds
    )

    while ($Clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $response = $Client.GetStringAsync("$BaseUrl/readiness").GetAwaiter().GetResult() | ConvertFrom-Json
            $now = [int]$Clock.Elapsed.TotalMilliseconds
            if (-not $Times.ContainsKey("text_ready_ms") -and $response.text_chat -eq "ready") { $Times.text_ready_ms = $now }
            if (-not $Times.ContainsKey("stt_ready_ms") -and $response.stt -eq "ready") { $Times.stt_ready_ms = $now }
            if (-not $Times.ContainsKey("tts_ready_ms") -and $response.tts -eq "ready") { $Times.tts_ready_ms = $now }
            if (-not $Times.ContainsKey("live_ready_ms") -and $response.live_ready) { $Times.live_ready_ms = $now }
            if ($Target -eq "text" -and $response.text_chat -eq "ready") { return }
            if ($Target -eq "live" -and $response.live_ready) { return }
        } catch {
            # The process may be alive before Uvicorn binds its port.
        }
        Start-Sleep -Milliseconds 100
    }
}

function Measure-Startup {
    param(
        [string]$Name,
        [string]$DataRoot
    )

    $port = Get-Random -Minimum 18000 -Maximum 48000
    $baseUrl = "http://127.0.0.1:$port"
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    if ($CoreExecutable) {
        $startInfo.FileName = (Resolve-Path -LiteralPath $CoreExecutable).Path
        $startInfo.Arguments = ""
    } else {
        if (-not (Test-Path -LiteralPath $python)) { throw "Python virtual environment not found at $python" }
        $startInfo.FileName = $python
        $startInfo.Arguments = "-m apps.backend.desktop_entry"
    }
    $startInfo.WorkingDirectory = $root
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    foreach ($item in @{
        NEUROASIST_PORT = "$port"
        NEUROASIST_DESKTOP_TOKEN = $token
        NEUROASIST_APP_DATA_DIR = $DataRoot
        LOG_TO_FILE = "false"
        AVATAR_ENABLED = "false"
    }.GetEnumerator()) {
        $startInfo.Environment[$item.Key] = $item.Value
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $times = @{}
    $client = $null
    $started = $false
    try {
        if (-not $process.Start()) { throw "Could not start benchmark backend" }
        $started = $true
        $spawnMs = [int]$clock.Elapsed.TotalMilliseconds
        $client = [System.Net.Http.HttpClient]::new()
        $client.DefaultRequestHeaders.Add("X-NeuroAsist-Token", $token)
        $healthDeadline = $clock.Elapsed.TotalSeconds + $TimeoutSeconds
        while ($clock.Elapsed.TotalSeconds -lt $healthDeadline) {
            try {
                $null = $client.GetStringAsync("$baseUrl/health").GetAwaiter().GetResult()
                $times.backend_health_ms = [int]$clock.Elapsed.TotalMilliseconds
                break
            } catch {
                Start-Sleep -Milliseconds 100
            }
        }

        Wait-Readiness -Client $client -BaseUrl $baseUrl -Target "text" -Clock $clock -Times $times -TimeoutSeconds $TimeoutSeconds
        Wait-Readiness -Client $client -BaseUrl $baseUrl -Target "live" -Clock $clock -Times $times -TimeoutSeconds $TimeoutSeconds
        $times.process_spawn_ms = $spawnMs
    } catch {
        $times.error = $_.Exception.Message
    } finally {
        if ($client) {
            try { $null = $client.PostAsync("$baseUrl/internal/shutdown", $null).GetAwaiter().GetResult() } catch { }
        }
        if ($started -and $process.HasExited -eq $false) {
            # Kill only the process tree spawned by this benchmark iteration;
            # the process id is explicit and never comes from workspace data.
            try { $process.Kill($true) } catch { }
            try { taskkill.exe /PID $process.Id /T /F *> $null } catch { }
        }
        if ($client) { $client.Dispose() }
        $process.Dispose()
    }
    $times.scenario = $Name
    $times.data_root = $DataRoot
    $times.timeout = -not $times.ContainsKey("text_ready_ms")
    return [pscustomobject]$times
}

$benchmarkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("iris-startup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $benchmarkRoot | Out-Null
try {
    $results = [System.Collections.Generic.List[object]]::new()
    if ($Scenario -in @("both", "clean")) {
        $cleanRoot = Join-Path $benchmarkRoot "profile"
        $results.Add((Measure-Startup -Name "clean" -DataRoot $cleanRoot))
    }
    if ($Scenario -in @("both", "cached")) {
        $cachedRoot = Join-Path $benchmarkRoot "profile"
        if ($Scenario -eq "cached" -and -not (Test-Path -LiteralPath $cachedRoot)) {
            New-Item -ItemType Directory -Force -Path $cachedRoot | Out-Null
        }
        $results.Add((Measure-Startup -Name "cached" -DataRoot $cachedRoot))
    }
    $json = $results | ConvertTo-Json -Depth 5
    if ($OutputPath) {
        $json | Set-Content -Encoding utf8 -LiteralPath $OutputPath
    }
    $json
} catch {
    Write-Host ("Benchmark failed: " + $_.Exception.Message)
    throw
} finally {
    Remove-Item -LiteralPath $benchmarkRoot -Recurse -Force -ErrorAction SilentlyContinue
}
