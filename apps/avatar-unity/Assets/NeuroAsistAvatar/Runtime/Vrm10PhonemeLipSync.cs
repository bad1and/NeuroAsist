using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>
    /// Routes uLipSync's detected vowel to the VRM 1.0 expression system.
    /// This avoids hard-coded mesh blend-shape indices, which differ per avatar.
    /// </summary>
    public sealed class Vrm10PhonemeLipSync : MonoBehaviour
    {
        [SerializeField] private Vrm10Instance vrm;
        [SerializeField] private AudioSource audioSource;
        [Range(0f, 1f)] [SerializeField] private float maxWeight = .78f;
        [Range(.01f, .3f)] [SerializeField] private float smoothTime = .05f;

        private readonly ExpressionKey[] keys =
        {
            ExpressionKey.Aa, ExpressionKey.Ih, ExpressionKey.Ou, ExpressionKey.Ee, ExpressionKey.Oh,
        };
        private readonly float[] weights = new float[5];
        private readonly float[] velocity = new float[5];
        private int activeIndex = -1;
        private float targetVolume;

        public void Configure(Vrm10Instance valueVrm, AudioSource valueAudioSource)
        {
            vrm = valueVrm;
            audioSource = valueAudioSource;
        }

        private void Awake()
        {
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            if (audioSource == null) audioSource = GetComponent<AudioSource>();
        }

        public void OnLipSyncUpdate(global::uLipSync.LipSyncInfo info)
        {
            activeIndex = ToIndex(info.phoneme);
            targetVolume = NormalizeVolume(info.rawVolume);
        }

        private void Update()
        {
            if (audioSource == null || !audioSource.isPlaying)
            {
                activeIndex = -1;
                targetVolume = 0f;
            }

            for (var i = 0; i < keys.Length; i++)
            {
                var target = i == activeIndex ? targetVolume * maxWeight : 0f;
                weights[i] = Mathf.SmoothDamp(weights[i], target, ref velocity[i], smoothTime);
                SetWeight(keys[i], weights[i]);
            }
        }

        public void ResetMouth()
        {
            activeIndex = -1;
            targetVolume = 0f;
            for (var i = 0; i < keys.Length; i++)
            {
                weights[i] = 0f;
                velocity[i] = 0f;
                SetWeight(keys[i], 0f);
            }
        }

        private void OnDisable() => ResetMouth();

        private void SetWeight(ExpressionKey key, float value)
        {
            if (vrm == null || vrm.Runtime == null) return;
            vrm.Runtime.Expression.SetWeight(key, value);
        }

        private static int ToIndex(string phoneme)
        {
            switch ((phoneme ?? string.Empty).Trim().ToUpperInvariant())
            {
                case "A": return 0;
                case "I": return 1;
                case "U": return 2;
                case "E": return 3;
                case "O": return 4;
                // A fresh uLipSync profile can have no classified phoneme yet.
                // Keep speech visibly animated until it is calibrated.
                default: return 0;
            }
        }

        private static float NormalizeVolume(float rawVolume)
        {
            if (rawVolume <= 0f) return 0f;
            return Mathf.Clamp01((Mathf.Log10(rawVolume) + 2.5f) / 1f);
        }
    }
}
