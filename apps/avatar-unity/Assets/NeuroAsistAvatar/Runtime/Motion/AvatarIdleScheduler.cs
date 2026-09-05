using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarIdleScheduler : MonoBehaviour
    {
        private static readonly AlternativeIdleDefinition[] SafePortraitIdles =
        {
            new AlternativeIdleDefinition { Id = "IdleLookWander", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Wander, Category = IdleCategory.Micro, DurationSeconds = 4.5f, CooldownSeconds = 18f },
            new AlternativeIdleDefinition { Id = "IdleSideGlance", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.SideGlance, Category = IdleCategory.Micro, DurationSeconds = 3.5f, CooldownSeconds = 16f },
            new AlternativeIdleDefinition { Id = "IdleThoughtfulLook", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Thoughtful, Category = IdleCategory.Micro, DurationSeconds = 4f, CooldownSeconds = 24f },
        };
        [SerializeField] private AvatarMotionSettings settings;
        private readonly Dictionary<string, float> lastPlayed = new Dictionary<string, float>();
        private IMotionRandom random = new UnityMotionRandom();
        private MotionProfile profile;
        private Coroutine loop;
        private int generation;
        private string previousId;
        public Func<bool> IsBlocked;
        public Func<bool> IsSpeaking;
        public Action<AlternativeIdleDefinition> OnIdleRequested;

        public void Configure(AvatarMotionSettings value) => settings = value;
        public void SetRandom(IMotionRandom value) => random = value ?? new UnityMotionRandom();
        public void SetProfile(MotionProfile value) { profile = value; generation++; }

        public void StartScheduling()
        {
            // Pure neural mode: spontaneous scripted alternative idles are completely disabled.
            StopScheduling();
        }

        public void StopScheduling()
        {
            generation++;
            if (loop != null) { StopCoroutine(loop); loop = null; }
        }

        private void OnDisable() => StopScheduling();

        public static AlternativeIdleDefinition Select(IList<AlternativeIdleDefinition> values, string previous, float now,
            IDictionary<string, float> played, IMotionRandom random, bool speaking, bool allowLongWhileSpeaking)
        {
            if (values == null || values.Count == 0) return null;
            var eligible = new List<AlternativeIdleDefinition>();
            for (var i = 0; i < values.Count; i++)
            {
                var item = values[i];
                if (item == null || string.IsNullOrWhiteSpace(item.AnimatorState)) continue;
                if (speaking && (item.Category == IdleCategory.Long && !allowLongWhileSpeaking)) continue;
                if (item.Id == previous && values.Count > 1) continue;
                if (played.TryGetValue(item.Id, out var last) && now - last < item.CooldownSeconds) continue;
                eligible.Add(item);
            }
            return eligible.Count == 0 ? null : eligible[random.Range(0, eligible.Count)];
        }
        private static IList<AlternativeIdleDefinition> ResolveIdles(MotionProfile current)
        {
            var valid = 0;
            if (current != null && current.AlternativeIdles != null)
                foreach (var item in current.AlternativeIdles)
                    if (item != null && !string.IsNullOrWhiteSpace(item.AnimatorState)) valid++;
            // Existing checked-in profiles have one real idle and two empty slots. Keep
            // old scenes safe immediately; the editor setup persists this same layout.
            return valid >= 3 ? current.AlternativeIdles : SafePortraitIdles;
        }
    }
}
