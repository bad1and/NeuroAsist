using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [CreateAssetMenu(menuName = "Iris/Avatar/Motion Profile", fileName = "MotionProfile")]
    public sealed class MotionProfile : ScriptableObject
    {
        public string ProfileId = "neutral";
        public string BaseIdleState = AvatarMotionNames.DefaultIdleState;
        [Range(0.1f, 2f)] public float BaseIdleSpeed = 1f;
        [Min(0.1f)] public float IdleIntervalMinSeconds = 6f;
        [Min(0.1f)] public float IdleIntervalMaxSeconds = 15f;
        [Range(0f, 1f)] public float AlternativeIdleProbability = .45f;
        [Range(0f, 2f)] public float GestureFrequencyMultiplier = 1f;
        [Range(0f, 2f)] public float GestureIntensityMultiplier = 1f;
        [Range(0f, 1f)] public float HeadLookWeight = 1f;
        [Range(0.1f, 20f)] public float HeadTurnSpeed = 5f;
        public bool AllowLongIdleWhileSpeaking;
        public List<AlternativeIdleDefinition> AlternativeIdles = new List<AlternativeIdleDefinition>();

        public void ValidateValues()
        {
            IdleIntervalMinSeconds = Mathf.Max(.1f, IdleIntervalMinSeconds);
            IdleIntervalMaxSeconds = Mathf.Max(IdleIntervalMinSeconds, IdleIntervalMaxSeconds);
            BaseIdleSpeed = Mathf.Max(.1f, BaseIdleSpeed);
        }

        private void OnValidate() => ValidateValues();
    }

    [Serializable]
    public sealed class EmotionMotionProfile
    {
        public AvatarEmotion Emotion = AvatarEmotion.Neutral;
        public MotionProfile Profile;
    }
}
