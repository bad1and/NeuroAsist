using UnityEngine;
using UnityEngine.Animations.Rigging;

namespace NeuroAsist.Avatar
{
    public sealed class AvatarLookController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private Transform target;
        [SerializeField] private Rig headLookRig;
        [Range(0f, 1f)] [SerializeField] private float weight = 1f;
        [Range(1f, 89f)] [SerializeField] private float maxYaw = 35f;
        [Range(1f, 89f)] [SerializeField] private float maxPitch = 20f;
        [Range(.1f, 20f)] [SerializeField] private float turnSpeed = 5f;
        private Transform head;
        private Quaternion baseLocalRotation;
        private float suppression;
        private Coroutine lookAroundRoutine;
        public void Configure(Animator valueAnimator, Transform valueTarget) { animator = valueAnimator; target = valueTarget; FindHead(); }
        public void SetProfile(MotionProfile profile) { if (profile == null) return; weight = profile.HeadLookWeight; turnSpeed = profile.HeadTurnSpeed; }
        public void SetSuppression(float value) => suppression = Mathf.Clamp01(value);
        public void PlayLookAround(float durationSeconds)
        {
            if (target == null || durationSeconds <= 0f) return;
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = StartCoroutine(LookAround(durationSeconds));
        }
        public void StopLookAround()
        {
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = null;
        }
        private void Awake() => FindHead();
        private void FindHead()
        {
            if (animator == null || !animator.isHuman) return;
            head = animator.GetBoneTransform(HumanBodyBones.Head);
            if (head != null) baseLocalRotation = head.localRotation;
        }
        private void LateUpdate()
        {
            var appliedWeight = weight * (1f - suppression);
            if (headLookRig != null) { headLookRig.weight = appliedWeight; return; }
            if (head == null || target == null || appliedWeight <= 0f) return;
            var direction = target.position - head.position;
            if (direction.sqrMagnitude < .0001f) return;
            var localDirection = animator.transform.InverseTransformDirection(direction.normalized);
            var angles = ClampAngles(Mathf.Atan2(localDirection.x, localDirection.z) * Mathf.Rad2Deg, -Mathf.Asin(localDirection.y) * Mathf.Rad2Deg, maxYaw, maxPitch);
            var yaw = angles.x;
            var pitch = angles.y;
            var wanted = baseLocalRotation * Quaternion.Euler(pitch * appliedWeight, yaw * appliedWeight, 0f);
            head.localRotation = Quaternion.Slerp(head.localRotation, wanted, 1f - Mathf.Exp(-turnSpeed * Time.deltaTime));
        }
        private System.Collections.IEnumerator LookAround(float durationSeconds)
        {
            var initialLocalPosition = target.localPosition;
            var elapsed = 0f;
            while (elapsed < durationSeconds)
            {
                // The target is a child of the camera. Moving this target changes only
                // the head aim; it never changes the avatar root, hips, or feet.
                target.localPosition = initialLocalPosition + new Vector3(
                    Random.Range(-.65f, .65f), Random.Range(-.2f, .3f), Random.Range(-.15f, .15f));
                var pause = Random.Range(1.25f, 2.25f);
                yield return new WaitForSeconds(pause);
                elapsed += pause;
            }
            target.localPosition = initialLocalPosition;
            lookAroundRoutine = null;
        }
        private void OnDisable() => StopLookAround();
        public static Vector2 ClampAngles(float yaw, float pitch, float yawLimit, float pitchLimit) => new Vector2(Mathf.Clamp(yaw, -yawLimit, yawLimit), Mathf.Clamp(pitch, -pitchLimit, pitchLimit));
    }
}
