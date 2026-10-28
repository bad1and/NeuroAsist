using System.Collections.Generic;
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
        private Bounds? fullBodyBounds;
        private IReadOnlyList<Vector3> fullBodyPoints;
        private bool groundedWelcome;
        private bool desktopFullBody;
        private Bounds? standingBounds;

        public void SetDesktopMode(string mode)
        {
            desktopFullBody = mode == "full_body";
            fullBodyBounds = null;
            fullBodyPoints = null;
            groundedWelcome = false;
            FrameNow();
        }

        public void SetFullBodyFraming(Bounds? bounds, IReadOnlyList<Vector3> points = null, bool groundAtBottom = false)
        {
            fullBodyBounds = bounds;
            fullBodyPoints = points;
            groundedWelcome = groundAtBottom;
            FrameNow();
        }

        public static float FullBodyDistance(Bounds bounds, float aspect, float fieldOfView, float padding = 1.1f, Vector3? direction = null)
        {
            var verticalTangent = Mathf.Tan(fieldOfView * Mathf.Deg2Rad * .5f);
            var inverseView = Quaternion.Inverse(Quaternion.LookRotation(direction ?? Vector3.back, Vector3.up));
            var distance = .1f;
            foreach (var x in new[] { -1f, 1f })
            foreach (var y in new[] { -1f, 1f })
            foreach (var z in new[] { -1f, 1f })
            {
                var point = inverseView * Vector3.Scale(bounds.extents, new Vector3(x, y, z));
                distance = Mathf.Max(distance, Mathf.Abs(point.y) * padding / verticalTangent - point.z,
                    Mathf.Abs(point.x) * padding / (verticalTangent * Mathf.Max(.1f, aspect)) - point.z);
            }
            return distance;
        }

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
            if (desktopFullBody && avatarCamera != null && avatar != null)
            {
                if (!standingBounds.HasValue && TryGetBounds(out var measured)) standingBounds = measured;
                if (standingBounds.HasValue)
                {
                    var full = standingBounds.Value;
                    var standingDistance = FullBodyDistance(full, avatarCamera.aspect, verticalFieldOfView, 1.08f, viewDirection);
                    avatarCamera.fieldOfView = verticalFieldOfView;
                    avatarCamera.transform.SetPositionAndRotation(full.center - viewDirection * standingDistance,
                        Quaternion.LookRotation(viewDirection, Vector3.up));
                    lastWidth = Screen.width; lastHeight = Screen.height;
                    return;
                }
            }
            if (avatarCamera != null && fullBodyBounds.HasValue)
            {
                var full = fullBodyBounds.Value;
                var fullDirection = (viewDirection + Vector3.down * .10f).normalized;
                var fullDistance = FullBodyDistance(full, avatarCamera.aspect, verticalFieldOfView, 1.08f, fullDirection);
                if (fullBodyPoints != null && fullBodyPoints.Count > 0)
                {
                    // Fit the deformed silhouette, avoiding the empty front/top
                    // corners of a world-space box making a seated figure tiny.
                    var inverse = Quaternion.Inverse(Quaternion.LookRotation(fullDirection, Vector3.up));
                    var tangent = Mathf.Tan(verticalFieldOfView * Mathf.Deg2Rad * .5f);
                    fullDistance = .1f;
                    foreach (var vertex in fullBodyPoints)
                    {
                        var point = inverse * (vertex - full.center);
                        fullDistance = Mathf.Max(fullDistance, Mathf.Abs(point.y) * 1.08f / tangent - point.z,
                            Mathf.Abs(point.x) * 1.08f / (tangent * Mathf.Max(.1f, avatarCamera.aspect)) - point.z);
                    }
                }
                avatarCamera.fieldOfView = verticalFieldOfView;
                avatarCamera.transform.SetPositionAndRotation(
                    full.center - fullDirection * fullDistance,
                    Quaternion.LookRotation(fullDirection, Vector3.up));
                if (groundedWelcome && fullBodyPoints != null)
                {
                    // Move the complete silhouette down to the button plane.
                    // Solve in view space so perspective depth and resize do not
                    // introduce a floating gap below the imported floor pose.
                    var inverse = Quaternion.Inverse(avatarCamera.transform.rotation);
                    var tangent = Mathf.Tan(verticalFieldOfView * Mathf.Deg2Rad * .5f);
                    var shift = float.PositiveInfinity;
                    foreach (var vertex in fullBodyPoints)
                    {
                        var point = inverse * (vertex - avatarCamera.transform.position);
                        shift = Mathf.Min(shift, point.y + .99f * point.z * tangent);
                    }
                    if (!float.IsInfinity(shift)) avatarCamera.transform.position += avatarCamera.transform.up * shift;
                }
                lastWidth = Screen.width; lastHeight = Screen.height;
                return;
            }
            if (avatarCamera == null || avatar == null || !TryGetBounds(out var bounds)) return;
            var aspect = Mathf.Max(.1f, avatarCamera.aspect);
            var verticalFovRadians = verticalFieldOfView * Mathf.Deg2Rad;
            var horizontalFovRadians = 2f * Mathf.Atan(Mathf.Tan(verticalFovRadians * .5f) * aspect);
            // The host is a narrow portrait panel.  Framing the complete mesh makes
            // a full-body doll; VTubers instead keep attention on face and upper torso.
            var portraitHeight = bounds.size.y * portraitHeightFraction;
            var halfHeight = portraitHeight * .5f * framingPadding;
            var portraitWidth = portraitHeight * aspect;
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
            if (AvatarPerformanceProfile.IsNativeHosted())
            {
                // Native surfaces share the GPU with the rest of the desktop.
                // Preserve the separate desktop and in-app performance profiles.
                if (avatarCamera != null)
                {
                    // Preserve coverage alpha in the embedded swapchain.
                    avatarCamera.allowHDR = false;
                    avatarCamera.renderingPath = RenderingPath.Forward;
                    avatarCamera.allowMSAA = QualitySettings.antiAliasing > 1;
                    avatarCamera.allowDynamicResolution = false;
                    avatarCamera.clearFlags = CameraClearFlags.SolidColor;
                }
                return;
            }
            if (QualitySettings.names.Length > 0)
                QualitySettings.SetQualityLevel(QualitySettings.names.Length - 1, true);
            QualitySettings.antiAliasing = 4; // Improved from 2
            QualitySettings.shadows = ShadowQuality.All; // Added for MToon lighting
            QualitySettings.anisotropicFiltering = AnisotropicFiltering.Enable;
            QualitySettings.lodBias = 1f;
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = 60;
            if (avatarCamera == null) return;
            avatarCamera.allowHDR = true; // Enabled for better MToon bloom/shading
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
