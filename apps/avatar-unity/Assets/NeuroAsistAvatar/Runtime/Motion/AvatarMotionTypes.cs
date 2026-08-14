using System;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public enum AvatarEmotion { Neutral, Happy, Sad, Angry, Surprised, Relaxed, Thinking, Annoyed, Smirk }
    public enum GestureTag { None, Auto, Talk, Greeting, Agreement, Disagreement, Question, Explanation, Thinking, Surprise, Frustration, Farewell, Shrug }
    public enum IdleCategory { Micro, Normal, Long }
    public enum IdleLookPattern { None, Wander, SideGlance, Thoughtful }

    public static class AvatarMotionNames
    {
        public const string BaseLayer = "Base Layer";
        public const string GestureLayer = "Gesture Layer";
        public const string EmptyGestureState = "Empty";
        public const string DefaultIdleState = "IdleNeutral";
        public static readonly int IsSpeaking = Animator.StringToHash("IsSpeaking");
        public static readonly int MotionIntensity = Animator.StringToHash("MotionIntensity");
        public static readonly int BaseIdle = Animator.StringToHash("BaseIdle");

        public static string StatePath(string layerName, string stateName)
        {
            return stateName != null && stateName.StartsWith(layerName + ".", StringComparison.Ordinal)
                ? stateName
                : layerName + "." + stateName;
        }

        public static int StateHash(string layerName, string stateName) => Animator.StringToHash(StatePath(layerName, stateName));

        public static AvatarEmotion ParseEmotion(string value)
        {
            if (Enum.TryParse(value, true, out AvatarEmotion result)) return result;
            return AvatarEmotion.Neutral;
        }

        public static GestureTag ParseGesture(string value)
        {
            if (Enum.TryParse(value, true, out GestureTag result)) return result;
            return GestureTag.Auto;
        }

        public static string ToTransport(this GestureTag value) => value.ToString().ToLowerInvariant();
    }

    public interface IMotionRandom
    {
        float Range(float minimum, float maximum);
        int Range(int minimumInclusive, int maximumExclusive);
    }

    public sealed class UnityMotionRandom : IMotionRandom
    {
        public float Range(float minimum, float maximum) => UnityEngine.Random.Range(minimum, maximum);
        public int Range(int minimumInclusive, int maximumExclusive) => UnityEngine.Random.Range(minimumInclusive, maximumExclusive);
    }

    [Serializable]
    public sealed class AlternativeIdleDefinition
    {
        public string Id = "IdleLookAround";
        public string AnimatorState = "IdleLookAround";
        public IdleCategory Category = IdleCategory.Micro;
        // Look patterns are deliberately procedural: they preserve the base body's hips and
        // feet, making them safe to crossfade from any stationary idle on the portrait rig.
        public IdleLookPattern LookPattern = IdleLookPattern.None;
        [Min(0.05f)] public float DurationSeconds = 2f;
        [Min(0f)] public float CooldownSeconds = 20f;
        [Range(0f, 2f)] public float Speed = 1f;
    }
}
