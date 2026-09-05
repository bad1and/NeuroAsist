using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Coordinates body motion only; facial expressions and lip sync remain independent.</summary>
    public sealed class AvatarMotionController : MonoBehaviour
    {
        private const float MinimumAutomaticAccentSeconds = 1.7f;
        [SerializeField] private AvatarMotionSettings settings;
        [SerializeField] private Animator animator;
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private AvatarWebSocketClient client;
        [SerializeField] private AvatarIdleScheduler idleScheduler;
        [SerializeField] private AvatarGestureController gestureController;
        [SerializeField] private AvatarLookController lookController;
        [SerializeField] private AvatarLifeController lifeController;
        [Range(.25f, 1.5f)] [SerializeField] private float transitionSeconds = .7f;
        [Min(.001f)] [SerializeField] private float rootDriftWarningDistance = .02f;
        private AvatarEmotion emotion = AvatarEmotion.Neutral;
        private MotionProfile profile;
        private Vector3 rootLocalPosition;
        private Quaternion rootLocalRotation;
        private Coroutine speechLoop;
        private int speechGeneration;
        private bool speaking;
        private readonly Dictionary<int, SpeechMotionCue> speechCues = new Dictionary<int, SpeechMotionCue>();
        private readonly Queue<string> recentAutomaticVariants = new Queue<string>();
        private readonly List<float> automaticAccentTimes = new List<float>();
        private Coroutine rootRestoreRoutine;

        private struct SpeechMotionCue
        {
            public float Duration;
            public GestureTag Requested;
            public bool Emphasized;
        }

        public event Action<MotionProfile> ProfileChanged;
        public AvatarEmotion CurrentEmotion => emotion;
        public MotionProfile CurrentProfile => profile;
        public string CurrentGesture => gestureController != null && gestureController.Active != null ? gestureController.Active.Id : "none";
        public bool IsSpeaking => speaking;
        public Animator Animator => animator;

        public void Configure(AvatarMotionSettings value, Animator valueAnimator, Transform root, AvatarStateController valueState)
        {
            settings = value; animator = valueAnimator; avatarRoot = root; state = valueState;
            Initialize();
        }

        private void Awake() => Initialize();

        private void OnEnable()
        {
            if (state != null) state.Changed += OnStateChanged;
            if (state != null) lookController?.SetPresence(state.Current);
            if (idleScheduler != null) idleScheduler.StartScheduling();
        }

        private void OnDisable()
        {
            if (state != null) state.Changed -= OnStateChanged;
            StopSpeechLoop();
            if (idleScheduler != null) idleScheduler.StopScheduling();
            if (rootRestoreRoutine != null) { StopCoroutine(rootRestoreRoutine); rootRestoreRoutine = null; }
        }

        private void Initialize()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (avatarRoot == null && animator != null) avatarRoot = animator.transform;
            if (animator != null) animator.applyRootMotion = false;
            if (avatarRoot != null) { rootLocalPosition = avatarRoot.localPosition; rootLocalRotation = avatarRoot.localRotation; }
            if (idleScheduler == null) idleScheduler = GetComponent<AvatarIdleScheduler>();
            if (gestureController == null) gestureController = GetComponent<AvatarGestureController>();
            if (lookController == null) lookController = GetComponent<AvatarLookController>();
            if (lifeController == null) lifeController = GetComponent<AvatarLifeController>();
            if (idleScheduler != null)
            {
                idleScheduler.Configure(settings);
                idleScheduler.IsBlocked = () => gestureController != null && gestureController.IsPlaying;
                idleScheduler.IsSpeaking = () => speaking;
                idleScheduler.OnIdleRequested = PlayAlternativeIdle;
            }
            if (gestureController != null)
            {
                gestureController.Configure(settings, animator);
                gestureController.SetHeadLookSuppression = value => { if (lookController != null) lookController.SetSuppression(value); };
                gestureController.Finished += _ => RestoreRootAfterOneShot();
                gestureController.Started += definition => client?.Send("avatar.gesture.started", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = definition.Weight });
                gestureController.Finished += definition => client?.Send("avatar.gesture.finished", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = definition.Weight });
                gestureController.Failed += (definition, _) => client?.Send("avatar.gesture.failed", new AvatarGesturePayload { gesture = definition.Tag.ToTransport(), intensity = 0f });
            }
            SetEmotion(settings != null && settings.DefaultProfile != null ? AvatarEmotion.Neutral : emotion);
        }

        public void SetEmotion(string value) => SetEmotion(AvatarMotionNames.ParseEmotion(value));

        public void SetEmotion(AvatarEmotion value)
        {
            var nextProfile = settings != null ? settings.FindProfile(value) : null;
            if (nextProfile == null && settings != null) nextProfile = settings.DefaultProfile;
            var changed = emotion != value || profile != nextProfile;
            emotion = value;
            profile = nextProfile;
            if (profile == null) return;
            profile.ValidateValues();
            idleScheduler?.SetProfile(profile);
            lookController?.SetProfile(profile);
            if (!changed) return;
            PlayBaseIdle();
            ProfileChanged?.Invoke(profile);
            client?.Send("avatar.motion_profile_changed", new AvatarMotionProfilePayload { profile = profile.ProfileId });
        }

        public void SetSpeaking(bool value)
        {
            if (speaking == value) return;
            speaking = value;
            if (animator != null) animator.SetBool(AvatarMotionNames.IsSpeaking, value);
            lookController?.SetSpeaking(value);
            if (value)
            {
                StartSpeechLoop();
            }
            else
            {
                StopSpeechLoop();
                speechCues.Clear();
                lifeController?.TriggerPendulumSettling(1.8f);
                RestoreRootAfterOneShot();
                PlayBaseIdle();
            }
        }

        public void TriggerGesture(GestureTag tag, float intensity = 1f, bool interrupt = true)
        {
            var multiplier = profile == null ? 1f : profile.GestureIntensityMultiplier;
            gestureController?.Trigger(tag, emotion, speaking, Mathf.Clamp01(intensity) * multiplier, interrupt);
        }

        public void BeginSpeechMotion() => speechCues.Clear();

        public void QueueSpeechCue(int sequence, float durationSeconds, AvatarMotionCuePayload cue)
        {
            speechCues[sequence] = new SpeechMotionCue
            {
                Duration = Mathf.Max(0f, durationSeconds),
                Requested = AvatarMotionNames.ParseGesture(cue != null ? cue.gesture : "auto"),
                Emphasized = cue != null && cue.emphasized,
            };
        }

        public void OnSpeechSegmentStarted(int sequence)
        {
            if (!speechCues.TryGetValue(sequence, out var cue)) return;
            speechCues.Remove(sequence);
            if (!speaking || gestureController == null) return;

            var isExplicit = cue.Requested != GestureTag.Auto && cue.Requested != GestureTag.None;
            if (!isExplicit)
            {
                if (gestureController.IsPlaying) return;
                if (!CanScheduleAutomaticAccent(cue.Duration, cue.Requested, Time.unscaledTime, automaticAccentTimes)) return;
            }

            var tag = ResolveSpeechGesture(cue);
            if (tag == GestureTag.None || tag == GestureTag.Auto) return;
            var intensity = (cue.Emphasized ? .86f : .68f) * (profile == null ? 1f : profile.GestureIntensityMultiplier);
            if (!gestureController.Trigger(tag, emotion, true, intensity, isExplicit, new List<string>(recentAutomaticVariants))) return;
            if (!isExplicit)
            {
                RememberAutomaticVariant(gestureController.ActiveVariantId, Time.unscaledTime);
            }
        }

        public void StopGesture(bool immediate = false) => gestureController?.Stop(immediate);

        public void ResetToNeutral()
        {
            speechCues.Clear();
            StopGesture(false);
            SetSpeaking(false);
            SetEmotion(AvatarEmotion.Neutral);
            lifeController?.TriggerPendulumSettling(1.6f);
            RestoreRootAfterOneShot();
        }

        private void OnStateChanged(AvatarState next)
        {
            lookController?.SetPresence(next);
            SetSpeaking(next == AvatarState.Speaking);
            if (next == AvatarState.Error || next == AvatarState.Disconnected) { StopGesture(false); SetSpeaking(false); }
        }

        private void PlayBaseIdle()
        {
            if (animator == null || profile == null || string.IsNullOrWhiteSpace(profile.BaseIdleState)) return;
            var statePath = AvatarMotionNames.StatePath(AvatarMotionNames.BaseLayer, profile.BaseIdleState);
            if (!animator.HasState(0, Animator.StringToHash(statePath))) { Log("Base idle state is not configured: " + profile.BaseIdleState); return; }
            animator.SetFloat(AvatarMotionNames.MotionIntensity, settings == null ? 1f : settings.DefaultMotionIntensity);
            var transition = Mathf.Max(transitionSeconds, 0.95f);
            animator.CrossFadeInFixedTime(statePath, transition, 0);
        }

        private void PlayAlternativeIdle(AlternativeIdleDefinition idle)
        {
            if (animator == null || idle == null || gestureController != null && gestureController.IsPlaying) return;
            if ((idle.LookPattern != IdleLookPattern.None || idle.Id == "IdleLookAround") && lookController != null)
            {
                var pattern = idle.LookPattern == IdleLookPattern.None ? IdleLookPattern.Wander : idle.LookPattern;
                lookController.PlayLookAround(idle.DurationSeconds, pattern);
                return;
            }
            var statePath = AvatarMotionNames.StatePath(AvatarMotionNames.BaseLayer, idle.AnimatorState);
            if (!animator.HasState(0, Animator.StringToHash(statePath))) { Log("Alternative idle state is not configured: " + idle.AnimatorState); return; }
            animator.CrossFadeInFixedTime(statePath, transitionSeconds, 0);
            StartCoroutine(ReturnToBaseAfter(idle.DurationSeconds / Mathf.Max(.1f, idle.Speed)));
        }

        private IEnumerator ReturnToBaseAfter(float seconds)
        {
            yield return new WaitForSeconds(seconds);
            if (!speaking || profile != null && profile.AllowLongIdleWhileSpeaking)
            {
                lifeController?.TriggerPendulumSettling(1.3f);
                PlayBaseIdle();
            }
            RestoreRootAfterOneShot();
        }

        private void StartSpeechLoop() => StopSpeechLoop();

        private void StopSpeechLoop()
        {
            speechGeneration++;
            if (speechLoop != null) { StopCoroutine(speechLoop); speechLoop = null; }
        }

        private GestureTag ResolveSpeechGesture(SpeechMotionCue cue)
        {
            if (cue.Requested != GestureTag.Auto && cue.Requested != GestureTag.None) return cue.Requested;
            // No scripted gestures: only neural network triggers gestures explicitly
            return GestureTag.None;
        }

        private void RememberAutomaticVariant(string variant, float now)
        {
            if (!string.IsNullOrWhiteSpace(variant))
            {
                recentAutomaticVariants.Enqueue(variant);
                while (recentAutomaticVariants.Count > 3) recentAutomaticVariants.Dequeue();
            }
            automaticAccentTimes.Add(now);
            automaticAccentTimes.RemoveAll(value => now - value > 30f);
        }

        public static bool CanScheduleAutomaticAccent(float durationSeconds, GestureTag requested, float now, IList<float> previous)
        {
            // Only explicitly requested gestures are allowed; no automatic scripts
            return requested != GestureTag.Auto && requested != GestureTag.None;
        }

        private void RestoreRootAfterOneShot()
        {
            if (avatarRoot == null) return;
            var drift = Vector3.Distance(avatarRoot.localPosition, rootLocalPosition);
            var angle = Quaternion.Angle(avatarRoot.localRotation, rootLocalRotation);
            if (drift < 0.001f && angle < 0.1f) return;
            if (drift > rootDriftWarningDistance) Log("Root motion drift detected; restoring avatar root smoothly.");
            if (rootRestoreRoutine != null) StopCoroutine(rootRestoreRoutine);
            rootRestoreRoutine = StartCoroutine(SmoothRestoreRoot(0.42f));
        }

        private IEnumerator SmoothRestoreRoot(float duration)
        {
            if (avatarRoot == null) yield break;
            var startPos = avatarRoot.localPosition;
            var startRot = avatarRoot.localRotation;
            var elapsed = 0f;
            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                var t = Mathf.Clamp01(elapsed / duration);
                // Damped harmonic pendulum settling curve (subtle ~3% momentum continuation and soft elastic return)
                var pendulumT = 1f - Mathf.Exp(-4.8f * t) * Mathf.Cos(Mathf.PI * 1.5f * t);
                pendulumT = Mathf.Clamp(pendulumT, 0f, 1.05f);
                avatarRoot.localPosition = Vector3.LerpUnclamped(startPos, rootLocalPosition, pendulumT);
                avatarRoot.localRotation = Quaternion.SlerpUnclamped(startRot, rootLocalRotation, pendulumT);
                yield return null;
            }
            avatarRoot.localPosition = rootLocalPosition;
            avatarRoot.localRotation = rootLocalRotation;
            rootRestoreRoutine = null;
        }

        private void Log(string message) { if (settings != null && settings.DebugLogging) Debug.Log("[AvatarMotion] " + message, this); }
    }
}
