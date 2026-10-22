using System;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Conversation-aware director. All semantic and ambient body requests meet here.</summary>
    public sealed class AvatarMotionController : MonoBehaviour
    {
        [SerializeField] private AvatarMotionSettings settings;
        [SerializeField] private Animator animator;
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private AvatarWebSocketClient client;
        [SerializeField] private AvatarIdleScheduler idleScheduler;
        [SerializeField] private AvatarGestureController gestureController;
        [SerializeField] private AvatarLookController lookController;
        [SerializeField] private AvatarLifeController lifeController;
        private readonly AvatarBehaviorPolicy policy = new AvatarBehaviorPolicy();
        private readonly IMotionRandom random = new UnityMotionRandom();
        private readonly Dictionary<int, SpeechMotionCue> speechCues = new Dictionary<int, SpeechMotionCue>();
        private readonly HashSet<int> playedSequences = new HashSet<int>();
        private AvatarEmotion emotion;
        private MotionProfile profile;
        private Vector3 rootPosition;
        private Quaternion rootRotation;
        private Transform cachedRoot;
        private string baseState;
        private bool speaking;
        private int speechGeneration;
        private float segmentEnd, earliestNextGesture, segmentIntensity;
        private GestureTag segmentGesture = GestureTag.None;
        private GestureTag metadataGesture = GestureTag.Auto;
        private float metadataIntensity = .75f;
        private string lastMetadata;
        private AudioSource speechAudio;
        private PendingGesture pending;
        private bool initialized;
        private readonly float[] energyWindow = new float[512];

        private struct SpeechMotionCue { public float Duration; public GestureTag Requested; public bool Emphasized; public float Intensity; }
        private sealed class PendingGesture { public GestureTag Tag; public float Intensity, Due, Expires; public bool Interrupt, SpeechScoped, ExplicitControl; public int Priority; }
        public event Action<MotionProfile> ProfileChanged;
        public AvatarEmotion CurrentEmotion => emotion;
        public MotionProfile CurrentProfile => profile;
        public string CurrentGesture => gestureController?.Active != null ? gestureController.Active.Id : "none";
        public bool IsSpeaking => speaking;
        public Animator Animator => animator;
        public float QuietActivity => state != null && state.Current != AvatarState.Idle ? 1f : policy.QuietActivity(Time.time);
        public int PendingCount => pending == null ? 0 : 1;
        public bool CanPerformGesture(GestureTag tag) => isActiveAndEnabled && settings != null && settings.MotionEnabled && tag != GestureTag.Auto && tag != GestureTag.None
            && settings.GestureDefinitions.Exists(d => d != null && (d.Tag == tag || d.Tag == AvatarMotionNames.BaseGesture(tag)));

        public void Configure(AvatarMotionSettings value, Animator valueAnimator, Transform root, AvatarStateController valueState)
        { settings = value; animator = valueAnimator; avatarRoot = root; state = valueState; Initialize(); }
        private void Awake() => Initialize();
        private void Initialize()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (avatarRoot == null && animator != null) avatarRoot = animator.transform;
            if (animator != null) animator.applyRootMotion = false;
            if (avatarRoot != null && cachedRoot != avatarRoot) { cachedRoot = avatarRoot; rootPosition = avatarRoot.localPosition; rootRotation = avatarRoot.localRotation; }
            if (state == null) state = GetComponent<AvatarStateController>();
            if (idleScheduler == null) idleScheduler = GetComponent<AvatarIdleScheduler>();
            if (gestureController == null) gestureController = GetComponent<AvatarGestureController>();
            if (lookController == null) lookController = GetComponent<AvatarLookController>();
            if (lifeController == null) lifeController = GetComponent<AvatarLifeController>();
            if (idleScheduler != null)
            {
                idleScheduler.Configure(settings);
                idleScheduler.IsBlocked = () => pending != null || gestureController != null && gestureController.IsPlaying;
                idleScheduler.IsSpeaking = () => speaking;
                idleScheduler.Activity = () => QuietActivity;
                idleScheduler.Presence = () => state != null ? state.Current : AvatarState.Idle;
                idleScheduler.OnIdleRequested = PlayAlternativeIdle;
                idleScheduler.OnRestPoseRequested = () => lifeController?.ChangeRestPose();
            }
            if (gestureController != null)
            {
                gestureController.Configure(settings, animator);
                gestureController.SetPolicy(policy);
                gestureController.SetHeadLookSuppression = amount => lookController?.SetSuppression(amount);
                gestureController.Started -= GestureStarted; gestureController.Started += GestureStarted;
                gestureController.Finished -= GestureFinished; gestureController.Finished += GestureFinished;
                gestureController.Failed -= GestureFailed; gestureController.Failed += GestureFailed;
            }
            initialized = true;
            SetEmotion(emotion);
        }
        private void OnEnable()
        {
            if (state != null) { state.Changed -= OnStateChanged; state.Changed += OnStateChanged; lookController?.SetPresence(state.Current); }
            policy.Touch(Time.time);
            idleScheduler?.StartScheduling();
        }
        private void OnDisable()
        {
            if (state != null) state.Changed -= OnStateChanged;
            CancelSpeechMotion();
            idleScheduler?.StopScheduling();
        }
        private void GestureStarted(GestureDefinition definition)
        {
            DeferAutomatic(Time.time);
            client?.Send("avatar.gesture.started", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = definition.Weight });
        }
        private void GestureFinished(GestureDefinition definition)
        {
            policy.Finished(definition.Tag, Time.time);
            earliestNextGesture = Time.time + random.Range(.65f, 1.25f);
            client?.Send("avatar.gesture.finished", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = definition.Weight });
        }
        private void GestureFailed(GestureDefinition definition, string reason)
        { pending = null; client?.Send("avatar.gesture.failed", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = 0 }); }

        public void SetEmotion(string value) => SetEmotion(AvatarMotionNames.ParseEmotion(value));
        public void SetEmotion(AvatarEmotion value)
        {
            var next = settings != null ? settings.FindProfile(value) ?? settings.DefaultProfile : null;
            var changed = emotion != value || profile != next;
            emotion = value; profile = next;
            if (profile == null) return;
            profile.ValidateValues();
            idleScheduler?.SetProfile(profile);
            lookController?.SetProfile(profile);
            // An updated expression must not reset the base clip's time.
            if (baseState != profile.BaseIdleState) PlayBaseIdle();
            if (changed) { ProfileChanged?.Invoke(profile); client?.Send("avatar.motion_profile_changed", new AvatarMotionProfilePayload { profile = profile.ProfileId }); }
        }
        public void SetSpeaking(bool value)
        {
            if (speaking == value) return;
            speaking = value;
            if (animator != null) animator.SetBool(AvatarMotionNames.IsSpeaking, value);
            lookController?.SetSpeaking(value);
            if (value) { policy.Touch(Time.time); DeferAutomatic(Time.time - 2f); }
            else { CancelSpeechMotion(); gestureController?.Stop(false); }
        }
        public void SetSpeechAudio(AudioSource source) => speechAudio = source;
        public void BeginSpeechMotion()
        {
            CancelSpeechMotion();
            pending = null;
            lastMetadata = null; metadataGesture = GestureTag.Auto; metadataIntensity = .75f;
            gestureController?.Stop(true);
        }
        public void SetSpeechMetadata(GestureTag gesture, float intensity)
        {
            var signature = gesture + ":" + intensity.ToString("F3", System.Globalization.CultureInfo.InvariantCulture);
            if (lastMetadata == signature) return;
            lastMetadata = signature;
            metadataGesture = gesture; metadataIntensity = Mathf.Clamp01(intensity);
            // Metadata is a hint for the next audible segment, never a second trigger.
        }
        public void QueueSpeechCue(int sequence, float durationSeconds, AvatarMotionCuePayload cue)
        {
            if (playedSequences.Contains(sequence)) return;
            speechCues[sequence] = new SpeechMotionCue { Duration = Mathf.Max(0, durationSeconds),
                Requested = AvatarMotionNames.ParseGesture(cue?.gesture ?? "auto"), Emphasized = cue != null && cue.emphasized,
                // Legacy protocol-v2 sends nullable intensity. JsonUtility reads
                // null as zero, so inherit the utterance's strength in that case.
                Intensity = cue != null && cue.intensity > 0 ? Mathf.Clamp01(cue.intensity) : metadataIntensity };
        }
        public void OnSpeechSegmentStarted(int sequence)
        {
            if (!speaking || !playedSequences.Add(sequence)) return;
            if (!speechCues.TryGetValue(sequence, out var cue)) return;
            speechCues.Remove(sequence);
            if (pending != null && pending.SpeechScoped) pending = null;
            if (cue.Requested == GestureTag.Auto && metadataGesture != GestureTag.Auto)
            { cue.Requested = metadataGesture; cue.Intensity = metadataIntensity; }
            metadataGesture = GestureTag.Auto;
            segmentGesture = cue.Requested;
            segmentIntensity = cue.Intensity;
            segmentEnd = Time.time + cue.Duration;
            policy.Touch(Time.time);
            if (cue.Requested != GestureTag.Auto && cue.Requested != GestureTag.None)
                Request(cue.Requested, cue.Intensity, true, segmentEnd, true, "segment:" + speechGeneration + ":" + sequence, AccentDelay(cue.Duration, cue.Requested));
        }
        public void TriggerGesture(GestureTag tag, float intensity = 1f, bool interrupt = true, bool controlled = false)
        {
            if (tag == GestureTag.None || tag == GestureTag.Auto) return;
            policy.Touch(Time.time);
            if (controlled) pending = null;
            Request(tag, intensity, interrupt, Time.time + (controlled ? 14f : 6f), false, null, 0);
            if (controlled && pending != null) pending.ExplicitControl = true;
        }
        private void Request(GestureTag tag, float intensity, bool interrupt, float expires, bool speechScoped, string key, float delay)
        {
            if (settings == null || !settings.MotionEnabled || intensity <= 0 || !policy.AcceptCue(key)) return;
            var priority = Priority(tag);
            if (pending != null && pending.Priority > priority) return;
            pending = new PendingGesture { Tag = tag, Intensity = Mathf.Clamp01(intensity), Due = Time.time + delay,
                Expires = expires, Interrupt = interrupt, SpeechScoped = speechScoped, Priority = priority };
        }
        private int Priority(GestureTag tag)
        {
            var definition = settings != null ? settings.GestureDefinitions.Find(d => d != null && d.Tag == tag) : null;
            if (definition != null) return definition.Priority;
            var family = AvatarBehaviorPolicy.Family(tag);
            if (tag == GestureTag.Auto || family == GestureTag.Talk) return 10;
            if (family == GestureTag.Greeting || family == GestureTag.Farewell || family == GestureTag.Facepalm || family == GestureTag.Surprise) return 50;
            return 30;
        }
        private void Update()
        {
            if (settings == null || !settings.MotionEnabled) { pending = null; gestureController?.Stop(false); return; }
            if (pending != null && (Time.time >= pending.Expires || pending.SpeechScoped && !speaking)) pending = null;
            var busy = gestureController != null && gestureController.IsPlaying;
            if (pending != null && busy && pending.Interrupt && gestureController.Phase == GesturePhase.Hold && pending.Priority > Priority(gestureController.Active.Tag))
                gestureController.Stop(false);
            if (pending != null && !busy && Time.time >= pending.Due && (pending.ExplicitControl || Time.time >= earliestNextGesture))
            {
                var tag = pending.Tag;
                var cooldown = AvatarBehaviorPolicy.IsSemantic(tag) ? 1.6f : .65f;
                if ((pending.ExplicitControl || policy.FamilyReady(tag, Time.time, cooldown)) && gestureController != null)
                {
                    var strength = pending.Intensity * (pending.ExplicitControl ? 1 : profile != null ? profile.GestureIntensityMultiplier : 1f);
                    if (gestureController.Trigger(tag, pending.ExplicitControl ? AvatarEmotion.Neutral : emotion, speaking, strength, false, ignoreCooldown: pending.ExplicitControl)) pending = null;
                }
            }

        }
        private void DeferAutomatic(float now) => policy.DeferAutomatic(now, random, profile != null ? profile.GestureFrequencyMultiplier : 1,
            settings != null ? settings.AutoGestureIntervalMinSeconds : 4, settings != null ? settings.AutoGestureIntervalMaxSeconds : 8);
        private float AccentDelay(float remaining, GestureTag tag)
        {
            if (remaining < 1.7f || speechAudio == null || speechAudio.clip == null) return 0;
            var clip = speechAudio.clip;
            var best = 0f; var peak = 0f;
            var family = tag == GestureTag.Auto ? GestureTag.Talk : AvatarBehaviorPolicy.Family(tag);
            var strokeAnchor = family == GestureTag.Talk || family == GestureTag.Explanation || family == GestureTag.Question ? 1.05f : .65f;
            // Read PCM, not the muted output bus. A few bounded windows only
            // refine the next stroke; syllables never trigger separate gestures.
            for (var i = 1; i <= 6; i++)
            {
                var delay = i * .09f;
                // Look ahead by preparation + the middle of the stroke, so the
                // accent (rather than the hand's first movement) meets the peak.
                var offset = speechAudio.timeSamples + Mathf.RoundToInt((delay + strokeAnchor) * clip.frequency);
                if (offset + energyWindow.Length >= clip.samples) break;
                if (!clip.GetData(energyWindow, offset)) break;
                var energy = 0f; foreach (var sample in energyWindow) energy += sample * sample;
                if (energy > peak) { peak = energy; best = delay; }
            }
            return best;
        }
        private void CancelSpeechMotion()
        {
            speechGeneration++; speechCues.Clear(); playedSequences.Clear();
            segmentEnd = 0; segmentIntensity = 0; segmentGesture = GestureTag.None;
            if (pending != null && pending.SpeechScoped) pending = null;
        }
        public void StopGesture(bool immediate = false) { pending = null; gestureController?.Stop(immediate); }
        public void ResetToNeutral()
        { CancelSpeechMotion(); StopGesture(true); SetSpeaking(false); SetEmotion(AvatarEmotion.Neutral); }
        private void OnStateChanged(AvatarState next)
        {
            lookController?.SetPresence(next);
            policy.Touch(Time.time);
            SetSpeaking(next == AvatarState.Speaking);
            if (next == AvatarState.Error || next == AvatarState.Disconnected) { StopGesture(true); GetComponent<AvatarBodyController>()?.ResetBody("disconnected"); }
        }
        private void PlayBaseIdle()
        {
            if (animator == null || profile == null || string.IsNullOrEmpty(profile.BaseIdleState)) return;
            var path = AvatarMotionNames.StatePath(AvatarMotionNames.BaseLayer, profile.BaseIdleState);
            if (!animator.HasState(0, Animator.StringToHash(path))) return;
            baseState = profile.BaseIdleState;
            animator.CrossFadeInFixedTime(path, .8f, 0);
        }
        private void PlayAlternativeIdle(AlternativeIdleDefinition idle)
        {
            if (idle == null || gestureController != null && gestureController.IsPlaying) return;
            lookController?.PlayLookAround(idle.DurationSeconds, idle.LookPattern == IdleLookPattern.None ? IdleLookPattern.Wander : idle.LookPattern);
        }
        private void LateUpdate()
        {
            // Source clips never own world placement; correct an accidental root
            // write before rendering instead of accumulating drift across one-shots.
            if (avatarRoot != null && initialized) { avatarRoot.localPosition = rootPosition; avatarRoot.localRotation = rootRotation; }
        }
        public static bool CanScheduleAutomaticAccent(float durationSeconds, GestureTag requested, float now, IList<float> previous)
        {
            if (requested == GestureTag.None || requested == GestureTag.Auto) return false;
            if (AvatarBehaviorPolicy.IsSemantic(requested)) return true;
            if (durationSeconds < 1.7f) return false;
            return previous == null || previous.Count == 0 || now - previous[previous.Count - 1] >= 4f;
        }
    }
}
