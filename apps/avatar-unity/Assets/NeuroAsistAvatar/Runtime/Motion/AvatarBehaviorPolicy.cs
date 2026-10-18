using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    [Flags] public enum MotionChannels { None = 0, LeftArm = 1, RightArm = 2, Head = 4, Torso = 8, BothArms = LeftArm | RightArm }
    public enum GestureSide { Either, Right, Left, Both }
    public enum GesturePhase { Rest, Preparation, Stroke, Hold, Recovery }
    [Flags] public enum MotionPresence { Idle = 1, Listening = 2, Thinking = 4, Speaking = 8, All = 15 }

    [Serializable]
    public sealed class GestureVariant
    {
        public string Id;
        // Shared by mirrored versions: mirroring never counts as a new performance.
        public string PatternId;
        public string AnimatorState;
        public string LayerName = AvatarMotionNames.GestureLayer;
        public AnimationClip Clip;
        public GestureSide Side;
        public MotionChannels Channels = MotionChannels.BothArms;
        public MotionPresence AllowedPresence = MotionPresence.All;
        public Vector2 SpeedRange = new Vector2(.92f, 1.08f);
        public Vector2 IntensityRange = new Vector2(.65f, .95f);
        [Min(.01f)] public float PreparationSeconds = .25f;
        [Min(.01f)] public float StrokeSeconds = .7f;
        [Min(0f)] public float HoldSeconds = .15f;
        [Min(.05f)] public float RecoverySeconds = .5f;
        public bool ContactSensitive;
        public bool LargeMotion;
        // A small, authored supporting torso motion, not the source clip's hips.
        public Vector3 TorsoAccent;
        public float Duration => Clip != null ? Clip.length : PreparationSeconds + StrokeSeconds + HoldSeconds + RecoverySeconds;
        public bool Allows(AvatarState state) => (AllowedPresence & PresenceOf(state)) != 0;
        public static MotionPresence PresenceOf(AvatarState state)
        {
            switch (state)
            {
                case AvatarState.Listening: return MotionPresence.Listening;
                case AvatarState.Thinking: case AvatarState.Downloading: return MotionPresence.Thinking;
                case AvatarState.Speaking: return MotionPresence.Speaking;
                default: return MotionPresence.Idle;
            }
        }
        public GesturePhase PhaseAt(float clipSeconds)
        {
            if (clipSeconds < PreparationSeconds) return GesturePhase.Preparation;
            if (clipSeconds < PreparationSeconds + StrokeSeconds) return GesturePhase.Stroke;
            if (clipSeconds < PreparationSeconds + StrokeSeconds + HoldSeconds) return GesturePhase.Hold;
            return GesturePhase.Recovery;
        }
    }

    /// <summary>Session-local variety and rhythm; never changes Iris's persistent mood or memory.</summary>
    public sealed class AvatarBehaviorPolicy
    {
        private readonly Dictionary<GestureTag, Queue<string>> recent = new Dictionary<GestureTag, Queue<string>>();
        private readonly Dictionary<GestureTag, float> lastFinished = new Dictionary<GestureTag, float>();
        private readonly HashSet<string> cueKeys = new HashSet<string>();
        private readonly Queue<string> cueOrder = new Queue<string>();
        private float nextAutomatic;
        private float lastActivity;
        public float NextAutomatic => nextAutomatic;

        public void Touch(float now) => lastActivity = now;
        public float QuietActivity(float now) => QuietActivityAfter(now - lastActivity);
        public static float QuietActivityAfter(float seconds) => Mathf.Lerp(1f, .5f, Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(45f, 180f, seconds)));
        public static GestureTag Family(GestureTag tag) => tag == GestureTag.Nod ? GestureTag.Agreement : AvatarMotionNames.BaseGesture(tag);
        public static bool IsSpeech(GestureTag tag) => Family(tag) == GestureTag.Talk;
        public static bool IsSemantic(GestureTag tag) => tag != GestureTag.None && tag != GestureTag.Auto && !IsSpeech(tag);

        public bool AcceptCue(string key)
        {
            if (string.IsNullOrEmpty(key)) return true;
            if (!cueKeys.Add(key)) return false;
            cueOrder.Enqueue(key);
            while (cueOrder.Count > 128) cueKeys.Remove(cueOrder.Dequeue());
            return true;
        }

        public bool FamilyReady(GestureTag tag, float now, float cooldown)
        {
            return !lastFinished.TryGetValue(Family(tag), out var finished) || now - finished >= cooldown;
        }
        public void Finished(GestureTag tag, float now) => lastFinished[Family(tag)] = now;
        public void DeferAutomatic(float now, IMotionRandom random, float frequency = 1f, float minimum = 4f, float maximum = 8f)
        {
            minimum = Mathf.Max(4f, minimum);
            nextAutomatic = now + random.Range(minimum, Mathf.Max(minimum, maximum)) / Mathf.Clamp(frequency, .7f, 1.25f);
        }
        public bool CanAccent(float now, float remaining, GestureTag requested, bool busy)
            => !busy && requested != GestureTag.None && remaining >= 1.7f && now >= nextAutomatic;

        public GestureVariant Select(IList<GestureVariant> variants, GestureTag tag, AvatarState presence,
            float expressiveness, IMotionRandom random, bool automatic = false)
        {
            var family = Family(tag);
            if (!recent.TryGetValue(family, out var history)) history = new Queue<string>();
            var eligible = new List<GestureVariant>();
            foreach (var item in variants)
            {
                if (item == null || string.IsNullOrEmpty(item.AnimatorState) || !item.Allows(presence)) continue;
                if (AvatarMotionNames.IsExplicitLeftHand(tag) && item.Side != GestureSide.Left) continue;
                if (AvatarMotionNames.IsExplicitRightHand(tag) && item.Side != GestureSide.Right) continue;
                if (automatic && (item.LargeMotion || item.ContactSensitive)) continue;
                eligible.Add(item);
            }
            if (eligible.Count == 0) return null;
            var fresh = eligible.FindAll(v => !history.Contains(v.PatternId ?? v.Id));
            if (fresh.Count > 0) eligible = fresh;
            // Expressiveness influences suitability, while a mild hand preference
            // remains stable instead of mechanically alternating sides.
            var weights = new float[eligible.Count];
            var total = 0f;
            for (var i = 0; i < eligible.Count; i++)
            {
                var item = eligible[i];
                var midpoint = (item.IntensityRange.x + item.IntensityRange.y) * .5f;
                var suitability = Mathf.Max(.15f, 1f - Mathf.Abs(midpoint - expressiveness));
                weights[i] = suitability * (item.Side == GestureSide.Right ? 1.3f : 1f);
                total += weights[i];
            }
            var ticket = random.Range(0f, total);
            var picked = eligible[eligible.Count - 1];
            for (var i = 0; i < weights.Length; i++) { ticket -= weights[i]; if (ticket <= 0f) { picked = eligible[i]; break; } }
            return picked;
        }
        public void Remember(GestureTag tag, GestureVariant variant)
        {
            var family = Family(tag);
            if (!recent.TryGetValue(family, out var history)) recent[family] = history = new Queue<string>();
            history.Enqueue(variant.PatternId ?? variant.Id);
            while (history.Count > 4) history.Dequeue();
        }
    }
}
