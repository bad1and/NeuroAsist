# Historical Qwen3-TTS quality pack

This document describes an isolated, historical Qwen experiment. Qwen is not
imported, installed, or selected by the base NeuroAsist backend. Production TTS
is TeraTTSv2 (`TeraSpace/TeraTTSv2`, voice `ru_f1`); Silero remains only the VAD
provider.

## Isolated environment

Create a separate virtual environment with CUDA PyTorch for the GTX 1660 SUPER,
then install `qwen-tts`. Do not install these packages into `.venv`. The worker
loads revision `c27fe8aa05b732b1376d0f6a1e522fbccb84abbd` with `float16` and
PyTorch SDPA; FlashAttention and BF16 are intentionally not required.

The old reference-preparation helper is no longer part of the production tree;
this historical gate only documents the isolated worker and existing reference
artifacts.

> [!WARNING]
> `data\voice-references\qwen-baya-neutral.wav` is not distributed in this
> repository. Reproducing the experiment requires a separately obtained,
> lawfully usable reference WAV and its exact transcript; point
> `--reference-wav` to that file. The command below preserves the historical
> filename only as an example.

Run the 100-segment gate using the isolated interpreter:

```powershell
<qwen-env>\Scripts\python.exe scripts\benchmark_qwen_tts.py `
  --python <qwen-env>\Scripts\python.exe `
  --reference-wav data\voice-references\qwen-baya-neutral.wav `
  --reference-text "Привет. Меня зовут Селера. Я говорю спокойно, ясно и естественно, сохраняя ровный и узнаваемый голос."
```

After the blind 20-pair comparison, repeat with `--blind-wins` and
`--similarity-median`. A report with `passed: false` must never activate Qwen.

## Promotion rule

Only a passing `gate-report.json` may be turned into a distributable
voice-quality pack. Its manifest must contain the pinned model revision and the
SHA-256 of every packaged artifact. Model Manager must verify all hashes before
launching the hidden worker. A missing or mismatched hash makes the historical
pack unhealthy before an utterance begins; production remains on the configured
TeraTTSv2 route.

Once a Qwen utterance has begun, provider and speaker are immutable. A failed
segment is retried once in the worker; a second failure stops audio while the
already generated text remains visible. This historical worker never changes
the production TeraTTS route.
