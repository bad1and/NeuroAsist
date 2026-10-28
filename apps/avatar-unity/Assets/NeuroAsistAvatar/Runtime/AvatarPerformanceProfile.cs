using UnityEngine;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarPerformanceProfile : MonoBehaviour
    {
        public const int EmbeddedFrameRate = 60;
        public const int EmbeddedAntiAliasing = 8;
        public const int DesktopFrameRate = 30;
        public const int DesktopAntiAliasing = 4;
        [SerializeField] private AvatarRuntimeSettings settings;
        public string SelectedQuality { get; private set; }
        public int FrameRate => FrameRateFor(SelectedQuality ?? DefaultQuality(IsManagedDesktopHost()), IsManagedDesktopHost());

        public static string DefaultQuality(bool desktop) => desktop ? "medium" : "high";
        public static int AntiAliasingFor(string quality) => quality == "low" ? 2 : quality == "medium" ? 4 : 8;
        public static int FrameRateFor(string quality, bool desktop) => quality == "low" || desktop && quality != "high" ? 30 : 60;

        public bool ConfigureQuality(string inAppQuality, string desktopQuality)
        {
            return ApplyQuality(IsManagedDesktopHost() ? desktopQuality : inAppQuality);
        }

        public bool ApplyQuality(string quality)
        {
            if (quality != "low" && quality != "medium" && quality != "high") return false;
            if (SelectedQuality == quality) return true;
            SelectedQuality = quality;
            QualitySettings.vSyncCount = 0;
            if (GetComponent<AvatarSleepController>()?.IsSleeping != true)
                Application.targetFrameRate = FrameRate;
            QualitySettings.antiAliasing = AntiAliasingFor(quality);
            // MToon needs shadowing for the original skin and clothing tones,
            // even in the economical preset. Only the shadow-map resolution varies.
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = quality == "low" ? ShadowResolution.Low
                : quality == "medium" ? ShadowResolution.Medium : ShadowResolution.High;
            QualitySettings.anisotropicFiltering = quality == "low"
                ? AnisotropicFiltering.Disable : AnisotropicFiltering.Enable;
            var camera = Camera.main;
            if (camera != null)
            {
                // MSAA is supported by the built-in Forward rendering path.
                camera.renderingPath = RenderingPath.Forward;
                camera.allowMSAA = true;
            }
            Debug.Log($"[AvatarQuality] {(IsManagedDesktopHost() ? "desktop" : "in-app")}: {quality}, {FrameRate} FPS, {QualitySettings.antiAliasing}x MSAA, soft shadows.", this);
            return true;
        }

        private void Awake()
        {
            if (Application.isEditor || settings == null) return;
            var embeddedInIris = IsNativeHosted();
            var desktop = IsManagedDesktopHost();
            if (!ShouldApplyPerformanceProfile(embeddedInIris, settings.ApplyAvatarLowProfile)) return;
            var quality = System.Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_QUALITY");
            if (!ApplyQuality(quality)) ApplyQuality(DefaultQuality(desktop));
            if (!embeddedInIris) Application.targetFrameRate = Mathf.Max(15, settings.AvatarFrameRate);
            // The Iris host owns the native bounds in the embedded mode.
            // Calling SetResolution here happens after the player is ready and
            // would overwrite its chat-slot rectangle with the standalone
            // 1280×720 default (the source of a fullscreen-looking avatar).
            if (ShouldSetStandaloneResolution(embeddedInIris))
                Screen.SetResolution(Mathf.Max(640, settings.AvatarWidth), Mathf.Max(360, settings.AvatarHeight), false);
            QualitySettings.pixelLightCount = desktop ? 1 : 2;
            QualitySettings.realtimeReflectionProbes = false;
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
                    light.shadows = LightShadows.Soft;
                    continue; 
                }
                light.enabled = false;
            }
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

        public static bool IsManagedDesktopHost() => WindowsDesktopOverlay.IsManagedDesktopHost(
            System.Environment.GetEnvironmentVariable("NEUROASIST_AVATAR_HOST"));

        public static bool IsNativeHosted() => IsEmbeddedHost() || IsManagedDesktopHost();
    }
}
