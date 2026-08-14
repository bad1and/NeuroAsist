using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [CreateAssetMenu(menuName = "Iris/Avatar/Gesture Definition", fileName = "GestureDefinition")]
    public sealed class GestureDefinition : ScriptableObject
    {
        public string Id = "TalkGesture01";
        public GestureTag Tag = GestureTag.Talk;
        public string AnimatorState = "TalkGesture01";
        [Tooltip("Optional safe alternatives of the same upper-body clip (for example a mirrored state).")]
        public List<string> VariantAnimatorStates = new List<string>();
        [Min(.05f)] public float BlendInSeconds = .55f;
        [Min(.05f)] public float DurationSeconds = 1.5f;
        [Min(.05f)] public float BlendOutSeconds = .65f;
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

        public string SelectAnimatorState(IMotionRandom random, ICollection<string> excluded = null)
        {
            var choices = new List<string>();
            if (!string.IsNullOrWhiteSpace(AnimatorState)) choices.Add(AnimatorState);
            foreach (var state in VariantAnimatorStates)
                if (!string.IsNullOrWhiteSpace(state) && !choices.Contains(state)) choices.Add(state);
            if (choices.Count == 0) return null;
            if (excluded != null && choices.Count > 1)
            {
                var fresh = choices.FindAll(value => !excluded.Contains(value));
                if (fresh.Count > 0) choices = fresh;
            }
            return choices[random.Range(0, choices.Count)];
        }
    }
}
