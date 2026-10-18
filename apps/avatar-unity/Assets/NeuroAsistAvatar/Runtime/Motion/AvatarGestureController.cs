using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>One physical gesture at a time, with a clip-derived lifecycle and safe recovery.</summary>
    public sealed class AvatarGestureController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private AvatarMotionSettings settings;
        private readonly Dictionary<string, float> lastPlayed = new Dictionary<string, float>();
        private IMotionRandom random = new UnityMotionRandom();
        private AvatarBehaviorPolicy policy = new AvatarBehaviorPolicy();
        private GestureDefinition active;
        private GestureVariant variant;
        private int layer = -1;
        private float started, speed = 1f, targetWeight, releaseStarted = -1, releaseDuration, releaseWeight;
        private bool hasSpeedParameter;
        public event Action<GestureDefinition> Started;
        public event Action<GestureDefinition> Finished;
        public event Action<GestureDefinition, string> Failed;
        public Action<float> SetHeadLookSuppression;
        public bool IsPlaying => active != null;
        public bool WasInterrupted { get; private set; }
        public GestureDefinition Active => active;
        public GestureVariant ActiveVariant => variant;
        public string ActiveVariantId => variant?.Id;
        public float PlaybackSpeed => speed;
        public float Elapsed => Mathf.Max(0, Time.time - started) * speed;
        public GesturePhase Phase => active == null ? GesturePhase.Rest : releaseStarted >= 0 ? GesturePhase.Recovery : variant.PhaseAt(Elapsed);
        public MotionChannels OccupiedChannels => variant != null ? variant.Channels : MotionChannels.None;
        public float GestureWeight => GetWeight();

        public void Configure(AvatarMotionSettings value, Animator valueAnimator) { settings = value; animator = valueAnimator; CacheLayer(); }
        public void SetPolicy(AvatarBehaviorPolicy value) => policy = value ?? new AvatarBehaviorPolicy();
        public void SetRandom(IMotionRandom value) => random = value ?? new UnityMotionRandom();
        private void Awake() => CacheLayer();
        private void CacheLayer()
        {
            layer = animator == null ? -1 : animator.GetLayerIndex(AvatarMotionNames.GestureLayer);
            hasSpeedParameter = false;
            if (animator != null) foreach (var p in animator.parameters) if (p.name == "GesturePlaybackSpeed") hasSpeedParameter = true;
        }
        public bool Trigger(GestureTag tag, AvatarEmotion emotion, bool speaking, float intensity, bool interrupt, ICollection<string> recentVariants = null, bool ignoreCooldown = false)
        {
            // Interrupt permission is arbitrated by the director. A new clip must
            // never erase a stroke or change the previous clip's playback speed.
            if (IsPlaying || settings == null || !settings.MotionEnabled || tag == GestureTag.None || intensity <= 0) return false;
            var next = Select(settings.GestureDefinitions, tag, emotion, speaking, -1, Time.unscaledTime, lastPlayed, random, ignoreCooldown);
            if (next == null) return false;
            var presence = speaking ? AvatarState.Speaking : GetComponent<AvatarStateController>()?.Current ?? AvatarState.Idle;
            var selected = next.Variants.Count > 0 ? policy.Select(next.Variants, tag, presence, intensity, random, tag == GestureTag.Auto) : null;
            if (next.Variants.Count > 0 && selected == null) return false;
            if (selected == null)
            {
                bool? mirror = AvatarMotionNames.IsExplicitLeftHand(tag) ? true : AvatarMotionNames.IsExplicitRightHand(tag) ? false : (bool?)null;
                var state = next.SelectAnimatorState(random, recentVariants, mirror);
                selected = new GestureVariant { Id = state, PatternId = state, AnimatorState = state,
                    PreparationSeconds = next.BlendInSeconds, StrokeSeconds = Mathf.Max(.1f, next.DurationSeconds - next.BlendInSeconds),
                    HoldSeconds = 0, RecoverySeconds = next.BlendOutSeconds, SpeedRange = Vector2.one * next.Speed };
            }
            layer = animator != null ? animator.GetLayerIndex(selected.LayerName) : -1;
            var path = AvatarMotionNames.StatePath(selected.LayerName, selected.AnimatorState);
            if (animator == null || layer < 0 || !animator.HasState(layer, Animator.StringToHash(path)))
            { Failed?.Invoke(next, "Animator gesture state is missing: " + selected.AnimatorState); return false; }
            active = next; variant = selected; started = Time.time; releaseStarted = -1; WasInterrupted = false;
            speed = Mathf.Clamp(random.Range(selected.SpeedRange.x, selected.SpeedRange.y), .5f, 1.5f);
            if (hasSpeedParameter) animator.SetFloat("GesturePlaybackSpeed", speed);
            targetWeight = selected.ContactSensitive ? 1f : Mathf.Clamp01(next.Weight * intensity);
            SetWeight(0);
            // The layer is at zero weight and has finished its previous recovery.
            // Start the clip clock exactly here: crossfading from Empty also
            // blended a default pose and displaced its phase relative to Elapsed.
            animator.Play(path, layer, 0f);
            lastPlayed[next.Id] = Time.unscaledTime;
            lastPlayed["@family:" + AvatarBehaviorPolicy.Family(tag == GestureTag.Auto ? GestureTag.Talk : tag)] = Time.unscaledTime;
            policy.Remember(tag, selected);
            SetHeadLookSuppression?.Invoke((selected.Channels & MotionChannels.Head) != 0 ? 1f : next.HeadLookSuppression);
            Started?.Invoke(next);
            return true;
        }
        private void Update()
        {
            if (active == null) return;
            if (releaseStarted >= 0)
            {
                var t = Mathf.Clamp01((Time.time - releaseStarted) / releaseDuration);
                SetWeight(releaseWeight * (1f - Ease(t)));
                if (t >= 1) Complete();
                return;
            }
            var elapsed = Elapsed;
            var duration = variant.Duration;
            if (elapsed >= duration) { Complete(); return; }
            var attack = Ease(Mathf.Clamp01(elapsed / Mathf.Max(.05f, variant.PreparationSeconds)));
            var release = Ease(Mathf.Clamp01((duration - elapsed) / Mathf.Max(.05f, variant.RecoverySeconds)));
            SetWeight(targetWeight * Mathf.Min(attack, release));
        }
        public void Stop(bool immediate)
        {
            if (active == null) return;
            WasInterrupted = true;
            if (!isActiveAndEnabled || !gameObject.activeInHierarchy) { Complete(); return; }
            if (releaseStarted >= 0) return;
            releaseStarted = Time.time;
            releaseWeight = GetWeight();
            releaseDuration = immediate ? .30f : Mathf.Min(.65f, variant.RecoverySeconds / speed);
        }
        private void Complete()
        {
            var previous = active;
            SetWeight(0);
            if (animator != null && layer >= 0) animator.Play(AvatarMotionNames.StateHash(variant != null ? variant.LayerName : AvatarMotionNames.GestureLayer, AvatarMotionNames.EmptyGestureState), layer, 0);
            active = null; variant = null; releaseStarted = -1;
            SetHeadLookSuppression?.Invoke(0);
            if (previous != null) Finished?.Invoke(previous);
        }
        private void OnDisable() { if (active != null) WasInterrupted = true; Complete(); }
        private float GetWeight() => animator != null && layer >= 0 ? animator.GetLayerWeight(layer) : 0;
        private void SetWeight(float value) { if (animator != null && layer >= 0) animator.SetLayerWeight(layer, value); }
        private static float Ease(float t) => t * t * t * (t * (t * 6f - 15f) + 10f);
        public static GestureDefinition Select(IList<GestureDefinition> values, GestureTag tag, AvatarEmotion emotion, bool speaking,
            int currentPriority, float now, IDictionary<string, float> played, IMotionRandom random, bool ignoreCooldown = false)
        {
            if (values == null || tag == GestureTag.None) return null;
            var effective = tag == GestureTag.Auto ? AvatarMotionNames.ResolveAutoGesture(emotion) : tag;
            if (effective == GestureTag.None) return null;
            var family = AvatarBehaviorPolicy.Family(effective);
            var familyCooldown = -1f;
            foreach (var definition in values) if (definition != null && definition.Tag == family) { familyCooldown = definition.CooldownSeconds; break; }
            var choices = new List<GestureDefinition>();
            foreach (var item in values)
            {
                if (item == null || string.IsNullOrEmpty(item.AnimatorState) || !item.Allows(emotion, speaking)) continue;
                if (item.Tag != effective && item.Tag != AvatarMotionNames.BaseGesture(effective)) continue;
                if (item.Priority < currentPriority) continue;
                var cooldown = familyCooldown >= 0 ? familyCooldown : item.CooldownSeconds;
                var hasPlayed = played.TryGetValue("@family:" + family, out var last) || played.TryGetValue(item.Id, out last);
                if (!ignoreCooldown && hasPlayed && now - last < cooldown) continue;
                choices.Add(item);
            }
            if (choices.Count == 0) return null;
            var exact = choices.FindAll(v => v.Tag == effective);
            return exact.Count > 0 ? exact[random.Range(0, exact.Count)] : choices[random.Range(0, choices.Count)];
        }
    }
}
