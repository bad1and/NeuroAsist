using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    // Keep native baked curves compact; the authoring recipes live in C#.
    [PreferBinarySerialization]
    public sealed class AvatarGestureClipLibrary : ScriptableObject
    {
        public List<AnimationClip> Clips = new List<AnimationClip>();
    }
}
