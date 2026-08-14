using System.Collections;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>
    /// A tiny additive presence layer.  It deliberately avoids the root, hips,
    /// legs, head and mouth: portrait animation must stay stable while the
    /// Animator, head look and lip-sync own their respective channels.
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
        private Coroutine blink;

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
        }

        private void OnDisable()
        {
            if (blink != null) StopCoroutine(blink);
            blink = null;
            SetBlink(0f);
        }

        private void LateUpdate()
        {
            if (animator == null) return;
            var profile = motion != null ? motion.CurrentProfile : null;
            var life = intensity * (profile != null ? profile.LifeMotionIntensity : 1f);
            if (state != null)
            {
                if (state.Current == AvatarState.Listening) life *= .88f;
                else if (state.Current == AvatarState.Thinking) life *= .94f;
            }
            if (motion != null && motion.CurrentGesture != "none") life *= .58f;
            phase += Time.deltaTime * Mathf.Lerp(.95f, 1.3f, Mathf.Clamp01(life));
            var breath = Mathf.Sin(phase) * life;
            var sway = Mathf.Sin(phase * .43f + 1.7f) * life;
            // Still upper-body only: this reads at normal portrait scale, while
            // leaving the root, hips, legs, head and mouth untouched.
            Apply(spine, new Vector3(.38f * breath, .13f * breath, .05f * sway));
            Apply(chest, new Vector3(.74f * breath, .22f * breath, -.16f * breath + .10f * sway));
            Apply(upperChest, new Vector3(.46f * breath, .18f * breath, .08f * sway));
            Apply(leftShoulder, new Vector3(.16f * breath, .04f * sway, .34f * breath));
            Apply(rightShoulder, new Vector3(-.13f * breath, -.04f * sway, -.29f * breath));
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
            for (var elapsed = 0f; elapsed < .065f; elapsed += Time.deltaTime)
            {
                SetBlink(Mathf.Clamp01(elapsed / .065f));
                yield return null;
            }
            for (var elapsed = 0f; elapsed < .11f; elapsed += Time.deltaTime)
            {
                SetBlink(1f - Mathf.Clamp01(elapsed / .11f));
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
