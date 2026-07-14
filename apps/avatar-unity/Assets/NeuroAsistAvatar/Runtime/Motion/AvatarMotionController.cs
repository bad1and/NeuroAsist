using System;
using System.Collections;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Coordinates body motion only; facial expressions and lip sync remain independent.</summary>
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
        [Range(.01f, 1f)] [SerializeField] private float transitionSeconds = .25f;
        [Min(.001f)] [SerializeField] private float rootDriftWarningDistance = .02f;
        private AvatarEmotion emotion = AvatarEmotion.Neutral;
        private MotionProfile profile;
        private Vector3 rootLocalPosition;
        private Quaternion rootLocalRotation;
        private Coroutine speechLoop;
        private int speechGeneration;
        private bool speaking;
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
            if (idleScheduler != null) idleScheduler.StartScheduling();
        }
        private void OnDisable()
        {
            if (state != null) state.Changed -= OnStateChanged;
            StopSpeechLoop();
            if (idleScheduler != null) idleScheduler.StopScheduling();
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
            emotion = value;
            profile = settings != null ? settings.FindProfile(value) : null;
            if (profile == null && settings != null) profile = settings.DefaultProfile;
            if (profile == null) return;
            profile.ValidateValues();
            idleScheduler?.SetProfile(profile);
            lookController?.SetProfile(profile);
            PlayBaseIdle();
            ProfileChanged?.Invoke(profile);
            client?.Send("avatar.motion_profile_changed", new AvatarMotionProfilePayload { profile = profile.ProfileId });
            var reaction = EmotionReaction(value);
            if (reaction != GestureTag.None)
                gestureController?.Trigger(reaction, emotion, speaking, profile.GestureIntensityMultiplier, false);
        }
        public void SetSpeaking(bool value)
        {
            if (speaking == value) return;
            speaking = value;
            if (animator != null) animator.SetBool(AvatarMotionNames.IsSpeaking, value);
            if (value) StartSpeechLoop(); else { StopSpeechLoop(); RestoreRootAfterOneShot(); PlayBaseIdle(); }
        }
        public void TriggerGesture(GestureTag tag, float intensity = 1f, bool interrupt = true)
        {
            var multiplier = profile == null ? 1f : profile.GestureIntensityMultiplier;
            gestureController?.Trigger(tag, emotion, speaking, Mathf.Clamp01(intensity) * multiplier, interrupt);
        }
        public void StopGesture(bool immediate = false) => gestureController?.Stop(immediate);
        public void ResetToNeutral()
        {
            StopGesture(false); SetSpeaking(false); SetEmotion(AvatarEmotion.Neutral); RestoreRootAfterOneShot();
        }
        private void OnStateChanged(AvatarState next)
        {
            SetSpeaking(next == AvatarState.Speaking);
            if (next == AvatarState.Thinking) SetEmotion(AvatarEmotion.Thinking);
            if (next == AvatarState.Error || next == AvatarState.Disconnected) { StopGesture(false); SetSpeaking(false); }
        }
        private void PlayBaseIdle()
        {
            if (animator == null || profile == null || string.IsNullOrWhiteSpace(profile.BaseIdleState)) return;
            var statePath = AvatarMotionNames.StatePath(AvatarMotionNames.BaseLayer, profile.BaseIdleState);
            if (!animator.HasState(0, Animator.StringToHash(statePath))) { Log("Base idle state is not configured: " + profile.BaseIdleState); return; }
            animator.SetFloat(AvatarMotionNames.MotionIntensity, settings == null ? 1f : settings.DefaultMotionIntensity);
            animator.CrossFadeInFixedTime(statePath, transitionSeconds, 0);
        }
        private void PlayAlternativeIdle(AlternativeIdleDefinition idle)
        {
            if (animator == null || idle == null || gestureController != null && gestureController.IsPlaying) return;
            if (idle.Id == "IdleLookAround" && lookController != null)
            {
                lookController.PlayLookAround(idle.DurationSeconds);
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
            if (!speaking || profile != null && profile.AllowLongIdleWhileSpeaking) PlayBaseIdle();
            RestoreRootAfterOneShot();
        }
        private void StartSpeechLoop()
        {
            StopSpeechLoop();
            speechLoop = StartCoroutine(AutoGestureLoop(++speechGeneration));
        }
        private void StopSpeechLoop()
        {
            speechGeneration++;
            if (speechLoop != null) { StopCoroutine(speechLoop); speechLoop = null; }
        }
        private IEnumerator AutoGestureLoop(int token)
        {
            while (token == speechGeneration && speaking)
            {
                var frequency = profile == null ? 1f : Mathf.Max(.05f, profile.GestureFrequencyMultiplier);
                var min = settings == null ? 3f : settings.AutoGestureIntervalMinSeconds / frequency;
                var max = settings == null ? 8f : settings.AutoGestureIntervalMaxSeconds / frequency;
                yield return new WaitForSeconds(UnityEngine.Random.Range(min, Mathf.Max(min, max)));
                if (token != speechGeneration || !speaking || gestureController == null || gestureController.IsPlaying) continue;
                if (UnityEngine.Random.value <= (settings == null ? .45f : settings.AutoGestureProbability)) TriggerGesture(GestureTag.Talk, 1f, false);
            }
        }
        private void RestoreRootAfterOneShot()
        {
            if (avatarRoot == null) return;
            var drift = Vector3.Distance(avatarRoot.localPosition, rootLocalPosition);
            if (drift > rootDriftWarningDistance) Debug.LogWarning("[AvatarMotion] Root motion drift detected; restoring avatar root.", this);
            if (drift > rootDriftWarningDistance) avatarRoot.localPosition = rootLocalPosition;
            if (Quaternion.Angle(avatarRoot.localRotation, rootLocalRotation) > 1f) avatarRoot.localRotation = rootLocalRotation;
        }
        private static GestureTag EmotionReaction(AvatarEmotion value)
        {
            switch (value)
            {
                case AvatarEmotion.Happy: return GestureTag.Greeting;
                case AvatarEmotion.Thinking: return GestureTag.Thinking;
                case AvatarEmotion.Surprised: return GestureTag.Surprise;
                case AvatarEmotion.Sad: return GestureTag.Shrug;
                default: return GestureTag.None;
            }
        }
        private void Log(string message) { if (settings != null && settings.DebugLogging) Debug.Log("[AvatarMotion] " + message, this); }
    }
}
