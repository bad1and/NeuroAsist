using System.Collections.Generic;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarEmotionController : MonoBehaviour
    {
        [SerializeField] private AvatarRuntimeSettings settings;
        [SerializeField] private Vrm10Instance vrm;

        private sealed class ChannelState
        {
            public ExpressionKey Key;
            public float Current;
            public float Velocity;
            public float Target;
            public float FilteredTarget;
            public float FilteredVelocity;
            public float HoldRemaining;
        }

        private readonly Dictionary<ExpressionKey, ChannelState> channels = new Dictionary<ExpressionKey, ChannelState>(ExpressionKey.Comparer);
        private readonly Dictionary<ExpressionKey, float> applied = new Dictionary<ExpressionKey, float>(ExpressionKey.Comparer);
        private readonly List<ExpressionKey> channelsToPrune = new List<ExpressionKey>();
        private HashSet<ExpressionKey> supported;
        private string currentEmotionName = "neutral";
        private float lifePhase;
        private bool isSpeaking;

        public string CurrentEmotion => currentEmotionName;
        public bool IsSpeaking => isSpeaking;

        public void SetSpeaking(bool value) => isSpeaking = value;

        public void Configure(AvatarRuntimeSettings valueSettings, Vrm10Instance valueVrm)
        {
            settings = valueSettings;
            vrm = valueVrm;
        }

        private void Awake()
        {
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            lifePhase = Random.Range(0f, Mathf.PI * 2f);
        }

        private void OnDisable()
        {
            foreach (var pair in applied)
            {
                if (vrm != null && vrm.Runtime != null)
                    vrm.Runtime.Expression.SetWeight(pair.Key, 0f);
            }
            applied.Clear();
            channels.Clear();
        }

        public void SetEmotion(string value, float intensity)
        {
            currentEmotionName = string.IsNullOrWhiteSpace(value) ? "neutral" : value;
            var next = ResolveKey(value, out var maximumIntensity);
            var targetIntensity = Mathf.Min(Mathf.Clamp01(intensity), maximumIntensity);
            float holdTime = settings != null ? settings.GetHoldTime() : 0.30f;

            bool isNeutral = ExpressionKey.Comparer.Equals(next, ExpressionKey.Neutral);

            if (isNeutral)
            {
                // Active channels hold their expression briefly for natural post-speech linger
                // before viscoelastic relaxation back to rest
                foreach (var pair in channels)
                {
                    if (pair.Value.Current > 0.05f && holdTime > 0f)
                    {
                        pair.Value.HoldRemaining = Mathf.Max(pair.Value.HoldRemaining, holdTime);
                    }
                    else
                    {
                        pair.Value.HoldRemaining = 0f;
                        pair.Value.Target = 0f;
                    }
                }
                if (HasSupportedExpression(ExpressionKey.Neutral))
                {
                    var ch = GetOrCreateChannel(ExpressionKey.Neutral);
                    ch.HoldRemaining = 0f;
                    ch.Target = targetIntensity;
                }
            }
            else
            {
                // Target the requested emotion (cancels any hold on this channel)
                var nextCh = GetOrCreateChannel(next);
                nextCh.HoldRemaining = 0f;
                nextCh.Target = targetIntensity;

                // All other active channels immediately begin gentle release to clear way for the new emotion
                foreach (var pair in channels)
                {
                    if (!ExpressionKey.Comparer.Equals(pair.Key, next))
                    {
                        pair.Value.HoldRemaining = 0f;
                        pair.Value.Target = 0f;
                    }
                }
            }
        }

        public void SnapToEmotion(string value, float intensity)
        {
            currentEmotionName = string.IsNullOrWhiteSpace(value) ? "neutral" : value;
            var next = ResolveKey(value, out var maximumIntensity);
            var targetIntensity = Mathf.Min(Mathf.Clamp01(intensity), maximumIntensity);
            bool isNeutral = ExpressionKey.Comparer.Equals(next, ExpressionKey.Neutral);

            foreach (var pair in channels)
            {
                pair.Value.Current = 0f;
                pair.Value.Target = 0f;
                pair.Value.FilteredTarget = 0f;
                pair.Value.Velocity = 0f;
                pair.Value.FilteredVelocity = 0f;
                pair.Value.HoldRemaining = 0f;
                Apply(pair.Key, 0f);
            }
            channels.Clear();

            if (!isNeutral)
            {
                var ch = GetOrCreateChannel(next);
                ch.Current = targetIntensity;
                ch.Target = targetIntensity;
                ch.FilteredTarget = targetIntensity;
                ch.Velocity = 0f;
                ch.FilteredVelocity = 0f;
                ch.HoldRemaining = 0f;
                Apply(next, targetIntensity);
            }
            else if (HasSupportedExpression(ExpressionKey.Neutral))
            {
                Apply(ExpressionKey.Neutral, targetIntensity);
            }
        }

        public float GetWeight(ExpressionKey key) => applied.TryGetValue(key, out var w) ? w : 0f;
        public float GetTargetWeight(ExpressionKey key) => channels.TryGetValue(key, out var ch) ? ch.Target : 0f;
        public float GetVelocity(ExpressionKey key) => channels.TryGetValue(key, out var ch) ? ch.Velocity : 0f;
        public float GetWeight(string emotion) => GetWeight(ResolveKey(emotion, out _));
        public float GetTargetWeight(string emotion) => GetTargetWeight(ResolveKey(emotion, out _));
        public float GetVelocity(string emotion) => GetVelocity(ResolveKey(emotion, out _));
        public float GetHoldRemaining(string emotion) => channels.TryGetValue(ResolveKey(emotion, out _), out var ch) ? ch.HoldRemaining : 0f;

        private void Update()
        {
            UpdateInternal(Mathf.Min(Time.deltaTime, 0.05f));
        }

        public void ManualUpdate(float dt)
        {
            UpdateInternal(dt);
        }

        private void UpdateInternal(float dt)
        {
            if (dt <= 0f || channels.Count == 0) return;

            float attackTime = settings != null ? settings.GetAttackTime() : 0.80f;
            float releaseTime = settings != null ? settings.GetReleaseTime() : 1.40f;
            float maxSpeed = settings != null ? settings.EmotionMaxVelocity : 1.8f;
            bool microDynamics = settings == null || settings.EmotionMicroDynamics;

            lifePhase += dt * 1.57f;
            channelsToPrune.Clear();

            foreach (var pair in channels)
            {
                var ch = pair.Value;

                // 1. Post-speech emotion hold countdown (avoids abrupt emotion drop on phrase end)
                if (ch.HoldRemaining > 0f)
                {
                    ch.HoldRemaining -= dt;
                    if (ch.HoldRemaining <= 0f)
                    {
                        ch.HoldRemaining = 0f;
                        ch.Target = 0f;
                    }
                }

                // 2. Asymmetric biomechanical timing:
                // Active contraction (target > filteredTarget) vs. viscoelastic tissue relaxation (target <= filteredTarget)
                float smoothTime = ch.Target > ch.FilteredTarget ? attackTime : releaseTime;
                smoothTime = Mathf.Max(0.01f, smoothTime);

                // 3. Two-Stage Cascaded Minimum Jerk Filter:
                // Stage 1: Intent acceleration filter (eliminates instant jump in acceleration / jerk at t=0)
                float stageTime = smoothTime * 0.52f;
                ch.FilteredTarget = Mathf.SmoothDamp(ch.FilteredTarget, ch.Target, ref ch.FilteredVelocity, stageTime, maxSpeed, dt);

                // Stage 2: Biomechanical muscle & skin viscoelastic compliance
                ch.Current = Mathf.SmoothDamp(ch.Current, ch.FilteredTarget, ref ch.Velocity, stageTime, maxSpeed, dt);

                // 4. Gentle settle threshold without snapping
                if (ch.HoldRemaining <= 0f && Mathf.Abs(ch.Target - ch.Current) < 0.005f && Mathf.Abs(ch.Velocity) < 0.008f)
                {
                    ch.Current = ch.Target;
                    ch.FilteredTarget = ch.Target;
                    ch.Velocity = 0f;
                    ch.FilteredVelocity = 0f;
                    if (ch.Target == 0f)
                    {
                        channelsToPrune.Add(pair.Key);
                    }
                }

                // 5. Multi-harmonic living micro-dynamics (subtle organic breathing on sustained expressions)
                float appliedWeight = ch.Current;
                if (microDynamics && ch.Current > 0.05f && !ExpressionKey.Comparer.Equals(ch.Key, ExpressionKey.Neutral))
                {
                    float seed = (float)(ch.Key.GetHashCode() & 0x7FFF) * 0.1f;
                    float wave1 = Mathf.Sin(lifePhase + seed) * 0.012f;
                    float wave2 = Mathf.Sin(lifePhase * 1.618f + seed * 2.3f) * 0.006f;
                    appliedWeight = Mathf.Clamp01(ch.Current * (1f + wave1 + wave2));
                }

                // 6. Speech co-articulation modulation:
                // When actively speaking, soften mouth-affecting morphs so visemes/lip-sync
                // have full articulation freedom without fighting rigid expression morphs.
                if (isSpeaking && IsMouthAffecting(ch.Key))
                {
                    appliedWeight = Mathf.Min(appliedWeight * 0.65f, 0.40f);
                }

                Apply(ch.Key, appliedWeight);
            }

            for (int i = 0; i < channelsToPrune.Count; i++)
            {
                var key = channelsToPrune[i];
                Apply(key, 0f);
                channels.Remove(key);
            }
        }

        private ChannelState GetOrCreateChannel(ExpressionKey key)
        {
            if (!channels.TryGetValue(key, out var ch))
            {
                float currentWeight = applied.TryGetValue(key, out var w) ? w : 0f;
                ch = new ChannelState
                {
                    Key = key,
                    Current = currentWeight,
                    Target = 0f,
                    FilteredTarget = currentWeight,
                    Velocity = 0f,
                    FilteredVelocity = 0f,
                    HoldRemaining = 0f
                };
                channels[key] = ch;
            }
            return ch;
        }

        private void Apply(ExpressionKey key, float weight)
        {
            applied[key] = weight;
            if (vrm == null || vrm.Runtime == null) return;
            vrm.Runtime.Expression.SetWeight(key, weight);
        }

        private bool HasSupportedExpression(ExpressionKey key)
        {
            CacheSupportedExpressions();
            return supported != null && supported.Contains(key);
        }

        private static bool IsMouthAffecting(ExpressionKey key)
        {
            return ExpressionKey.Comparer.Equals(key, ExpressionKey.Happy) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Angry) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Sad) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Oh) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Aa) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Ih) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Ou) ||
                   ExpressionKey.Comparer.Equals(key, ExpressionKey.Ee);
        }

        private ExpressionKey ResolveKey(string value, out float maximumIntensity)
        {
            var requested = (value ?? "neutral").ToLowerInvariant();
            var candidate = ToKey(requested);
            maximumIntensity = requested switch
            {
                "happy" => .80f,
                "smirk" => .55f,
                "annoyed" => .60f,
                "sad" => .75f,
                "surprised" => .65f,
                _ => .80f,
            };
            CacheSupportedExpressions();
            if (supported == null || supported.Contains(candidate)) return candidate;

            if (requested == "surprised")
            {
                var customSurprise = ExpressionKey.CreateCustom("Surprised");
                if (supported.Contains(customSurprise)) return customSurprise;
                var customSurpriseLower = ExpressionKey.CreateCustom("surprised");
                if (supported.Contains(customSurpriseLower)) return customSurpriseLower;
            }

            if (supported.Contains(ExpressionKey.Neutral))
            {
                return ExpressionKey.Neutral;
            }
            return candidate;
        }

        public static bool IsTransient(string value) => string.Equals(value, "surprised", System.StringComparison.OrdinalIgnoreCase);

        private void CacheSupportedExpressions()
        {
            if (supported != null || vrm == null || vrm.Runtime == null) return;
            supported = new HashSet<ExpressionKey>(ExpressionKey.Comparer);
            foreach (var key in vrm.Runtime.Expression.ExpressionKeys) supported.Add(key);
        }

        public static ExpressionKey ToKey(string value)
        {
            switch ((value ?? "neutral").ToLowerInvariant())
            {
                case "happy": case "smirk": return ExpressionKey.Happy;
                case "sad": return ExpressionKey.Sad;
                case "angry": case "annoyed": return ExpressionKey.Angry;
                case "surprised": return ExpressionKey.Surprised;
                case "relaxed": case "fun": return ExpressionKey.Neutral;
                case "thinking": case "natural": case "neutral": return ExpressionKey.Neutral;
                default: return ExpressionKey.Neutral;
            }
        }
    }
}
