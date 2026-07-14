using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarIdleScheduler : MonoBehaviour
    {
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
            if (loop == null) loop = StartCoroutine(ScheduleLoop());
        }
        public void StopScheduling()
        {
            generation++;
            if (loop != null) { StopCoroutine(loop); loop = null; }
        }
        private void OnDisable() => StopScheduling();
        private IEnumerator ScheduleLoop()
        {
            while (true)
            {
                var current = profile;
                if (current == null || settings == null || !settings.MotionEnabled || !settings.IdleSchedulingEnabled)
                {
                    yield return new WaitForSeconds(1f);
                    continue;
                }
                var token = generation;
                yield return new WaitForSeconds(random.Range(current.IdleIntervalMinSeconds, current.IdleIntervalMaxSeconds));
                if (token != generation || IsBlocked != null && IsBlocked()) continue;
                if (random.Range(0f, 1f) > current.AlternativeIdleProbability) continue;
                var next = Select(current.AlternativeIdles, previousId, Time.unscaledTime, lastPlayed, random, IsSpeaking != null && IsSpeaking(), current.AllowLongIdleWhileSpeaking);
                if (next == null) continue;
                previousId = next.Id;
                lastPlayed[next.Id] = Time.unscaledTime;
                OnIdleRequested?.Invoke(next);
                yield return new WaitForSeconds(next.DurationSeconds / Mathf.Max(.1f, next.Speed));
            }
        }

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
    }
}
