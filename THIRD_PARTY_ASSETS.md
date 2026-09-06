# Third-party avatar assets

## Unity Iris motion library

The FBX motion clips in
`apps/avatar-unity/Assets/NeuroAsistAvatar/Animations/` originate from
[Mixamo](https://www.mixamo.com/). Only clips assigned by the Unity runtime are
retained in the repository.

Adobe's public [Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html)
describes the animation library as free to use for personal, commercial and
non-profit projects. The [Mixamo Additional Terms](https://wwwimages2.adobe.com/content/dam/cc/en/legal/servicetou/Mixamo-Addl-Terms-en_US-20210623.pdf)
still apply, including restrictions on redistributing the original raw asset
files as a standalone asset pack.

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
