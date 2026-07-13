# Unity avatar runtime v0.4

The Unity runtime lives in the companion project `D:\Nero3DPizda\My project`; it is intentionally not copied into the NeuroAsist Git repository. It targets Unity **2022.3.62f3**, embedded UniVRM 1.0 packages, and uLipSync **3.1.5**.

## Flow

```text
React text or non-live voice → CharacterAgent → SpeechOrchestrator → complete WAV
→ /voice/audio/{file}.wav → avatar.speak over /ws/avatar → Unity AudioSource
→ existing uLipSync (or aa volume fallback) + VRM emotion
```

Unity is optional. A closed, restarting, or failed Unity client never changes successful chat/TTS results. `avatar.speak` broadcasts to every currently connected avatar client. Live browser voice remains browser-only in v0.4.

## One-time Unity setup

1. Open `D:\Nero3DPizda\My project` with Unity 2022.3.62f3.
2. Let Unity import `Assets/NeuroAsistAvatar/`; do not delete the existing `LipSyncAudio`, `Liqu.vrm`, or `uLipSync-Profile-New` assets.
3. Run **NeuroAsist → Avatar → Setup Canonical Scene**. This opens `Assets/хуй.unity`, adds only the `NeuroAsistAvatarRuntime` control object, retains the existing uLipSync object/profile, and adds this scene to Build Settings.
4. Run **NeuroAsist → Avatar → Validate Canonical Scene**. Fix only reported missing references.
5. In Play mode, set `AVATAR_ENABLED=true` in the backend `.env`, start the backend, then start Unity. The runtime connects to `ws://127.0.0.1:8000/ws/avatar?version=1`.

`AvatarRuntimeSettings` defaults to the local HTTP/WS endpoints. Change its URLs only for a different backend host. It contains no API key.

## Verification and diagnostics

- `GET http://127.0.0.1:8000/avatar/status` shows enabled state, clients, heartbeat, state, and current utterance.
- Settings → Avatar → **Send test phrase** queues real Silero full-WAV synthesis; **Send emotion** does not synthesize audio; **Stop avatar** returns the avatar to neutral.
- A 404 WAV error means the backend was restarted/cleaned its runtime audio or `VOICE_AUDIO_DIR` is wrong. Open the returned `/voice/audio/...` URL in a browser first.
- `[AvatarWS]` logs connection/reconnect/send errors, `[AvatarProtocol]` reports rejected frames, `[AvatarAudio]` reports download failures, `[LipSync]` reports fallback availability, `[Emotion]` reports missing expressions, and `[AvatarState]` is available through backend events.
- `Auto` lipsync retains the configured uLipSync component. It falls back to amplitude-driven VRM expression `aa` only when uLipSync is absent. Verify the VRM has `aa`, `ih`, `ou`, `ee`, `oh`, plus the required emotion presets.

## Tests and limits

Run Unity EditMode tests with the Test Runner after Unity imports the new asmdefs. The runtime deliberately has no live WAV segment support, phoneme timestamps, Rhubarb, body gestures, eye tracking, VRM hot-swap, or multiple-speaker ownership. Unity live segments are deferred to v0.4.1.

Manual smoke test: start backend with `AVATAR_ENABLED=true`; start React and Unity; confirm `/avatar/status` client count; send text; confirm an `avatar.speak` event only after `voice.tts_ready`; observe WAV playback/lip movement; send a second phrase during download; press Stop; restart backend and confirm Unity reconnects.
