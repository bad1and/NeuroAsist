using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [CreateAssetMenu(menuName = "NeuroAsist/Avatar/Motion Settings", fileName = "AvatarMotionSettings")]
    public sealed class AvatarMotionSettings : ScriptableObject
    {
        public bool MotionEnabled = true;
        public MotionProfile DefaultProfile;
        public List<EmotionMotionProfile> EmotionProfiles = new List<EmotionMotionProfile>();
        public List<GestureDefinition> GestureDefinitions = new List<GestureDefinition>();
        public bool IdleSchedulingEnabled = true;
        [Min(.1f)] public float AutoGestureIntervalMinSeconds = 3f;
        [Min(.1f)] public float AutoGestureIntervalMaxSeconds = 8f;
        [Range(0f, 1f)] public float AutoGestureProbability = .45f;
        [Range(0f, 1f)] public float DefaultMotionIntensity = 1f;
        public bool HeadLookEnabled = true;
        [Range(0f, 1f)] public float HeadLookWeight = 1f;
        public bool DebugLogging;

        public MotionProfile FindProfile(AvatarEmotion emotion)
        {
            for (var i = 0; i < EmotionProfiles.Count; i++)
                if (EmotionProfiles[i] != null && EmotionProfiles[i].Emotion == emotion && EmotionProfiles[i].Profile != null)
                    return EmotionProfiles[i].Profile;
            return DefaultProfile;
        }

        private void OnValidate()
        {
            AutoGestureIntervalMinSeconds = Mathf.Max(.1f, AutoGestureIntervalMinSeconds);
            AutoGestureIntervalMaxSeconds = Mathf.Max(AutoGestureIntervalMinSeconds, AutoGestureIntervalMaxSeconds);
        }
    }
}
