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
        private readonly Dictionary<ExpressionKey, float> applied = new Dictionary<ExpressionKey, float>(ExpressionKey.Comparer);
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
            // Use the longer side of the blend when replacing one expression with
            // another.  This prevents a sharp "pop" through neutral on interruptions.
            var blendIn = settings != null ? settings.EmotionBlendInSeconds : .45f;
            var blendOut = settings != null ? settings.EmotionBlendOutSeconds : .6f;
            var seconds = ExpressionKey.Comparer.Equals(next, ExpressionKey.Neutral)
                ? blendOut
                : Mathf.Max(blendIn, blendOut);
            var start = new Dictionary<ExpressionKey, float>(applied, ExpressionKey.Comparer);
            if (!start.ContainsKey(next)) start[next] = 0f;
            for (var t = 0f; t < 1f; t += Time.deltaTime / Mathf.Max(.01f, seconds))
            {
                var eased = t * t * (3f - 2f * t);
                foreach (var item in start) Apply(item.Key, ExpressionKey.Comparer.Equals(item.Key, next) ? Mathf.Lerp(item.Value, intensity, eased) : item.Value * (1f - eased));
                yield return null;
            }
            foreach (var item in start) if (!ExpressionKey.Comparer.Equals(item.Key, next)) Apply(item.Key, 0f);
            Apply(next, intensity);
            blend = null;
        }
        private void Apply(ExpressionKey key, float weight)
        {
            applied[key] = weight;
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
