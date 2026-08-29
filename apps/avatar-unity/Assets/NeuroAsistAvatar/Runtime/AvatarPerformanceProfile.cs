using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarPerformanceProfile : MonoBehaviour
    {
        public const int EmbeddedFrameRate = 60;
        // Neutral #1d2022 is deliberately close to Iris' in-app surface.
        // The native fallback still uses a colour key, and a neutral matte
        // prevents the former blue fringe from reading as visual grain.
        private static readonly Color EmbeddedColorKey = new Color(29f / 255f, 32f / 255f, 34f / 255f, 0f);
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
                camera.allowHDR = true;
                camera.allowMSAA = true;
                camera.farClipPlane = Mathf.Min(camera.farClipPlane, 20f);
                camera.clearFlags = CameraClearFlags.SolidColor;
                // InApp uses the same neutral clear colour as Tauri's native
                // colour key. It has no saturated blue component to leak into
                // anti-aliased hair or clothing pixels.
                var background = camera.backgroundColor;
                camera.backgroundColor = embeddedInIris
                    ? EmbeddedColorKey
                    : new Color(background.r, background.g, background.b, 0f);
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
