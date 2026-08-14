using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Frames the active avatar as a VTuber-style portrait for its native host.</summary>
    [DisallowMultipleComponent]
    public sealed class AvatarPresentationController : MonoBehaviour
    {
        [SerializeField] private Camera avatarCamera;
        [SerializeField] private Vrm10Instance avatar;
        [Range(20f, 55f)] [SerializeField] private float verticalFieldOfView = 34f;
        [Range(1f, 1.35f)] [SerializeField] private float framingPadding = 1.06f;
        [Tooltip("Visible height as a portion of the avatar's full renderer bounds. 0.48 gives a face-and-torso VTuber framing.")]
        [Range(.3f, .8f)] [SerializeField] private float portraitHeightFraction = .48f;
        [Tooltip("Keeps a small headroom above the hair while biasing the frame toward the face.")]
        [Range(.45f, .6f)] [SerializeField] private float portraitCenterFromTop = .52f;

        private Vector3 viewDirection = Vector3.back;
        private int lastWidth;
        private int lastHeight;

        public void Configure(Camera camera, Vrm10Instance vrm)
        {
            avatarCamera = camera;
            avatar = vrm;
            CacheDirection();
            ApplyRenderQuality();
            FrameNow();
        }

        private void Awake()
        {
            if (avatarCamera == null) avatarCamera = Camera.main;
            if (avatar == null) avatar = GetComponentInChildren<Vrm10Instance>();
            CacheDirection();
            ApplyRenderQuality();
        }

        private void Start() => FrameNow();

        private void LateUpdate()
        {
            if (Screen.width == lastWidth && Screen.height == lastHeight) return;
            FrameNow();
        }

        public void FrameNow()
        {
            if (avatarCamera == null || avatar == null || !TryGetBounds(out var bounds)) return;
            var aspect = Mathf.Max(.1f, avatarCamera.aspect);
            var verticalFovRadians = verticalFieldOfView * Mathf.Deg2Rad;
            var horizontalFovRadians = 2f * Mathf.Atan(Mathf.Tan(verticalFovRadians * .5f) * aspect);
            // The host is a narrow portrait panel.  Framing the complete mesh makes
            // a full-body doll; VTubers instead keep attention on face and upper torso.
            var portraitHeight = bounds.size.y * portraitHeightFraction;
            var halfHeight = portraitHeight * .5f * framingPadding;
            var portraitWidth = portraitHeight * Mathf.Max(.72f, aspect) * .9f;
            var halfWidth = portraitWidth * .5f * framingPadding;
            var distance = Mathf.Max(
                halfHeight / Mathf.Tan(verticalFovRadians * .5f),
                halfWidth / Mathf.Tan(horizontalFovRadians * .5f));
            var target = new Vector3(
                bounds.center.x,
                bounds.max.y - portraitHeight * portraitCenterFromTop,
                bounds.center.z);

            avatarCamera.fieldOfView = verticalFieldOfView;
            avatarCamera.transform.SetPositionAndRotation(
                target - viewDirection * Mathf.Max(distance, .1f),
                Quaternion.LookRotation(viewDirection, Vector3.up));
            avatarCamera.nearClipPlane = .05f;
            avatarCamera.farClipPlane = 50f;
            lastWidth = Screen.width;
            lastHeight = Screen.height;
        }

        private void ApplyRenderQuality()
        {
            if (AvatarPerformanceProfile.IsEmbeddedHost())
            {
                // The embedded D3D surface shares the GPU with WebView. The
                // performance profile configured the 60 FPS, low-overhead path.
                if (avatarCamera != null)
                {
                    avatarCamera.allowHDR = false;
                    avatarCamera.allowMSAA = AvatarPerformanceProfile.EmbeddedAntiAliasing > 1;
                    avatarCamera.allowDynamicResolution = false;
                    avatarCamera.clearFlags = CameraClearFlags.SolidColor;
                }
                return;
            }
            if (QualitySettings.names.Length > 0)
                QualitySettings.SetQualityLevel(QualitySettings.names.Length - 1, true);
            QualitySettings.antiAliasing = 8;
            QualitySettings.anisotropicFiltering = AnisotropicFiltering.ForceEnable;
            QualitySettings.lodBias = Mathf.Max(QualitySettings.lodBias, 2f);
            QualitySettings.vSyncCount = 1;
            Application.targetFrameRate = 60;
            if (avatarCamera == null) return;
            avatarCamera.allowHDR = true;
            avatarCamera.allowMSAA = true;
            avatarCamera.allowDynamicResolution = false;
            avatarCamera.clearFlags = CameraClearFlags.SolidColor;
        }

        private void CacheDirection()
        {
            if (avatarCamera != null && avatarCamera.transform.forward.sqrMagnitude > .001f)
                viewDirection = avatarCamera.transform.forward.normalized;
        }

        private bool TryGetBounds(out Bounds bounds)
        {
            var renderers = avatar.GetComponentsInChildren<Renderer>(true);
            bounds = default;
            var found = false;
            foreach (var renderer in renderers)
            {
                if (!renderer.enabled || !renderer.gameObject.activeInHierarchy) continue;
                if (!found) { bounds = renderer.bounds; found = true; }
                else bounds.Encapsulate(renderer.bounds);
            }
            return found;
        }
    }
}
