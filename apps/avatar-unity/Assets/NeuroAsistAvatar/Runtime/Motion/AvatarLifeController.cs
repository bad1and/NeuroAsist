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
        private float pendulumAmplitude;
        private float pendulumPhase;

        public void Configure(Animator valueAnimator, Vrm10Instance valueVrm, AvatarMotionController valueMotion, AvatarStateController valueState)
        {
            animator = valueAnimator; vrm = valueVrm; motion = valueMotion; state = valueState; FindBones();
        }

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            if (motion == null) motion = GetComponent<AvatarMotionController>();
            if (state == null) state = GetComponent<AvatarStateController>();
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
        /// Triggers a secondary damped pendulum sway through the torso when returning to neutral posture.
        /// </summary>
        public void TriggerPendulumSettling(float strength = 1f)
        {
            pendulumAmplitude = Mathf.Clamp(pendulumAmplitude + strength * 2.2f, 0f, 3.5f);
            pendulumPhase = 0f;
        }

        private void OnStateChanged(AvatarState next)
        {
            if (previousState == AvatarState.Speaking && next != AvatarState.Speaking)
            {
                // When finishing a speaking turn, dissipate kinetic energy via an organic pendulum recoil
                TriggerPendulumSettling(1.0f);
            }
            previousState = next;
        }

        private void OnProfileChanged(MotionProfile newProfile)
        {
            if (newProfile != null && (newProfile.ProfileId == "neutral" || newProfile.ProfileId == "default"))
            {
                TriggerPendulumSettling(0.75f);
            }
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
            var sway = Mathf.Sin(phase * .43f + 1.7f) * smoothedLife;

            // Physical pendulum inertia: natural harmonic dissipation after large motion/emotion transitions
            float pendulumPitch = 0f;
            float pendulumRoll = 0f;
            float pendulumYaw = 0f;

            if (pendulumAmplitude > 0.001f)
            {
                pendulumPhase += Time.deltaTime * 2.8f;
                pendulumAmplitude = Mathf.MoveTowards(pendulumAmplitude, 0f, Time.deltaTime * 0.35f);
                float envelope = pendulumAmplitude * Mathf.Exp(-pendulumPhase * 0.28f);

                pendulumPitch = Mathf.Cos(pendulumPhase) * envelope * 1.8f;
                pendulumRoll = Mathf.Sin(pendulumPhase * 0.85f) * envelope * 1.5f;
                pendulumYaw = Mathf.Sin(pendulumPhase * 0.65f) * envelope * 0.9f;
            }

            // Apply biological breathing + pendulum dissipation additively to upper-body bones
            Apply(spine, new Vector3((.38f * breath) + (pendulumPitch * 0.60f), (.13f * breath) + (pendulumYaw * 0.50f), (.05f * sway) + (pendulumRoll * 0.60f)));
            Apply(chest, new Vector3((.74f * breath) + (pendulumPitch * 1.10f), (.22f * breath) + (pendulumYaw * 0.90f), (-.16f * breath + .10f * sway) + (pendulumRoll * 1.10f)));
            Apply(upperChest, new Vector3((.46f * breath) + (pendulumPitch * 0.80f), (.18f * breath) + (pendulumYaw * 0.65f), (.08f * sway) + (pendulumRoll * 0.80f)));
            Apply(leftShoulder, new Vector3((.16f * breath) + (pendulumPitch * 0.35f), (.04f * sway), (.34f * breath) + (pendulumRoll * 0.45f)));
            Apply(rightShoulder, new Vector3((-.13f * breath) - (pendulumPitch * 0.35f), (-.04f * sway), (-.29f * breath) - (pendulumRoll * 0.45f)));
        }

        private IEnumerator BlinkLoop()
        {
            while (true)
            {
                yield return new WaitForSeconds(Random.Range(1.9f, 5.4f));
                yield return BlinkOnce();
                if (Random.value < .14f)
                {
                    yield return new WaitForSeconds(Random.Range(.09f, .18f));
                    yield return BlinkOnce();
                }
            }
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
