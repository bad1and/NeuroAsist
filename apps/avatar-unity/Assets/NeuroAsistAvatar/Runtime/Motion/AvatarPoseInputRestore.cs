using UnityEngine;

namespace NeuroAsist.Avatar
{
    // Unwind procedural layers in reverse order BEFORE Animator evaluates the
    // next pose. Otherwise sparse clips can feed last frame's correction back in.
    [DefaultExecutionOrder(-1000)]
    internal sealed class AvatarPoseInputRestore : MonoBehaviour
    {
        internal AvatarPoseFilter Filter;
        internal AvatarArmRig Arms;
        internal AvatarContactController Contact;
        internal AvatarLifeController Life;
        internal AvatarBodyController Body;
        internal AvatarLookController Look;
        private void Update()
        {
            Arms?.RestoreInput();
            Contact?.Restore();
            Filter?.RestoreInput();
            Body?.RestoreInput();
            Life?.RestoreOffsets();
            Look?.RestoreLook();
        }
    }
}
