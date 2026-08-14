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
            if (settings == null || !settings.MotionEnabled) return false;
            var next = Select(settings.GestureDefinitions, tag, emotion, speaking, active == null ? -1 : active.Priority, Time.unscaledTime, lastPlayed, random);
            if (next == null) return false;
            if (active != null && (!interrupt || !active.CanInterrupt || next.Priority < active.Priority)) return false;
            var variant = next.SelectAnimatorState(random, recentVariants);
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
            var old = active; active = null; activeVariantId = null;
            if (immediate) SetWeight(0f); else StartCoroutine(FadeTo(0f, generation, old != null ? old.BlendOutSeconds : blendSeconds));
            SetHeadLookSuppression?.Invoke(0f);
            if (old != null) Finished?.Invoke(old);
        }
        private IEnumerator Run(GestureDefinition definition, string animatorState, float intensity, int token)
        {
            var statePath = AvatarMotionNames.StatePath(AvatarMotionNames.GestureLayer, animatorState);
            if (animator == null || layer < 0 || !animator.HasState(layer, Animator.StringToHash(statePath)))
            {
                if (token == generation) { active = null; Failed?.Invoke(definition, "Animator gesture state is missing"); }
                yield break;
            }
            animator.CrossFadeInFixedTime(statePath, definition.BlendInSeconds, layer, 0f);
            lastPlayed[definition.Id] = Time.unscaledTime;
            SetHeadLookSuppression?.Invoke(definition.HeadLookSuppression);
            Started?.Invoke(definition);
            yield return FadeTo(Mathf.Clamp01(definition.Weight * intensity), token, definition.BlendInSeconds);
            yield return new WaitForSeconds(Mathf.Max(.05f, definition.DurationSeconds / definition.Speed));
            if (token != generation) yield break;
            yield return FadeTo(0f, token, definition.BlendOutSeconds);
            if (token != generation) yield break;
            animator.CrossFadeInFixedTime(AvatarMotionNames.StatePath(AvatarMotionNames.GestureLayer, AvatarMotionNames.EmptyGestureState), definition.BlendOutSeconds, layer, 0f);
            SetHeadLookSuppression?.Invoke(0f);
            active = null; activeVariantId = null; activeRoutine = null;
            Finished?.Invoke(definition);
        }
        private IEnumerator FadeTo(float target, int token, float seconds)
        {
            var start = GetWeight();
            for (var elapsed = 0f; elapsed < seconds; elapsed += Time.deltaTime)
            {
                if (token != generation) yield break;
                SetWeight(Mathf.Lerp(start, target, elapsed / seconds));
                yield return null;
            }
            if (token == generation) SetWeight(target);
        }
        private float GetWeight() => animator != null && layer >= 0 ? animator.GetLayerWeight(layer) : 0f;
        private void SetWeight(float value) { if (animator != null && layer >= 0) animator.SetLayerWeight(layer, value); }
        private void OnDisable() => Stop(true);

        public static GestureDefinition Select(IList<GestureDefinition> values, GestureTag tag, AvatarEmotion emotion, bool speaking,
            int currentPriority, float now, IDictionary<string, float> played, IMotionRandom random)
        {
            if (values == null) return null;
            var choices = new List<GestureDefinition>();
            for (var i = 0; i < values.Count; i++)
            {
                var item = values[i];
                if (item == null || string.IsNullOrWhiteSpace(item.AnimatorState) || !item.Allows(emotion, speaking)) continue;
                if (tag != GestureTag.Auto && tag != item.Tag) continue;
                if (item.Priority < currentPriority) continue;
                if (played.TryGetValue(item.Id, out var last) && now - last < item.CooldownSeconds) continue;
                choices.Add(item);
            }
            return choices.Count == 0 ? null : choices[random.Range(0, choices.Count)];
        }
    }
}
