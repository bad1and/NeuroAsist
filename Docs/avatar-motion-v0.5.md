# Avatar motion v0.5

The Unity companion project is intentionally separate from this repository at `D:\Nero3DPizda\My project`. It uses Unity 2022.3.62f3, UniVRM 1.0, uLipSync 3.1.5 and Animation Rigging 1.2.1. Motion code lives under `Assets/NeuroAsistAvatar/Runtime/Motion`; it does not replace the VRM model, uLipSync profile, `AvatarEmotionController`, or the existing audio runtime.

## Runtime design

```text
avatar.speak { emotion, gesture }
  -> AvatarSpeechCoordinator -> AvatarMotionController
  -> AvatarIdleScheduler / AvatarGestureController / AvatarLookController
  -> Animator base layer + upper-body Gesture Layer

uLipSync and AvatarEmotionController continue to own mouth and VRM expressions.
```

`AvatarMotionController` selects `MotionProfile` from an emotion, informs the idle scheduler whether speech is active, handles interruption/reset, and disables `Animator.applyRootMotion`. It keeps the initial avatar-root transform and restores it after one-shots only when drift exceeds 2 cm. `AvatarIdleScheduler` has one controlled coroutine, deterministic random injection for tests, no immediate repeat, cooldowns and Micro/Normal/Long categories. Long idles are suppressed while speaking. `AvatarGestureController` has a generation token, so a completion from an interrupted gesture cannot reset a newer one. `AvatarLookController` supports an optional Animation Rigging `Rig`; without one it safely uses the Humanoid head as a fallback in `LateUpdate`.

The initial assets are slots, not bundled animations. No third-party clip is downloaded, created, or committed.

## Protocol and UI

Protocol v1 remains compatible. `avatar.speak` now optionally carries `gesture` (`auto` by default) and `gesture_intensity` (0..1); `avatar.gesture` accepts `{gesture, intensity, interrupt}`. Unknown gesture strings normalize to `auto`. Unity reports `avatar.gesture.started`, `.finished`, `.failed`, and `avatar.motion_profile_changed`; `/avatar/status` exposes the last profile and active gesture. The React Avatar panel offers a test-gesture selector, intensity, status, and reset.

Supported transport tags: `none`, `auto`, `talk`, `greeting`, `agreement`, `disagreement`, `question`, `explanation`, `thinking`, `surprise`, `frustration`, `farewell`, `shrug`.

For direct testing, call:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/avatar/test/gesture -Method Post -ContentType application/json -Body '{"gesture":"greeting","intensity":0.8,"interrupt":true}'
```

## One-time Unity setup

1. Open `D:\Nero3DPizda\My project` in Unity 2022.3.62f3 and let it import scripts.
2. Run **NeuroAsist → Avatar → Setup Motion Assets**. It creates `AvatarMotionSettings`, nine emotion profiles, a two-layer controller and `UpperBody.mask`, but deliberately leaves all animation slots empty.
3. Run **NeuroAsist → Avatar → Setup Canonical Scene**. This preserves the existing scene/VRM/uLipSync and wires the runtime, `AvatarHeadLookTarget`, settings and Animator. It only assigns the generated controller if the Animator had no controller.
4. Run **NeuroAsist → Avatar → Validate Avatar Motion Setup**. Resolve errors before Play mode. Warnings about slots with no clip are expected until clips are assigned.
5. In the Animator Controller, keep Base Layer states `IdleNeutral`, `IdleRelaxed`, `IdleEnergetic`, `IdleSad`, `IdleThinking`, `IdleLookAround`, `IdleShiftWeight`, `IdleSmallStretch`; Gesture Layer states are `Empty`, `TalkGesture01`, `Greeting`, `Agreement`, `Disagreement`, `Question`, `Explanation`, `Thinking`, `Surprise`, `Frustration`, `Farewell`, `Shrug`. Required parameters are `IsSpeaking` (Bool), `MotionIntensity` (Float), `BaseIdle` (Int). The runtime caches their hashes; `IsSpeaking` is the only required parameter at startup.
6. The generated `UpperBody.mask` includes Body/LeftArm/RightArm and excludes head, legs and root. Do not add head unless that gesture truly needs it; then set its `HeadLookSuppression` above zero.
7. Assign a camera-facing target to `AvatarHeadLookTarget`. For an Animation Rigging setup, create a `RigBuilder`, a `Rig` with `MultiAimConstraint` on the Humanoid head, target it at `AvatarHeadLookTarget`, then assign that `Rig` to `AvatarLookController`. The controller changes the rig weight during a gesture. The fallback works without a rig.

## Mixamo import and assignment

Download legally licensed clips yourself: **FBX for Unity**, **Without Skin**, 30 FPS. For each import use `Rig > Humanoid > Create From This Model`; verify its humanoid map against the VRM. For looping base idle clips set **Loop Time** and **Loop Pose**. Gestures and alternative idles are one-shots. For every clip set Root Transform Rotation, Position Y and Position XZ to **Bake Into Pose**. Do not enable root motion on the runtime Animator.

Suggested assignment: one loop to `IdleNeutral`; optional loops to the other base states; short one-shots to three alternative idle states; upper-body one-shots to the matching Gesture Layer states. For each state replace the empty Motion field with the imported clip. Then set `GestureDefinition` duration/speed/cooldown and permitted emotion lists; adjust profile idle intervals and gesture frequency as needed. Never commit animation assets unless their licence and repository use have been approved.

## Smoke checklist

1. Start backend with `AVATAR_ENABLED=true`, then React and Unity; confirm `/avatar/status` shows a client and neutral profile.
2. Wait 6–15 seconds: an alternative idle should run when a clip is assigned, never repeat immediately, and root position should remain stable.
3. Send a test phrase: uLipSync and facial emotion must continue; long idles must not run while speaking; `talk` gestures remain sparse.
4. Test `greeting`, `thinking`, `surprise`, `frustration`, and `farewell` from the UI. Start another command during a gesture and verify the old completion does not clear the newer gesture.
5. Confirm legs are unaffected, head motion remains smooth and clamped, and a gesture with head suppression restores tracking afterwards.
6. Remove a profile, clip, rig or disconnect backend: the runtime must log/skip safely rather than throw.

## Troubleshooting and limits

T-pose generally means a wrong Humanoid map, no controller, or an incompatible clip. Avatar drift means root transforms were not baked or `applyRootMotion` was re-enabled. Broken arms mean a bad retarget/map or mask. Head jitter means both a clip and the look rig control head, or smoothing/constraint weight is too high. Mouth problems mean an animation is touching face blendshapes; body clips must not do that.

No visual result is claimed until the clips are imported and Unity Play-mode smoke test is performed. This version does not provide locomotion, full-body IK, animation generation, finger tracking, webcam/eye tracking or automatic asset download. The code contains EditMode tests, but Unity Test Runner must be run locally because Unity was not available from the automation environment.
