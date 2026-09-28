using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class VolumeLipSyncFallback : MonoBehaviour
    {
        [SerializeField] private AvatarRuntimeSettings settings;
        [SerializeField] private AudioSource audioSource;
        [SerializeField] private Vrm10Instance vrm;
        [Range(0f, .2f)] public float NoiseGate = .015f;
        [Range(0f, 1f)] public float MaxWeight = .7f;
        public float Attack = .18f;
        public float Release = .08f;
        private float current;
        private readonly float[] samples = new float[256];
        private bool warned;
        private bool forceActiveForMutedPlayback;
        private global::uLipSync.uLipSync primaryLipSync;
        private Vrm10PhonemeLipSync phonemeBridge;
        private bool primaryWasEnabled;
        private bool bridgeWasEnabled;
        private void Awake()
        {
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            primaryLipSync = GetComponent<global::uLipSync.uLipSync>();
            phonemeBridge = GetComponent<Vrm10PhonemeLipSync>();
        }
        private void Update()
        {
            if (!enabled || audioSource == null || !audioSource.isPlaying)
            {
                if (current > 0.001f)
                {
                    current = Mathf.Lerp(current, 0f, Time.deltaTime * Release * 60f);
                    Apply(current);
                }
                else if (current != 0f)
                {
                    current = 0f;
                    Apply(0f);
                }
                return;
            }
            if (!ReadSamples())
            {
                ResetMouth(true);
                return;
            }
            var sum = 0f; for (var i = 0; i < samples.Length; i++) sum += samples[i] * samples[i];
            var rms = Mathf.Sqrt(sum / samples.Length); var target = rms <= NoiseGate ? 0f : Mathf.Clamp01((rms - NoiseGate) * 18f) * MaxWeight;
            current = Mathf.Lerp(current, target, Time.deltaTime * (target > current ? Attack * 60f : Release * 60f));
            Apply(current);
        }
        public bool ShouldBeActive()
        {
            if (forceActiveForMutedPlayback) return true;
            if (settings == null || settings.LipSyncMode == LipSyncMode.Disabled || settings.LipSyncMode == LipSyncMode.ULipSync) return false;
            if (settings.LipSyncMode == LipSyncMode.VolumeFallback) return true;
            return GetComponent<global::uLipSync.uLipSync>() == null;
        }
        public void SetActive(bool value) => enabled = value;
        public void SetMutedPlayback(bool muted)
        {
            if (forceActiveForMutedPlayback == muted) return;
            forceActiveForMutedPlayback = muted;
            if (muted)
            {
                primaryWasEnabled = primaryLipSync != null && primaryLipSync.enabled;
                bridgeWasEnabled = phonemeBridge != null && phonemeBridge.enabled;
                if (primaryLipSync != null) primaryLipSync.enabled = false;
                if (phonemeBridge != null) phonemeBridge.enabled = false;
                enabled = true;
                return;
            }

            ResetMouth(true);
            if (primaryLipSync != null) primaryLipSync.enabled = primaryWasEnabled;
            if (phonemeBridge != null) phonemeBridge.enabled = bridgeWasEnabled;
            enabled = ShouldBeActive();
        }
        public void ResetMouth() => ResetMouth(false);
        public void ResetMouth(bool immediate)
        {
            if (immediate)
            {
                current = 0f;
                Apply(0f);
            }
        }
        private void OnDisable() => ResetMouth(true);
        private bool ReadSamples()
        {
            try
            {
                // AudioSource.GetOutputData is silent when the source is muted.
                // Read the clip directly in desktop-routed mode so lip-sync
                // remains driven by the exact PCM that the browser is playing.
                if (forceActiveForMutedPlayback || audioSource.mute)
                {
                    var clip = audioSource.clip;
                    if (clip == null || clip.samples <= 0) return false;
                    var framesRequested = Mathf.CeilToInt(samples.Length / (float)Mathf.Max(1, clip.channels));
                    var offset = Mathf.Clamp(
                        audioSource.timeSamples - framesRequested / 2,
                        0,
                        Mathf.Max(0, clip.samples - framesRequested));
                    return clip.GetData(samples, offset);
                }
                audioSource.GetOutputData(samples, 0);
                return true;
            }
            catch
            {
                return false;
            }
        }
        private void Apply(float weight)
        {
            if (vrm == null) { DisableFallback(); return; }
            try
            {
                var runtime = vrm.Runtime;
                if (runtime == null) { DisableFallback(); return; }
                runtime.Expression.SetWeight(ExpressionKey.Aa, weight);
            }
            catch { if (!warned) { warned = true; Debug.LogWarning("[LipSync] VRM aa expression unavailable; fallback disabled", this); } enabled = false; }
        }
        private void DisableFallback()
        {
            if (!warned) { warned = true; Debug.LogWarning("[LipSync] VRM aa expression unavailable; fallback disabled", this); }
            enabled = false;
        }
    }
}
