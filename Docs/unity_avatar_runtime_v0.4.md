# Unity avatar runtime v0.5

The Unity runtime is an optional external project. Its source has not yet been published or pinned; see [Unity source handoff](unity-source.md). It targets Unity **2022.3.62f3**, UniVRM 1.0 and uLipSync 3.1.5.

## Performance defaults

The supported performance target is a **Windows Standalone Player**, not the Unity Editor. `AvatarPerformanceProfile` applies `AvatarLow` only in a player:

- 1280×720 window, 30 FPS and VSync disabled;
- HDR/MSAA, shadows, realtime reflection probes and anisotropic filtering disabled;
- one directional light, camera far plane capped at 20 metres, lower LOD bias.

The values are stored in `AvatarRuntimeSettings.asset`. Run **NeuroAsist → Avatar → Setup Canonical Scene**, then use **File → Build Settings → Windows → Build**. The Editor remains a development tool; profile the standalone development build with the CPU/GPU Profiler, Frame Debugger and Memory Profiler.

## Voice flow and compatibility

`VOICE_SILERO_DEVICE=cpu` is the recommended default: Whisper remains on CUDA and Unity keeps the GPU while Silero synthesizes on four CPU threads.

Protocol v1 remains compatible:

```text
full reply → complete WAV → avatar.speak → HTTP download → AudioSource
```

The runtime now connects to `ws://127.0.0.1:8000/ws/avatar?version=2` and advertises `[1, 2]`. A v2 client receives:

```text
avatar.stream.start → avatar.stream.segment (base64 PCM WAV, ordered) → avatar.stream.end
```

Segments are decoded into `AudioClip`s on the Unity main thread and played from an ordered FIFO. The first segment waits only the configured 200 ms prebuffer; the player does not wait for a complete LLM reply or an HTTP WAV download. `avatar.stop` clears the queue, destroys transient clips and rejects old utterance segments.

## Latency telemetry

Backend events record upload/STT elapsed time, first LLM delta and first TTS segment readiness. Unity reports `avatar.stream_segment_received` and `avatar.speaking_started` with client-side elapsed time from the server frame timestamp. Neither event contains speech text or audio.

## Smoke test

1. Set `AVATAR_ENABLED=true`, `VOICE_SILERO_DEVICE=cpu`; start backend and frontend.
2. Run the standalone avatar and confirm `/avatar/status` shows a v2 client.
3. Send live voice from the browser. Verify `avatar.stream.start`, ordered segment receipts, first playback, and cancellation when a second utterance starts.
4. Capture 30 seconds of idle and active speech. Accept only P95 CPU and GPU frame times ≤33.3 ms and P95 end-of-speech to first audio ≤2.5 s.
