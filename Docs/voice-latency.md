# Live voice latency

The user-facing latency budget is measured from the last audible input frame to
the first audible assistant frame. It is not measured from the VAD boundary,
because the boundary is emitted only after an intentional silence window.

## Critical path

```text
last speech frame
  -> VAD endpoint silence
  -> Smart Turn
  -> GigaAM STT
  -> conversation decision and persistence
  -> first DeepSeek delta / first speakable text boundary
  -> TeraTTSv2
  -> WebSocket + browser WAV decode + AudioContext lead
  -> first audible frame
```

The response path stays fully streamed at the text/segment level. TeraTTSv2 is
kept unchanged and remains preloaded and warmed on startup.

## Local baseline (2026-09-23)

Measurements were taken with the checked-in configuration on this 16-logical-
CPU Windows host, after model warmup:

| Stage | Measured latency |
| --- | ---: |
| Smart Turn v3.2 | 47–57 ms typical; 175 ms first measured call |
| GigaAM v3 RNNT, 1.9–4.1 s fixtures | 177–256 ms |
| TeraTTSv2, `ru_f1`, 3 characters | 217 ms |
| TeraTTSv2, `ru_f1`, 25 characters | 268 ms |
| TeraTTSv2, `ru_f1`, 53 characters | 378 ms |
| Browser playback lead (old default) | 30 ms |

TeraTTS native generation yielded its first internal chunk only 24–74 ms before
the complete tested segment. Converting that internal generator into multiple
standalone WAV messages would complicate pause placement, post-processing and
cancellation for a relatively small first-audio gain. The safer optimization is
therefore to send a shorter first textual segment into the same model sooner.

On this host, TeraTTS thread-count medians for the same phrase were 288 ms (4
threads), 297 ms (8 threads) and 311 ms (12 threads). The difference is too
small and noisy to justify changing the existing 8-thread default globally.

## Current low-latency profile

- Smart Turn receives a candidate after 350 ms of silence in the natural pause
  profile. If it reports an incomplete turn, existing continuation assembly and
  the conservative 2.5 s forced-endpoint safeguard remain in force.
- The first safe text fragment targets 24 characters and can idle-flush after
  80 ms. A fragment is still released only on whitespace or punctuation and
  never in the middle of a token.
- Browser playback uses one decoded segment, no time prebuffer and a 10 ms
  scheduling lead.
- The exact end-of-speech stopwatch is propagated through endpoint, STT,
  decision, first LLM delta, first speakable segment, first TTS segment and
  browser playback acknowledgement.

The relevant event stream now includes:

- `voice.endpoint_detected`
- `voice.stt_completed`
- `voice.decision_completed`
- `voice.llm_first_delta`
- `voice.first_speakable_segment`
- `voice.tts_first_segment_ready`
- `voice.end_of_speech_to_playback`

Use the final event's `end_of_speech_to_playback_ms` as the acceptance metric.
Track P50 and P95 separately for warm startup and cold startup. The release gate
remains P95 <= 2.5 seconds; the practical warm target is P50 <= 1.5 seconds.

## Remaining optimization order

1. Collect at least 30 real microphone turns and group the events by
   `utterance_id` to identify the dominant stage on the actual DeepSeek route.
2. If `voice.llm_first_delta` dominates, reduce prompt construction and remote
   first-token latency; TTS tuning cannot hide that stage.
3. If TTS dominates despite short first segments, prototype native audio
   streaming behind a feature flag and require gapless playback/cancellation
   tests before enabling it.
4. Do not reduce endpoint silence further without real-audio false-cutoff tests
   for quiet endings, short pauses and unfinished clauses.
