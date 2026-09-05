using System;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public enum AvatarEmotion
    {
        Neutral = 0,
        Happy = 1,
        Sad = 2,
        Angry = 3,
        Surprised = 4,
        Relaxed = 5,
        Thinking = 6,
        Annoyed = 7,
        Smirk = 8,
        Embarrassed = 9,
        Concerned = 10,
        Playful = 11,
        Pouting = 12,
        Wink = 13,
        Wink_Left = 14,
        Skeptical = 15,
        Proud = 16,
        Sleepy = 17,
        Excited = 18,
        Shocked = 19,
        Touched = 20,
        Teasing = 21,
        Curious = 22,
        Confused = 23,
    }

    public enum GestureTag
    {
        None = 0,
        Auto = 1,
        Talk = 2,
        Greeting = 3,
        Agreement = 4,
        Disagreement = 5,
        Question = 6,
        Explanation = 7,
        Thinking = 8,
        Surprise = 9,
        Frustration = 10,
        Farewell = 11,
        Shrug = 12,
        Talk_Right = 13,
        Talk_Left = 14,
        Greeting_Right = 15,
        Greeting_Left = 16,
        Greeting_Casual = 17,
        Question_Right = 18,
        Question_Left = 19,
        Explanation_Right = 20,
        Explanation_Left = 21,
        Thinking_Right = 22,
        Thinking_Left = 23,
        Farewell_Right = 24,
        Farewell_Left = 25,
        Farewell_Casual = 26,
        Nod = 27,
    }

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
            if (string.IsNullOrWhiteSpace(value)) return AvatarEmotion.Neutral;
            var clean = value.Trim().Replace("-", "_");
            if (Enum.TryParse(clean, true, out AvatarEmotion result)) return result;
            return AvatarEmotion.Neutral;
        }

        public static GestureTag ParseGesture(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return GestureTag.Auto;
            var clean = value.Trim().Replace("-", "_");
            if (Enum.TryParse(clean, true, out GestureTag result)) return result;
            return GestureTag.Auto;
        }

        public static string ToTransport(this GestureTag value) => value.ToString().ToLowerInvariant();

        public static GestureTag BaseGesture(GestureTag tag)
        {
            switch (tag)
            {
                case GestureTag.Greeting_Right:
                case GestureTag.Greeting_Left:
                case GestureTag.Greeting_Casual:
                    return GestureTag.Greeting;
                case GestureTag.Farewell_Right:
                case GestureTag.Farewell_Left:
                case GestureTag.Farewell_Casual:
                    return GestureTag.Farewell;
                case GestureTag.Thinking_Right:
                case GestureTag.Thinking_Left:
                    return GestureTag.Thinking;
                case GestureTag.Question_Right:
                case GestureTag.Question_Left:
                    return GestureTag.Question;
                case GestureTag.Explanation_Right:
                case GestureTag.Explanation_Left:
                    return GestureTag.Explanation;
                case GestureTag.Talk_Right:
                case GestureTag.Talk_Left:
                    return GestureTag.Talk;
                default:
                    return tag;
            }
        }

        public static bool IsExplicitLeftHand(GestureTag tag)
        {
            return tag == GestureTag.Greeting_Left ||
                   tag == GestureTag.Farewell_Left ||
                   tag == GestureTag.Thinking_Left ||
                   tag == GestureTag.Question_Left ||
                   tag == GestureTag.Explanation_Left ||
                   tag == GestureTag.Talk_Left;
        }

        public static bool IsExplicitRightHand(GestureTag tag)
        {
            return tag == GestureTag.Greeting_Right ||
                   tag == GestureTag.Farewell_Right ||
                   tag == GestureTag.Thinking_Right ||
                   tag == GestureTag.Question_Right ||
                   tag == GestureTag.Explanation_Right ||
                   tag == GestureTag.Talk_Right;
        }
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
