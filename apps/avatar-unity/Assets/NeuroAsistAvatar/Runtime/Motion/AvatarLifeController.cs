using System.Collections;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>
    /// Additive biological life layer with natural breathing and post-motion pendulum inertia.
    /// Deliberately avoids the root, hips, legs, head, and mouth to preserve primary animation channels.
    /// </summary>
    [DefaultExecutionOrder(100)]
    public sealed class AvatarLifeController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private Vrm10Instance vrm;
        [SerializeField] private AvatarMotionController motion;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private AvatarEmotionController emotionController;
        [Range(0f, 1.5f)] [SerializeField] private float intensity = 1f;

        private Transform spine;
        private Transform chest;
        private Transform upperChest;
        private Transform leftShoulder;
        private Transform rightShoulder;
        private float phase;
        private float smoothedLife = 1f;
        private float lifeVelocity;
        private Coroutine blink;

        private AvatarState previousState = AvatarState.Idle;

        public void Configure(Animator valueAnimator, Vrm10Instance valueVrm, AvatarMotionController valueMotion, AvatarStateController valueState, AvatarEmotionController valueEmotion = null)
        {
            animator = valueAnimator; vrm = valueVrm; motion = valueMotion; state = valueState; emotionController = valueEmotion; FindBones();
        }

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            if (motion == null) motion = GetComponent<AvatarMotionController>();
            if (state == null) state = GetComponent<AvatarStateController>();
            if (emotionController == null) emotionController = GetComponent<AvatarEmotionController>() ?? GetComponentInParent<AvatarEmotionController>();
            FindBones();
        }

        private void OnEnable()
        {
            phase = Random.Range(0f, Mathf.PI * 2f);
            blink = StartCoroutine(BlinkLoop());
            if (state != null) state.Changed += OnStateChanged;
            if (motion != null) motion.ProfileChanged += OnProfileChanged;
        }

        private void OnDisable()
        {
            if (blink != null) StopCoroutine(blink);
            blink = null;
            SetBlink(0f);
            if (state != null) state.Changed -= OnStateChanged;
            if (motion != null) motion.ProfileChanged -= OnProfileChanged;
        }

        /// <summary>
        /// Torso settling stub: kept for backward compatibility, pendulum swaying disabled for rock-solid posture.
        /// </summary>
        public void TriggerPendulumSettling(float strength = 1f)
        {
        }

        private void OnStateChanged(AvatarState next)
        {
            previousState = next;
        }

        private void OnProfileChanged(MotionProfile newProfile)
        {
        }

        private void LateUpdate()
        {
            if (animator == null) return;
            var profile = motion != null ? motion.CurrentProfile : null;
            var targetLife = intensity * (profile != null ? profile.LifeMotionIntensity : 1f);
            if (state != null)
            {
                if (state.Current == AvatarState.Listening) targetLife *= .88f;
                else if (state.Current == AvatarState.Thinking) targetLife *= .94f;
            }
            if (motion != null && motion.CurrentGesture != "none") targetLife *= .58f;
            smoothedLife = Mathf.SmoothDamp(smoothedLife, targetLife, ref lifeVelocity, 0.45f);

            phase += Time.deltaTime * Mathf.Lerp(.95f, 1.3f, Mathf.Clamp01(smoothedLife));
            var breath = Mathf.Sin(phase) * smoothedLife;

            // Stable biological breathing pitch only (no drunken roll, sway or yaw oscillations)
            Apply(spine, new Vector3(.12f * breath, 0f, 0f));
            Apply(chest, new Vector3(.28f * breath, 0f, 0f));
            Apply(upperChest, new Vector3(.16f * breath, 0f, 0f));
            Apply(leftShoulder, new Vector3(.08f * breath, 0f, 0f));
            Apply(rightShoulder, new Vector3(-.08f * breath, 0f, 0f));
        }

        private IEnumerator BlinkLoop()
        {
            while (true)
            {
                yield return new WaitForSeconds(Random.Range(1.9f, 5.4f));
                if (ShouldSkipProceduralBlink())
                    continue;
                yield return BlinkOnce();
                if (Random.value < .14f)
                {
                    yield return new WaitForSeconds(Random.Range(.09f, .18f));
                    if (!ShouldSkipProceduralBlink())
                        yield return BlinkOnce();
                }
            }
        }

        private bool ShouldSkipProceduralBlink()
        {
            if (emotionController == null) return false;
            var current = emotionController.CurrentEmotion;
            if (string.IsNullOrEmpty(current)) return false;
            var clean = current.Trim().ToLowerInvariant().Replace("-", "_");
            return clean == "wink" || clean == "wink_left" || clean == "teasing" || clean == "playful"
                   || emotionController.GetWeight(ExpressionKey.BlinkRight) > 0.1f
                   || emotionController.GetWeight(ExpressionKey.BlinkLeft) > 0.1f;
        }

        private IEnumerator BlinkOnce()
        {
            const float closeDuration = 0.075f;
            const float openDuration = 0.13f;
            for (var elapsed = 0f; elapsed < closeDuration; elapsed += Time.deltaTime)
            {
                var t = Mathf.Clamp01(elapsed / closeDuration);
                var eased = t * t * (3f - 2f * t);
                SetBlink(eased);
                yield return null;
            }
            for (var elapsed = 0f; elapsed < openDuration; elapsed += Time.deltaTime)
            {
                var t = Mathf.Clamp01(elapsed / openDuration);
                var eased = t * t * (3f - 2f * t);
                SetBlink(1f - eased);
                yield return null;
            }
            SetBlink(0f);
        }

        private void FindBones()
        {
            if (animator == null || !animator.isHuman) return;
            spine = animator.GetBoneTransform(HumanBodyBones.Spine);
            chest = animator.GetBoneTransform(HumanBodyBones.Chest);
            upperChest = animator.GetBoneTransform(HumanBodyBones.UpperChest);
            leftShoulder = animator.GetBoneTransform(HumanBodyBones.LeftShoulder);
            rightShoulder = animator.GetBoneTransform(HumanBodyBones.RightShoulder);
        }

        private static void Apply(Transform target, Vector3 euler)
        {
            if (target != null) target.localRotation *= Quaternion.Euler(euler);
        }

        private void SetBlink(float value)
        {
            if (vrm != null && vrm.Runtime != null)
                vrm.Runtime.Expression.SetWeight(ExpressionKey.Blink, Mathf.Clamp01(value));
        }
    }
}
