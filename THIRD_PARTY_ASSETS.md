# Third-party avatar assets

## Mixamo animations

The FBX motion clips in `apps/web/public/avatar/animations/` originate from
[Mixamo](https://www.mixamo.com/). They are retained as source references and
are loaded by the Three.js runtime through a normalized VRM humanoid retargeter.
The neutral, weight-shift, and look-around idles are now authored procedurally
on that normalized rig; the old Mixamo `Idle` and `Look Around` files remain
available as source references but are not used as the production idle layer.
The runtime never copies Mixamo quaternions onto Iris's raw bones: it removes
each source clip's bind rotation, applies the resulting relative pose to the
normalized VRM rig, and lets `VRMHumanoid.update()` write the model-specific
raw pose. This is required because the two rigs use different bone axes.

Adobe's public [Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html)
describes the animation library as free to use for personal, commercial and
non-profit projects. The [Mixamo Additional Terms](https://wwwimages2.adobe.com/content/dam/cc/en/legal/servicetou/Mixamo-Addl-Terms-en_US-20210623.pdf)
still apply, including restrictions on redistributing the original raw asset
files as a standalone asset pack.

Present and verified in the repository on 2026-08-12:

| Runtime file | Use | Notes |
| --- | --- | --- |
| `X Bot@Idle.fbx` | Source reference | Rejected as production idle: its exported entry/neutral pose is not suitable for Iris |
| `X Bot@Idle 1.fbx` | Source reference | Byte-identical to `X Bot@Idle.fbx`; not loaded twice |
| `X Bot@Look Around.fbx` | Source reference | Rejected as production idle: retained for future authored extraction, never played during speech |
| `X Bot@Batter On Deck.fbx` | Source reference | Rejected for idle: it is a baseball ready stance, not a neutral VTuber idle |
| `X Bot@Thinking.fbx` | Runtime thinking source | Full-body thinking gesture; retargeted through normalized VRM humanoid |
| `X Bot@Angry.fbx` | Runtime angry source | Tense reaction source |
| `X Bot@Surprised.fbx` | Runtime surprised source | Alert reaction source |
| `X Bot@Talking.fbx` | Runtime speech source | Looping speech body motion |
| `X Bot@TalkingQuestion.fbx` | Runtime question source | Looping question body motion |
| `X Bot@Agreeing.fbx` | Runtime agreement source | One-shot agreement gesture |
| `X Bot@Shaking Head No.fbx` | Runtime disagreement source | One-shot disagreement gesture |
| `X Bot@Waving.fbx` | Runtime greeting source | One-shot greeting gesture |
| `X Bot@WavingGoodbye.fbx` | Runtime farewell source | One-shot farewell gesture |
| `X Bot@Shrugging.fbx` | Runtime shrug source | One-shot shrug gesture |

### Role-based motion library

`apps/web/public/avatar/animations/manifest.json` is the stable registry for
the role-based downloads. On 2026-08-13, seven animation-only FBX files were
downloaded via Adobe Mixamo with `FBX Binary`, `Without Skin`, `30 FPS`, and
no keyframe reduction. The runtime retains a safe procedural or checked-in
fallback for every role, so an optional missing FBX cannot break a pose or
delay avatar startup.

| Runtime role | Requested Mixamo source | Runtime fallback |
| --- | --- | --- |
| `idle_calm_a` | Standing Idle | procedural soft sway |
| `idle_calm_b` | Neutral Idle | procedural shoulder release |
| `listening` | Unarmed Idle (neutral fallback; `Listening` only returned a music/headphone clip) | procedural attentive listening |
| `thinking` | Thinking | procedural thoughtful presence |
| `talk_calm` | Talking | `X Bot@Talking.fbx` |
| `talk_question` | Talking — Asking A Question | `X Bot@TalkingQuestion.fbx` |
| `accent_affirm` | Thoughtful Head Nod | `X Bot@Agreeing.fbx` |
| `accent_explain` | Shrugging | `X Bot@Shrugging.fbx` |

The `listening` fallback was selected but its browser download did not finish,
so it deliberately remains procedural. All raw source files remain embedded
application assets only and must not be republished as an asset pack.

The downloaded `Thinking` clip is retained as an embedded reference asset, but
is not played as Iris's presence loop: its source torso bend is unsuitable for
the portrait rig. The calibrated procedural `thinking` pose remains active.

Facial expressions are not Mixamo assets. They come from the VRM expression
blend shapes and are blended by the Three.js emotion controller. Production
idle motion is implemented in `apps/web/src/avatar/avatar-retarget.ts` so that
the neutral pose is explicit and independent from the source FBX bind frame.

## Unity Iris motion library

The active Unity avatar is `apps/avatar-unity/Assets/IRIS.vrm`. Its native VRM
expressions provide the face layer (`Joy`, `Angry`, `Sad`, `Surprise`, `Blink`
and phoneme visemes); body motion uses the clips under
`apps/avatar-unity/Assets/NeuroAsistAvatar/Animations/`.

| Motion role | Installed source | Runtime use |
| --- | --- | --- |
| Neutral body loop | `X Bot@Idle.fbx` | The sole persistent base stance, so every emotional transition has a compatible body pose. |
| Thinking pose | `X Bot@Thinking.fbx` | Upper-body entry / hold / exit gesture. |
| Tension / anger | `X Bot@Angry.fbx` | Short upper-body frustration reaction; also used at reduced intensity for annoyance. |
| Surprise | `X Bot@Surprised.fbx` | Brief one-shot reaction. |
| Speech / question | `X Bot@Talking.fbx`, `X Bot@TalkingQuestion.fbx` | Upper-body speech gestures. |
| Social accents | `Agreeing`, `Shaking Head No`, `Shrugging`, `Waving`, `WavingGoodbye` | One-shot gesture layer. |

`X Bot@Idle 1.fbx` is byte-identical to `X Bot@Idle.fbx` and is deliberately
not assigned. `X Bot@Batter On Deck.fbx` is deliberately not assigned: its
baseball-ready pose is unsuitable for a stationary portrait avatar.

### Requested Mixamo downloads

Mixamo requires an Adobe account for downloading, so no unauthenticated file is
committed as a substitute. Download candidate clips from
[Mixamo](https://www.mixamo.com/) with **FBX Binary**, **Without Skin**, **30
FPS**, and **no keyframe reduction**, then put them in the Unity animation
folder and retain them only after the Iris visual check passes.

| Search tag | Intended use | Acceptance rule |
| --- | --- | --- |
| `Standing Idle` | Calm breathing / weight transfer loop | Stationary feet and a neutral first frame. |
| `Neutral Idle` | Shoulder-release idle loop | No step, lean, or large arm arc. |
| `Look Around` | Brief observant glance | Use only if the head movement does not fight live head-look. |
| `Bored Idle` | Quiet waiting | No slouch that leaves the portrait frame. |
| `Thinking` | Hand-to-chin thought pose | Must retarget without hand/face clipping. |
| `Listening` or `Unarmed Idle` | Attentive listening | Keep only a neutral, prop-free variant. |

Every retained FBX is imported as **Humanoid**, with root rotation and root
position baked into pose. Only calm/talking clips loop; emotional reactions are
one-shots on the upper-body Avatar Mask. This prevents root drift, foot sliding,
and visible hard switches between emotions.
