using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarPerformanceProfile : MonoBehaviour
    {
        [SerializeField] private AvatarRuntimeSettings settings;

        private void Awake()
        {
            if (Application.isEditor || settings == null || !settings.ApplyAvatarLowProfile) return;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = Mathf.Max(15, settings.AvatarFrameRate);
            // The Iris host owns the native bounds in the embedded mode.
            // Calling SetResolution here happens after the player is ready and
            // would overwrite its chat-slot rectangle with the standalone
            // 1280×720 default (the source of a fullscreen-looking avatar).
            var embeddedInIris = WindowsDesktopOverlay.IsEmbeddedHost(
                System.Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_HOST"));
            if (ShouldSetStandaloneResolution(embeddedInIris))
                Screen.SetResolution(Mathf.Max(640, settings.AvatarWidth), Mathf.Max(360, settings.AvatarHeight), false);
            QualitySettings.antiAliasing = 0;
            QualitySettings.shadows = ShadowQuality.Disable;
            QualitySettings.pixelLightCount = 1;
            QualitySettings.realtimeReflectionProbes = false;
            QualitySettings.anisotropicFiltering = AnisotropicFiltering.Disable;
            QualitySettings.lodBias = .5f;

            var camera = Camera.main;
            if (camera != null)
            {
                camera.allowHDR = false;
                camera.allowMSAA = false;
                camera.farClipPlane = Mathf.Min(camera.farClipPlane, 20f);
                camera.clearFlags = CameraClearFlags.SolidColor;
            }

            var keptLight = false;
            foreach (var light in FindObjectsByType<Light>(FindObjectsSortMode.None))
            {
                if (!keptLight && light.type == LightType.Directional) { keptLight = true; light.shadows = LightShadows.None; continue; }
                light.enabled = false;
            }
            Debug.Log(embeddedInIris
                ? "[AvatarPerformance] AvatarLow enabled inside Iris; host controls bounds."
                : "[AvatarPerformance] AvatarLow enabled: 1280x720 @ 30 FPS", this);
        }

        public static bool ShouldSetStandaloneResolution(bool embeddedInIris)
        {
            return !embeddedInIris;
        }
    }
}
