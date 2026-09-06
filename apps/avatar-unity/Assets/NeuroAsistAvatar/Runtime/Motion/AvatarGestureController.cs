using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarGestureController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private AvatarMotionSettings settings;
        [Range(0.01f, 1f)] [SerializeField] private float blendSeconds = .35f;
        private readonly Dictionary<string, float> lastPlayed = new Dictionary<string, float>();
        private Coroutine activeRoutine;
        private Coroutine fadeRoutine;
        private GestureDefinition active;
        private int generation;
        private int layer = -1;
        private string activeVariantId;
        private IMotionRandom random = new UnityMotionRandom();
        public event Action<GestureDefinition> Started;
        public event Action<GestureDefinition> Finished;
        public event Action<GestureDefinition, string> Failed;
        public Action<float> SetHeadLookSuppression;
        public bool IsPlaying => active != null;
        public GestureDefinition Active => active;
        public string ActiveVariantId => activeVariantId;

        public void Configure(AvatarMotionSettings value, Animator valueAnimator) { settings = value; animator = valueAnimator; CacheLayer(); }
        public void SetRandom(IMotionRandom value) => random = value ?? new UnityMotionRandom();
        private void Awake() => CacheLayer();
        private void CacheLayer() { layer = animator == null ? -1 : animator.GetLayerIndex(AvatarMotionNames.GestureLayer); }
        public bool Trigger(GestureTag tag, AvatarEmotion emotion, bool speaking, float intensity, bool interrupt, ICollection<string> recentVariants = null)
        {
            if (settings == null || !settings.MotionEnabled || tag == GestureTag.None) return false;
            var isExplicit = tag != GestureTag.Auto && tag != GestureTag.None;
            var ignoreCooldown = interrupt || isExplicit;
            var currentPriority = (active == null || (isExplicit && interrupt)) ? -1 : active.Priority;
            var next = Select(settings.GestureDefinitions, tag, emotion, speaking, currentPriority, Time.unscaledTime, lastPlayed, random, ignoreCooldown);
            if (next == null) return false;
            if (active != null && !interrupt) return false;
            if (active != null && !isExplicit && (!active.CanInterrupt || next.Priority < active.Priority)) return false;
            bool? preferMirror = null;
            if (AvatarMotionNames.IsExplicitLeftHand(tag)) preferMirror = true;
            else if (AvatarMotionNames.IsExplicitRightHand(tag)) preferMirror = false;
            var variant = next.SelectAnimatorState(random, recentVariants, preferMirror);
            if (string.IsNullOrWhiteSpace(variant)) return false;
            Stop(false);
            active = next;
            activeVariantId = variant;
            var token = ++generation;
            activeRoutine = StartCoroutine(Run(next, variant, Mathf.Clamp01(intensity), token));
            return true;
        }
        public void Stop(bool immediate)
        {
            generation++;
            if (activeRoutine != null) { StopCoroutine(activeRoutine); activeRoutine = null; }
            if (fadeRoutine != null) { StopCoroutine(fadeRoutine); fadeRoutine = null; }
            var old = active; active = null; activeVariantId = null;
            if (immediate) SetWeight(0f); else fadeRoutine = StartCoroutine(FadeTo(0f, generation, old != null ? old.BlendOutSeconds : blendSeconds));
            SetHeadLookSuppression?.Invoke(0f);
            if (old != null) Finished?.Invoke(old);
        }
        private IEnumerator Run(GestureDefinition definition, string animatorState, float intensity, int token)
        {
            var statePath = AvatarMotionNames.StatePath(AvatarMotionNames.GestureLayer, animatorState);
            var hasPath = animator != null && layer >= 0 && animator.HasState(layer, Animator.StringToHash(statePath));
            var hasShort = animator != null && layer >= 0 && animator.HasState(layer, Animator.StringToHash(animatorState));
            if (animator == null || layer < 0 || (!hasPath && !hasShort))
            {
                if (token == generation) { active = null; Failed?.Invoke(definition, "Animator gesture state is missing"); }
                yield break;
            }
            animator.CrossFadeInFixedTime(hasPath ? statePath : animatorState, definition.BlendInSeconds, layer, 0f);
            lastPlayed[definition.Id] = Time.unscaledTime;
            SetHeadLookSuppression?.Invoke(definition.HeadLookSuppression);
            Started?.Invoke(definition);
            if (fadeRoutine != null) { StopCoroutine(fadeRoutine); fadeRoutine = null; }
            fadeRoutine = StartCoroutine(FadeTo(Mathf.Clamp01(definition.Weight * intensity), token, definition.BlendInSeconds));
            yield return fadeRoutine;
            yield return new WaitForSeconds(Mathf.Max(.05f, definition.DurationSeconds / definition.Speed));
            if (token != generation) yield break;
            fadeRoutine = StartCoroutine(FadeTo(0f, token, definition.BlendOutSeconds));
            yield return fadeRoutine;
            if (token != generation) yield break;
            animator.CrossFadeInFixedTime(AvatarMotionNames.StatePath(AvatarMotionNames.GestureLayer, AvatarMotionNames.EmptyGestureState), definition.BlendOutSeconds, layer, 0f);
            SetHeadLookSuppression?.Invoke(0f);
            active = null; activeVariantId = null; activeRoutine = null; fadeRoutine = null;
            Finished?.Invoke(definition);
        }
        private IEnumerator FadeTo(float target, int token, float seconds)
        {
            var start = GetWeight();
            var duration = Mathf.Max(.01f, seconds);
            for (var elapsed = 0f; elapsed < duration; elapsed += Time.deltaTime)
            {
                if (token != generation) yield break;
                var t = Mathf.Clamp01(elapsed / duration);
                // Quintic smootherstep with zero initial and terminal jerk for physical inertia
                var eased = t * t * t * (t * (6f * t - 15f) + 10f);
                SetWeight(Mathf.Lerp(start, target, eased));
                yield return null;
            }
            if (token == generation) SetWeight(target);
        }
        private float GetWeight() => animator != null && layer >= 0 ? animator.GetLayerWeight(layer) : 0f;
        private void SetWeight(float value) { if (animator != null && layer >= 0) animator.SetLayerWeight(layer, value); }
        private void OnDisable() => Stop(true);

        public static GestureDefinition Select(IList<GestureDefinition> values, GestureTag tag, AvatarEmotion emotion, bool speaking,
            int currentPriority, float now, IDictionary<string, float> played, IMotionRandom random, bool ignoreCooldown = false)
        {
            if (values == null || tag == GestureTag.None) return null;
            var effectiveTag = tag == GestureTag.Auto ? AvatarMotionNames.ResolveAutoGesture(emotion) : tag;
            if (effectiveTag == GestureTag.None) return null;
            var baseTag = AvatarMotionNames.BaseGesture(effectiveTag);
            var choices = new List<GestureDefinition>();
            for (var i = 0; i < values.Count; i++)
            {
                var item = values[i];
                if (item == null || string.IsNullOrWhiteSpace(item.AnimatorState) || !item.Allows(emotion, speaking)) continue;
                if (effectiveTag != item.Tag && baseTag != item.Tag) continue;
                if (item.Priority < currentPriority) continue;
                if (!ignoreCooldown && played.TryGetValue(item.Id, out var last) && now - last < item.CooldownSeconds) continue;
                choices.Add(item);
            }
            if (choices.Count == 0) return null;
            var exact = choices.FindAll(c => c.Tag == effectiveTag);
            if (exact.Count > 0) return exact[random.Range(0, exact.Count)];
            return choices[random.Range(0, choices.Count)];
        }
    }
}
