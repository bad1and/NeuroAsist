using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarPerformanceProfile : MonoBehaviour
    {
        public const int EmbeddedFrameRate = 60;
        // Two samples clean up hair and clothing silhouettes at the narrow
        // in-app size without materially competing with the WebView GPU work.
        public const int EmbeddedAntiAliasing = 4;
        [SerializeField] private AvatarRuntimeSettings settings;

        private void Awake()
        {
            if (Application.isEditor || settings == null) return;
            var embeddedInIris = IsEmbeddedHost();
            if (!ShouldApplyPerformanceProfile(embeddedInIris, settings.ApplyAvatarLowProfile)) return;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = embeddedInIris ? EmbeddedFrameRate : Mathf.Max(15, settings.AvatarFrameRate);
            // The Iris host owns the native bounds in the embedded mode.
            // Calling SetResolution here happens after the player is ready and
            // would overwrite its chat-slot rectangle with the standalone
            // 1280×720 default (the source of a fullscreen-looking avatar).
            if (ShouldSetStandaloneResolution(embeddedInIris))
                Screen.SetResolution(Mathf.Max(640, settings.AvatarWidth), Mathf.Max(360, settings.AvatarHeight), false);
            QualitySettings.antiAliasing = embeddedInIris ? EmbeddedAntiAliasing : 4;
            QualitySettings.shadows = ShadowQuality.All; // Enable shadows for MToon
            QualitySettings.pixelLightCount = 2;
            QualitySettings.realtimeReflectionProbes = false;
            QualitySettings.anisotropicFiltering = AnisotropicFiltering.Enable;
            QualitySettings.lodBias = 1.0f;

            var camera = Camera.main;
            if (camera != null)
            {
                camera.allowHDR = !embeddedInIris;
                camera.allowMSAA = true;
                camera.farClipPlane = Mathf.Min(camera.farClipPlane, 20f);
                camera.clearFlags = CameraClearFlags.SolidColor;
                // The DWM compositor consumes real coverage alpha. Transparent
                // black avoids a matte in anti-aliased hair and the edge blur.
                var background = camera.backgroundColor;
                camera.backgroundColor = embeddedInIris
                    ? Color.clear
                    : new Color(background.r, background.g, background.b, 0f);
                if (embeddedInIris && camera.GetComponent<AvatarEdgeFeather>() == null)
                    camera.gameObject.AddComponent<AvatarEdgeFeather>();
            }

            var keptLight = false;
            foreach (var light in FindObjectsByType<Light>(FindObjectsSortMode.None))
            {
                if (!keptLight && light.type == LightType.Directional) { 
                    keptLight = true; 
                    light.shadows = LightShadows.Soft; // Enable soft shadows for the main directional light
                    continue; 
                }
                light.enabled = false;
            }
            Debug.Log(embeddedInIris
                ? "[AvatarPerformance] Iris embedded profile enabled: 60 FPS, 4x MSAA, Shadows Enabled, host-controlled bounds."
                : "[AvatarPerformance] AvatarLow enabled: 1280x720 @ 30 FPS", this);
        }

        public static bool ShouldSetStandaloneResolution(bool embeddedInIris)
        {
            return !embeddedInIris;
        }

        public static bool ShouldApplyPerformanceProfile(bool embeddedInIris, bool requestedLowProfile)
        {
            return embeddedInIris || requestedLowProfile;
        }

        public static bool IsEmbeddedHost()
        {
            return WindowsDesktopOverlay.IsEmbeddedHost(
                System.Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_HOST"));
        }
    }
}
