param(
    [Parameter(Mandatory = $true)] [string] $Binary,
    [Parameter(Mandatory = $true)] [string] $Model,
    [Parameter(Mandatory = $true)] [string] $Mmproj,
    [Parameter(Mandatory = $true)] [string] $Reference,
    [Parameter(Mandatory = $true)] [string] $Text,
    [Parameter(Mandatory = $true)] [string] $Output,
    [Parameter(Mandatory = $true)] [string] $Report,
    [string] $Tag = "qwen3-tts",
    [int] $PollMs = 500,
    [int] $Threads = 8,
    [int] $Seed = 12345,
    [int] $Frames = 0,
    [double] $RepeatPenalty = 0,
    [int] $RepeatLastN = -1,
    [string] $Language = "ru",
    [switch] $NoMmprojOffload,
    [switch] $FlashAttnOff,
    [switch] $CpuOnly
)

$ErrorActionPreference = "Stop"

function Get-GpuSample {
    $line = & nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits 2>$null
    if (-not $line) { return $null }
    $parts = $line -split "," | ForEach-Object { $_.Trim() }
    if ($parts.Count -lt 7) { return $null }
    return [ordered]@{
        name = $parts[0]
        memory_total_mib = [double]$parts[1]
        memory_used_mib = [double]$parts[2]
        memory_free_mib = [double]$parts[3]
        utilization_gpu_percent = [double]$parts[4]
        power_w = [double]$parts[5]
        temperature_c = [double]$parts[6]
    }
}

$binaryPath = (Resolve-Path $Binary).Path
$modelPath = (Resolve-Path $Model).Path
$mmprojPath = (Resolve-Path $Mmproj).Path
$referencePath = (Resolve-Path $Reference).Path
$outputPath = [IO.Path]::GetFullPath($Output)
$reportPath = [IO.Path]::GetFullPath($Report)
$stdoutPath = "$reportPath.stdout.log"
$stderrPath = "$reportPath.stderr.log"
New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($outputPath)) | Out-Null
New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($reportPath)) | Out-Null
Remove-Item $outputPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

function Quote-Argument([string] $value) {
    return '"' + ($value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

$gpuLayers = if ($CpuOnly) { "0" } else { "all" }
$arguments = @(
    "--model", (Quote-Argument $modelPath),
    "--mmproj", (Quote-Argument $mmprojPath),
    "--prompt", (Quote-Argument $Text),
    "--output", (Quote-Argument $outputPath),
    "--tts-lang", $Language,
    "--tts-speaker-file", (Quote-Argument $referencePath),
    "--gpu-layers", $gpuLayers,
    "--threads", "$Threads",
    "--threads-batch", "$Threads",
    "--seed", "$Seed",
    "--perf",
    "--log-colors", "off"
)
if ($NoMmprojOffload -or $CpuOnly) { $arguments += "--no-mmproj-offload" }
if ($FlashAttnOff -or $CpuOnly) { $arguments += @("--flash-attn", "off") }
if ($CpuOnly) { $arguments += @("--device", "none", "--no-op-offload") }
if ($Frames -gt 0) { $arguments += @("--n-predict", "$Frames") }
if ($RepeatPenalty -gt 0) { $arguments += @("--repeat-penalty", "$RepeatPenalty") }
if ($RepeatLastN -ge 0) { $arguments += @("--repeat-last-n", "$RepeatLastN") }

$baselineGpu = Get-GpuSample
$startedAt = Get-Date
$sw = [Diagnostics.Stopwatch]::StartNew()
$process = Start-Process -FilePath $binaryPath -ArgumentList ($arguments -join " ") -WorkingDirectory ([IO.Path]::GetDirectoryName($binaryPath)) -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
$samples = [Collections.Generic.List[object]]::new()
$peakWorkingSet = 0L
$peakPrivateBytes = 0L

while (-not $process.HasExited) {
    Start-Sleep -Milliseconds $PollMs
    try { $process.Refresh() } catch { }
    $gpu = Get-GpuSample
    if ($gpu) {
        $gpu.timestamp_ms = [int]$sw.ElapsedMilliseconds
        $samples.Add([pscustomobject]$gpu)
    }
    try {
        if ($process.WorkingSet64 -gt $peakWorkingSet) { $peakWorkingSet = $process.WorkingSet64 }
        if ($process.PrivateMemorySize64 -gt $peakPrivateBytes) { $peakPrivateBytes = $process.PrivateMemorySize64 }
    } catch { }
}

$sw.Stop()
$process.WaitForExit()
$process.Refresh()
$rawExitCode = $null
try { $rawExitCode = $process.ExitCode } catch { }
$finalGpu = Get-GpuSample
$gpuSamples = @($samples)
$peakGpu = $gpuSamples | Sort-Object memory_used_mib -Descending | Select-Object -First 1
$peakUtil = $gpuSamples | Measure-Object utilization_gpu_percent -Maximum
$peakPower = $gpuSamples | Measure-Object power_w -Maximum
$cpuMs = $null
try { $cpuMs = [int]$process.TotalProcessorTime.TotalMilliseconds } catch { }
$stderrText = Get-Content $stderrPath -Raw -ErrorAction SilentlyContinue
$audioWasWritten = Test-Path $outputPath
$inferenceCompleted = $audioWasWritten -and ($stderrText -match "wrote .+\.wav")
$exitCode = if ($null -ne $rawExitCode) { [int]$rawExitCode } elseif ($inferenceCompleted) { 0 } else { -1 }

$result = [ordered]@{
    tag = $Tag
    started_at = $startedAt.ToString("o")
    wall_ms = [int]$sw.ElapsedMilliseconds
    exit_code = $exitCode
    success = $inferenceCompleted
    command = ($binaryPath + " " + (($arguments | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '))
    model = $modelPath
    mmproj = $mmprojPath
    reference = $referencePath
    text = $Text
    output = $outputPath
    output_bytes = if (Test-Path $outputPath) { (Get-Item $outputPath).Length } else { 0 }
    cpu_time_ms = $cpuMs
    cpu_time_to_wall_ratio = if ($cpuMs) { [math]::Round($cpuMs / [math]::Max(1, $sw.ElapsedMilliseconds), 3) } else { $null }
    peak_process_working_set_mib = [math]::Round($peakWorkingSet / 1MB, 1)
    peak_process_private_mib = [math]::Round($peakPrivateBytes / 1MB, 1)
    gpu_baseline = $baselineGpu
    gpu_peak = if ($peakGpu) { $peakGpu } else { $null }
    gpu_final = $finalGpu
    peak_gpu_utilization_percent = if ($peakUtil.Maximum) { [double]$peakUtil.Maximum } else { $null }
    peak_gpu_power_w = if ($peakPower.Maximum) { [double]$peakPower.Maximum } else { $null }
    gpu_memory_delta_mib = if ($baselineGpu -and $peakGpu) { [math]::Round($peakGpu.memory_used_mib - $baselineGpu.memory_used_mib, 1) } else { $null }
    sample_count = $gpuSamples.Count
    samples = $gpuSamples
    stdout_log = $stdoutPath
    stderr_log = $stderrPath
}

$result | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
Write-Output ($reportPath)
Write-Output ("exit_code=" + $exitCode + " wall_ms=" + $result.wall_ms + " peak_gpu_used_mib=" + $(if ($peakGpu) { $peakGpu.memory_used_mib } else { "n/a" }))
