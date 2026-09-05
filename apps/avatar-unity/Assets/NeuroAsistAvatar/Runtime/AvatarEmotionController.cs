using System;
using System.Collections.Generic;
using UniVRM10;
using UnityEngine;
using Random = UnityEngine.Random;

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
        private string baseEmotionName = "neutral";
        private float baseEmotionIntensity = 1f;
        private float transientRemaining;
        private bool isTransientActive;
        private float lifePhase;
        private bool isSpeaking;

        public string CurrentEmotion => currentEmotionName;
        public string BaseEmotion => baseEmotionName;
        public bool IsTransientActive => isTransientActive;
        public float TransientRemaining => transientRemaining;
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
            var requested = (value ?? "neutral").Trim().ToLowerInvariant().Replace("-", "_");
            currentEmotionName = string.IsNullOrWhiteSpace(requested) ? "neutral" : requested;

            if (IsTransient(requested))
            {
                isTransientActive = true;
                transientRemaining = GetTransientDuration(requested);
            }
            else
            {
                baseEmotionName = currentEmotionName;
                baseEmotionIntensity = intensity;
                isTransientActive = false;
                transientRemaining = 0f;
            }

            var targets = ResolveTargets(value, intensity, out _);
            float holdTime = settings != null ? settings.GetHoldTime() : 0.30f;

            bool isNeutral = targets.Count == 1 && ExpressionKey.Comparer.Equals(targets[0].Key, ExpressionKey.Neutral);

            if (isNeutral)
            {
                // Active channels hold their expression briefly for natural post-speech linger
                // before viscoelastic relaxation back to rest (eyelids and transients release immediately)
                foreach (var pair in channels)
                {
                    if (!IsEyelidKey(pair.Key) && pair.Value.Current > 0.05f && holdTime > 0f)
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
                    ch.Target = targets[0].TargetWeight;
                }
            }
            else
            {
                var targetKeys = new HashSet<ExpressionKey>(ExpressionKey.Comparer);
                foreach (var target in targets)
                {
                    targetKeys.Add(target.Key);
                    var ch = GetOrCreateChannel(target.Key);
                    ch.HoldRemaining = 0f;
                    ch.Target = target.TargetWeight;
                }

                // All other active channels immediately begin gentle release to clear way for the new emotion
                foreach (var pair in channels)
                {
                    if (!targetKeys.Contains(pair.Key))
                    {
                        pair.Value.HoldRemaining = 0f;
                        pair.Value.Target = 0f;
                    }
                }
            }
        }

        public void SnapToEmotion(string value, float intensity)
        {
            var requested = (value ?? "neutral").Trim().ToLowerInvariant().Replace("-", "_");
            currentEmotionName = string.IsNullOrWhiteSpace(requested) ? "neutral" : requested;

            if (IsTransient(requested))
            {
                isTransientActive = true;
                transientRemaining = GetTransientDuration(requested);
            }
            else
            {
                baseEmotionName = currentEmotionName;
                baseEmotionIntensity = intensity;
                isTransientActive = false;
                transientRemaining = 0f;
            }

            var targets = ResolveTargets(value, intensity, out _);
            bool isNeutral = targets.Count == 1 && ExpressionKey.Comparer.Equals(targets[0].Key, ExpressionKey.Neutral);

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
                foreach (var target in targets)
                {
                    var ch = GetOrCreateChannel(target.Key);
                    ch.Current = target.TargetWeight;
                    ch.Target = target.TargetWeight;
                    ch.FilteredTarget = target.TargetWeight;
                    ch.Velocity = 0f;
                    ch.FilteredVelocity = 0f;
                    ch.HoldRemaining = 0f;
                    Apply(target.Key, target.TargetWeight);
                }
            }
            else if (HasSupportedExpression(ExpressionKey.Neutral))
            {
                Apply(ExpressionKey.Neutral, targets[0].TargetWeight);
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
            if (dt <= 0f) return;

            // 1. Transient auto-return countdown
            if (isTransientActive && transientRemaining > 0f)
            {
                transientRemaining -= dt;
                if (transientRemaining <= 0f)
                {
                    isTransientActive = false;
                    transientRemaining = 0f;
                    SetEmotion(baseEmotionName, baseEmotionIntensity);
                }
            }

            if (channels.Count == 0) return;

            float defaultAttackTime = settings != null ? settings.GetAttackTime() : 0.80f;
            float defaultReleaseTime = settings != null ? settings.GetReleaseTime() : 1.40f;
            float defaultMaxSpeed = settings != null ? settings.EmotionMaxVelocity : 1.8f;
            bool microDynamics = settings == null || settings.EmotionMicroDynamics;

            lifePhase += dt * 1.57f;
            channelsToPrune.Clear();

            foreach (var pair in channels)
            {
                var ch = pair.Value;

                // 2. Post-speech emotion hold countdown (avoids abrupt emotion drop on phrase end)
                if (ch.HoldRemaining > 0f)
                {
                    ch.HoldRemaining -= dt;
                    if (ch.HoldRemaining <= 0f)
                    {
                        ch.HoldRemaining = 0f;
                        ch.Target = 0f;
                    }
                }

                // 3. Channel-specific biomechanical timing:
                // Eyelid movements are fast/ballistic, while postural expressions are gentle.
                bool isEyelid = IsEyelidKey(ch.Key);
                bool isAttacking = ch.Target > ch.FilteredTarget;

                float attackTime = isEyelid ? 0.10f : (isTransientActive ? Mathf.Min(defaultAttackTime, 0.16f) : defaultAttackTime);
                float releaseTime = isEyelid ? 0.18f : (isTransientActive ? Mathf.Min(defaultReleaseTime, 0.25f) : defaultReleaseTime);
                float maxSpeed = isEyelid ? 14.0f : (isTransientActive ? 6.0f : defaultMaxSpeed);

                float smoothTime = isAttacking ? attackTime : releaseTime;
                smoothTime = Mathf.Max(0.01f, smoothTime);

                // 4. Two-Stage Cascaded Minimum Jerk Filter:
                float stageTime = smoothTime * 0.52f;
                ch.FilteredTarget = Mathf.SmoothDamp(ch.FilteredTarget, ch.Target, ref ch.FilteredVelocity, stageTime, maxSpeed, dt);
                ch.Current = Mathf.SmoothDamp(ch.Current, ch.FilteredTarget, ref ch.Velocity, stageTime, maxSpeed, dt);

                // 5. Gentle settle threshold without snapping
                float settleThreshold = isEyelid ? 0.002f : 0.005f;
                float velThreshold = isEyelid ? 0.005f : 0.008f;
                if (ch.HoldRemaining <= 0f && Mathf.Abs(ch.Target - ch.Current) < settleThreshold && Mathf.Abs(ch.Velocity) < velThreshold)
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

                // 6. Multi-harmonic living micro-dynamics (subtle organic breathing on sustained expressions)
                float appliedWeight = ch.Current;
                if (microDynamics && ch.Current > 0.05f && !ExpressionKey.Comparer.Equals(ch.Key, ExpressionKey.Neutral) && !isEyelid)
                {
                    float seed = (float)(ch.Key.GetHashCode() & 0x7FFF) * 0.1f;
                    float wave1 = Mathf.Sin(lifePhase + seed) * 0.012f;
                    float wave2 = Mathf.Sin(lifePhase * 1.618f + seed * 2.3f) * 0.006f;
                    appliedWeight = Mathf.Clamp01(ch.Current * (1f + wave1 + wave2));
                }

                // 7. Speech co-articulation modulation:
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

        private struct TargetBinding
        {
            public ExpressionKey Key;
            public float TargetWeight;
        }

        private List<TargetBinding> ResolveTargets(string value, float intensity, out float primaryMax)
        {
            var requested = (value ?? "neutral").Trim().ToLowerInvariant().Replace("-", "_");
            var primary = ResolveKey(requested, out primaryMax);
            var clamped = Mathf.Min(Mathf.Clamp01(intensity), primaryMax);
            var result = new List<TargetBinding>();

            CacheSupportedExpressions();
            if (supported == null || requested == "neutral")
            {
                result.Add(new TargetBinding { Key = primary, TargetWeight = clamped });
                return result;
            }

            var usedKeys = new HashSet<ExpressionKey>(ExpressionKey.Comparer);

            void TryAddKey(ExpressionKey key, float multiplier)
            {
                if (supported != null && supported.Contains(key))
                {
                    if (usedKeys.Add(key))
                    {
                        result.Add(new TargetBinding { Key = key, TargetWeight = Mathf.Clamp01(clamped * multiplier) });
                    }
                }
            }

            void TryAddCustom(string customName, float multiplier)
            {
                var customKey = ExpressionKey.CreateCustom(customName);
                if (supported != null && supported.Contains(customKey))
                {
                    if (usedKeys.Add(customKey))
                    {
                        result.Add(new TargetBinding { Key = customKey, TargetWeight = Mathf.Clamp01(clamped * multiplier) });
                    }
                    return;
                }
                if (supported != null)
                {
                    foreach (var key in supported)
                    {
                        if (key.Preset == ExpressionPreset.custom && string.Equals(key.Name, customName, StringComparison.OrdinalIgnoreCase))
                        {
                            if (usedKeys.Add(key))
                            {
                                result.Add(new TargetBinding { Key = key, TargetWeight = Mathf.Clamp01(clamped * multiplier) });
                            }
                            return;
                        }
                    }
                }
            }

            switch (requested)
            {
                case "pouting":
                    TryAddCustom("CheekPuff", 0.85f);
                    TryAddCustom("MouthPucker", 0.80f);
                    TryAddCustom("BrowInnerUp", 0.45f);
                    TryAddCustom("EyeSquintLeft", 0.10f);
                    TryAddCustom("EyeSquintRight", 0.10f);
                    break;
                case "wink":
                    if (HasSupportedExpression(ExpressionKey.BlinkRight))
                        TryAddKey(ExpressionKey.BlinkRight, 1.0f);
                    else
                        TryAddCustom("EyeBlinkRight", 1.0f);
                    TryAddCustom("MouthSmileRight", 0.22f);
                    TryAddCustom("MouthSmileLeft", 0.15f);
                    TryAddCustom("BrowOuterUpRight", 0.18f);
                    break;
                case "wink_left":
                    if (HasSupportedExpression(ExpressionKey.BlinkLeft))
                        TryAddKey(ExpressionKey.BlinkLeft, 1.0f);
                    else
                        TryAddCustom("EyeBlinkLeft", 1.0f);
                    TryAddCustom("MouthSmileLeft", 0.22f);
                    TryAddCustom("MouthSmileRight", 0.15f);
                    TryAddCustom("BrowOuterUpLeft", 0.18f);
                    break;
                case "teasing":
                    TryAddCustom("TongueOut", 1.0f);
                    TryAddCustom("JawOpen", 0.26f);
                    if (HasSupportedExpression(ExpressionKey.BlinkRight))
                        TryAddKey(ExpressionKey.BlinkRight, 0.85f);
                    else
                        TryAddCustom("EyeBlinkRight", 0.85f);
                    TryAddCustom("MouthSmileRight", 0.25f);
                    TryAddCustom("MouthSmileLeft", 0.15f);
                    TryAddCustom("BrowOuterUpRight", 0.20f);
                    break;
                case "tongue_out":
                case "tongue":
                    TryAddCustom("TongueOut", 1.0f);
                    TryAddCustom("JawOpen", 0.26f);
                    TryAddCustom("EyeWideLeft", 0.15f);
                    TryAddCustom("EyeWideRight", 0.15f);
                    TryAddCustom("MouthSmileRight", 0.20f);
                    TryAddCustom("MouthSmileLeft", 0.15f);
                    break;
                case "playful":
                    TryAddCustom("TongueOut", 0.60f);
                    TryAddCustom("JawOpen", 0.20f);
                    if (HasSupportedExpression(ExpressionKey.BlinkRight))
                        TryAddKey(ExpressionKey.BlinkRight, 0.80f);
                    else
                        TryAddCustom("EyeBlinkRight", 0.80f);
                    TryAddCustom("MouthSmileRight", 0.25f);
                    TryAddCustom("MouthSmileLeft", 0.15f);
                    TryAddCustom("BrowOuterUpRight", 0.20f);
                    break;
                case "thinking":
                    TryAddCustom("BrowInnerUp", 0.50f);
                    TryAddCustom("BrowDownLeft", 0.30f);
                    TryAddCustom("EyeSquintLeft", 0.15f);
                    TryAddCustom("EyeSquintRight", 0.15f);
                    TryAddCustom("EyeLookUpLeft", 0.35f);
                    TryAddCustom("EyeLookUpRight", 0.35f);
                    TryAddCustom("MouthPucker", 0.18f);
                    TryAddCustom("MouthSmileRight", 0.10f);
                    break;
                case "smirk":
                    TryAddCustom("MouthSmileRight", 0.60f);
                    TryAddCustom("MouthSmileLeft", 0.10f);
                    TryAddCustom("BrowOuterUpRight", 0.45f);
                    TryAddCustom("BrowDownLeft", 0.25f);
                    TryAddCustom("EyeSquintRight", 0.15f);
                    break;
                case "skeptical":
                    TryAddCustom("BrowOuterUpRight", 0.70f);
                    TryAddCustom("BrowDownLeft", 0.45f);
                    TryAddCustom("MouthSmileRight", 0.20f);
                    TryAddCustom("EyeSquintLeft", 0.20f);
                    break;
                case "proud":
                    TryAddKey(ExpressionKey.Happy, 0.50f);
                    TryAddCustom("EyeSquintLeft", 0.60f);
                    TryAddCustom("EyeSquintRight", 0.60f);
                    TryAddCustom("BrowOuterUpLeft", 0.45f);
                    TryAddCustom("BrowOuterUpRight", 0.45f);
                    break;
                case "excited":
                    TryAddKey(ExpressionKey.Happy, 0.65f);
                    TryAddCustom("EyeWideLeft", 0.80f);
                    TryAddCustom("EyeWideRight", 0.80f);
                    TryAddCustom("BrowInnerUp", 0.50f);
                    break;
                case "shocked":
                    TryAddKey(ExpressionKey.Surprised, 0.85f);
                    TryAddCustom("surprised", 0.85f);
                    TryAddCustom("EyeWideLeft", 0.95f);
                    TryAddCustom("EyeWideRight", 0.95f);
                    TryAddCustom("JawOpen", 0.60f);
                    break;
                case "surprised":
                    TryAddKey(ExpressionKey.Surprised, 0.80f);
                    TryAddCustom("surprised", 0.80f);
                    TryAddCustom("EyeWideLeft", 0.70f);
                    TryAddCustom("EyeWideRight", 0.70f);
                    TryAddCustom("JawOpen", 0.30f);
                    break;
                case "concerned":
                    TryAddKey(ExpressionKey.Sad, 0.60f);
                    TryAddCustom("BrowInnerUp", 0.85f);
                    TryAddCustom("MouthFrownLeft", 0.35f);
                    TryAddCustom("MouthFrownRight", 0.35f);
                    break;
                case "touched":
                    TryAddKey(ExpressionKey.Happy, 0.50f);
                    TryAddCustom("BrowInnerUp", 0.70f);
                    TryAddCustom("EyeSquintLeft", 0.35f);
                    TryAddCustom("EyeSquintRight", 0.35f);
                    break;
                case "embarrassed":
                    TryAddCustom("BrowInnerUp", 0.65f);
                    TryAddCustom("EyeSquintLeft", 0.45f);
                    TryAddCustom("EyeSquintRight", 0.45f);
                    TryAddCustom("CheekPuff", 0.30f);
                    TryAddCustom("MouthSmileRight", 0.25f);
                    break;
                case "sleepy":
                    TryAddCustom("EyeSquintLeft", 0.75f);
                    TryAddCustom("EyeSquintRight", 0.75f);
                    TryAddCustom("MouthClose", 0.35f);
                    break;
                case "curious":
                    TryAddCustom("EyeWideLeft", 0.70f);
                    TryAddCustom("EyeWideRight", 0.70f);
                    TryAddCustom("BrowInnerUp", 0.60f);
                    TryAddCustom("BrowOuterUpRight", 0.50f);
                    break;
                case "confused":
                    TryAddCustom("BrowOuterUpRight", 0.85f);
                    TryAddCustom("BrowDownLeft", 0.70f);
                    TryAddCustom("MouthFrownLeft", 0.35f);
                    TryAddCustom("EyeSquintLeft", 0.30f);
                    break;
                default:
                    TryAddKey(primary, 1.0f);
                    break;
            }

            if (result.Count == 0)
            {
                result.Add(new TargetBinding { Key = primary, TargetWeight = clamped });
            }
            return result;
        }

        private ExpressionKey ResolveKey(string value, out float maximumIntensity)
        {
            var requested = (value ?? "neutral").Trim().ToLowerInvariant().Replace("-", "_");
            var candidate = ToKey(requested);
            maximumIntensity = requested switch
            {
                "happy" => .80f,
                "smirk" => .70f,
                "annoyed" => .60f,
                "sad" => .75f,
                "surprised" => .65f,
                "playful" => .75f,
                "pouting" => .75f,
                "wink" => .80f,
                "wink_left" => .80f,
                "skeptical" => .65f,
                "proud" => .75f,
                "sleepy" => .55f,
                "excited" => .85f,
                "shocked" => .85f,
                "touched" => .70f,
                "teasing" => .80f,
                "tongue_out" => .85f,
                "tongue" => .85f,
                "relaxed" => .60f,
                "embarrassed" => .65f,
                "concerned" => .70f,
                "curious" => .70f,
                "confused" => .65f,
                "thinking" => .75f,
                _ => .80f,
            };
            CacheSupportedExpressions();
            if (supported == null || supported.Contains(candidate)) return candidate;

            if (candidate.Preset == ExpressionPreset.custom && supported != null)
            {
                foreach (var key in supported)
                {
                    if (key.Preset == ExpressionPreset.custom && string.Equals(key.Name, candidate.Name, StringComparison.OrdinalIgnoreCase))
                        return key;
                }
            }

            if (requested == "surprised" || requested == "shocked")
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

        public static bool IsTransient(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return false;
            var clean = value.Trim().ToLowerInvariant().Replace("-", "_");
            return clean == "surprised" || clean == "shocked" || clean == "wink" || clean == "wink_left" ||
                   clean == "teasing" || clean == "tongue_out" || clean == "tongue";
        }

        public static float GetTransientDuration(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return 0f;
            var clean = value.Trim().ToLowerInvariant().Replace("-", "_");
            return clean switch
            {
                "wink" => 0.35f,
                "wink_left" => 0.35f,
                "surprised" => 0.75f,
                "shocked" => 0.75f,
                "teasing" => 1.80f,
                "tongue_out" => 1.80f,
                "tongue" => 1.80f,
                _ => 0f,
            };
        }

        public static bool IsEyelidKey(ExpressionKey key)
        {
            if (ExpressionKey.Comparer.Equals(key, ExpressionKey.Blink) ||
                ExpressionKey.Comparer.Equals(key, ExpressionKey.BlinkLeft) ||
                ExpressionKey.Comparer.Equals(key, ExpressionKey.BlinkRight))
                return true;

            if (key.Preset == ExpressionPreset.custom && !string.IsNullOrEmpty(key.Name))
            {
                var n = key.Name.ToLowerInvariant();
                if (n.Contains("blink") || n.Contains("close"))
                    return true;
            }
            return false;
        }

        private void CacheSupportedExpressions()
        {
            if (supported != null || vrm == null || vrm.Runtime == null) return;
            supported = new HashSet<ExpressionKey>(ExpressionKey.Comparer);
            foreach (var key in vrm.Runtime.Expression.ExpressionKeys) supported.Add(key);
        }

        public static ExpressionKey ToKey(string value)
        {
            switch ((value ?? "neutral").Trim().ToLowerInvariant().Replace("-", "_"))
            {
                case "happy": case "excited": case "proud": case "touched":
                    return ExpressionKey.Happy;
                case "sad": case "concerned":
                    return ExpressionKey.Sad;
                case "angry": case "annoyed":
                    return ExpressionKey.Angry;
                case "surprised": case "shocked":
                    return ExpressionKey.Surprised;
                case "relaxed":
                    return ExpressionKey.Relaxed;
                case "sleepy":
                    return ExpressionKey.CreateCustom("EyeSquintLeft");
                case "wink":
                    return ExpressionKey.BlinkRight;
                case "wink_left":
                    return ExpressionKey.BlinkLeft;
                case "pouting":
                    return ExpressionKey.CreateCustom("CheekPuff");
                case "teasing": case "tongue_out": case "tongue": case "playful":
                    return ExpressionKey.CreateCustom("TongueOut");
                case "smirk":
                    return ExpressionKey.CreateCustom("MouthSmileRight");
                case "thinking":
                    return ExpressionKey.CreateCustom("BrowInnerUp");
                case "skeptical":
                    return ExpressionKey.CreateCustom("BrowOuterUpRight");
                case "curious":
                    return ExpressionKey.CreateCustom("EyeWideLeft");
                case "confused":
                    return ExpressionKey.CreateCustom("BrowOuterUpRight");
                case "embarrassed":
                    return ExpressionKey.CreateCustom("BrowInnerUp");
                case "neutral":
                default:
                    return ExpressionKey.Neutral;
            }
        }
    }
}
