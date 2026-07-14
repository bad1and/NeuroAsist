using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [CreateAssetMenu(menuName = "NeuroAsist/Avatar/Gesture Definition", fileName = "GestureDefinition")]
    public sealed class GestureDefinition : ScriptableObject
    {
        public string Id = "TalkGesture01";
        public GestureTag Tag = GestureTag.Talk;
        public string AnimatorState = "TalkGesture01";
        [Min(.05f)] public float DurationSeconds = 1.5f;
        [Range(0f, 2f)] public float Weight = 1f;
        [Range(.1f, 2f)] public float Speed = 1f;
        [Min(0f)] public float CooldownSeconds = 4f;
        public bool CanRunWhileSpeaking = true;
        public bool CanInterrupt = true;
        [Range(0, 100)] public int Priority = 10;
        [Range(0f, 1f)] public float HeadLookSuppression;
        public List<AvatarEmotion> AllowedEmotions = new List<AvatarEmotion>();
        public List<AvatarEmotion> DeniedEmotions = new List<AvatarEmotion>();

        public bool Allows(AvatarEmotion emotion, bool speaking)
        {
            return (!speaking || CanRunWhileSpeaking)
                && !DeniedEmotions.Contains(emotion)
                && (AllowedEmotions.Count == 0 || AllowedEmotions.Contains(emotion));
        }
    }
}
