using System.Collections;
using System.Collections.Generic;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarEmotionController : MonoBehaviour
    {
        [SerializeField] private AvatarRuntimeSettings settings;
        [SerializeField] private Vrm10Instance vrm;
        private ExpressionKey active = ExpressionKey.Neutral;
        private Coroutine blend;
        private HashSet<ExpressionKey> supported;
        private void Awake() { if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>(); }
        public void SetEmotion(string value, float intensity)
        {
            var next = ResolveKey(value, out var maximumIntensity);
            if (blend != null) StopCoroutine(blend);
            blend = StartCoroutine(Blend(next, Mathf.Min(Mathf.Clamp01(intensity), maximumIntensity)));
        }
        private IEnumerator Blend(ExpressionKey next, float intensity)
        {
            var seconds = settings != null ? settings.EmotionBlendInSeconds : .15f;
            for (var t = 0f; t < 1f; t += Time.deltaTime / Mathf.Max(.01f, seconds)) { Apply(active, 1f - t); Apply(next, intensity * t); yield return null; }
            Apply(active, 0f); Apply(next, intensity); active = next;
        }
        private void Apply(ExpressionKey key, float weight)
        {
            if (vrm == null || vrm.Runtime == null) return;
            vrm.Runtime.Expression.SetWeight(key, weight);
        }
        private ExpressionKey ResolveKey(string value, out float maximumIntensity)
        {
            var requested = (value ?? "neutral").ToLowerInvariant();
            var candidate = ToKey(requested);
            maximumIntensity = requested switch
            {
                "smirk" => .55f,
                "annoyed" => .65f,
                "sad" => .8f,
                "surprised" => .9f,
                _ => 1f,
            };
            CacheSupportedExpressions();
            if (supported == null || supported.Contains(candidate)) return candidate;
            if (supported.Contains(ExpressionKey.Neutral))
            {
                Debug.LogWarning("[Emotion] Unsupported expression '" + requested + "'; using neutral", this);
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
                // Liqu has no native Surprise preset. Its real Oh viseme gives a brief, readable
                // open-mouth reaction before speech; it is released once lip sync takes over.
                case "surprised": return ExpressionKey.Oh;
                // Liqu maps VRM0 Fun to Relaxed, which is the unwanted star-eye look.
                case "relaxed": case "fun": return ExpressionKey.Neutral;
                case "thinking": case "natural": case "neutral": return ExpressionKey.Neutral;
                default: return ExpressionKey.Neutral;
            }
        }
    }
}
