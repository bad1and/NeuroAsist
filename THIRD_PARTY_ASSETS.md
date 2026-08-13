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

Facial expressions are not Mixamo assets. They come from the VRM expression
blend shapes and are blended by the Three.js emotion controller. Production
idle motion is implemented in `apps/web/src/avatar/avatar-retarget.ts` so that
the neutral pose is explicit and independent from the source FBX bind frame.
