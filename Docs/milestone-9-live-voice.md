# Milestone 9 — Live Voice, VAD and Barge-in

## Delivered

- The browser has an AudioWorklet RMS monitor with a deterministic VAD gate:
  speech onset and end are debounced before an utterance is submitted.
- Hands-free mode requests microphone constraints for echo cancellation, noise
  suppression and automatic gain control. Microphone audio stays in browser RAM;
  it is encoded only for the already-existing transient voice request and is not
  persisted as a raw recording.
- Push-to-talk remains available as the fallback path.
- A `PlaybackCoordinator` issues generation-scoped leases to either `unity` or
  `desktop_ui`. The browser only schedules segments for its own current lease.
- Beginning speech while the assistant is thinking/speaking performs barge-in in
  one action: browser audio stops, the active WebSocket utterance is cancelled,
  Unity receives the existing backend `avatar.stop`, and late frames are ignored.

## Compatibility boundary

The server still receives completed browser utterances through the existing
authenticated voice request, then streams LLM/TTS output over its Voice
WebSocket. A binary PCM input WebSocket, backend ring buffer and model-backed
Silero VAD require a model/runtime packaging decision from Milestone 10. The
current browser AudioWorklet is deliberately local and ephemeral, so it does
not introduce raw-audio storage or a new server-side recording surface.
