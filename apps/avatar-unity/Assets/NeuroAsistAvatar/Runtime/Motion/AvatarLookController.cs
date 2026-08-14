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
        [Range(.1f, 20f)] [SerializeField] private float turnSpeed = 3.25f;
        [Range(.1f, 2f)] [SerializeField] private float targetMoveSeconds = .75f;
        private Transform head;
        private Quaternion baseLocalRotation;
        private float suppression;
        private Coroutine lookAroundRoutine;
        private Vector3 lookTargetBaseLocalPosition;
        private bool hasLookTargetBase;
        private float gazeInterest = .6f;
        private AvatarState presence = AvatarState.Idle;
        public void Configure(Animator valueAnimator, Transform valueTarget) { animator = valueAnimator; target = valueTarget; FindHead(); }
        public void SetProfile(MotionProfile profile)
        {
            if (profile == null) return;
            weight = profile.HeadLookWeight;
            gazeInterest = profile.GazeInterest;
            // A fast authored profile should not turn a portrait head into a camera pan.
            turnSpeed = Mathf.Min(profile.HeadTurnSpeed, 3.25f);
            targetMoveSeconds = Mathf.Lerp(1.05f, .55f, gazeInterest);
        }
        public void SetSuppression(float value) => suppression = Mathf.Clamp01(value);
        public void SetPresence(AvatarState value)
        {
            presence = value;
            if (presence == AvatarState.Listening) StopLookAround();
            else if (presence == AvatarState.Thinking && target != null && lookAroundRoutine == null)
                lookAroundRoutine = StartCoroutine(ThoughtfulAfterPause());
        }
        public void PlayLookAround(float durationSeconds, IdleLookPattern pattern = IdleLookPattern.Wander)
        {
            if (target == null || durationSeconds <= 0f) return;
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            if (!hasLookTargetBase)
            {
                lookTargetBaseLocalPosition = target.localPosition;
                hasLookTargetBase = true;
            }
            lookAroundRoutine = StartCoroutine(LookAround(durationSeconds, pattern));
        }
        public void StopLookAround()
        {
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = hasLookTargetBase && target != null
                ? StartCoroutine(ReturnTargetToBase())
                : null;
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
        private System.Collections.IEnumerator LookAround(float durationSeconds, IdleLookPattern pattern)
        {
            var elapsed = 0f;
            while (elapsed < durationSeconds)
            {
                // The target is a child of the camera. Moving this target changes only
                // the head aim; it never changes the avatar root, hips, or feet.
                yield return MoveTargetTo(lookTargetBaseLocalPosition + OffsetFor(pattern));
                var pause = Random.Range(Mathf.Lerp(1.9f, 1.25f, gazeInterest), Mathf.Lerp(3.1f, 2.1f, gazeInterest));
                yield return new WaitForSeconds(pause);
                elapsed += targetMoveSeconds + pause;
            }
            yield return MoveTargetTo(lookTargetBaseLocalPosition);
            lookAroundRoutine = null;
        }
        private System.Collections.IEnumerator ReturnTargetToBase()
        {
            yield return MoveTargetTo(lookTargetBaseLocalPosition);
            lookAroundRoutine = null;
        }
        private System.Collections.IEnumerator ThoughtfulAfterPause()
        {
            // Avoid an immediate "thinking animation" flash while the LLM is
            // still preparing a short answer. A real pause earns one glance.
            yield return new WaitForSeconds(Random.Range(1.25f, 2.1f));
            if (presence == AvatarState.Thinking)
                yield return LookAround(Random.Range(2.4f, 3.6f), IdleLookPattern.Thoughtful);
            lookAroundRoutine = null;
        }
        private System.Collections.IEnumerator MoveTargetTo(Vector3 destination)
        {
            if (target == null) yield break;
            var initial = target.localPosition;
            for (var elapsed = 0f; elapsed < targetMoveSeconds; elapsed += Time.deltaTime)
            {
                var t = Mathf.Clamp01(elapsed / Mathf.Max(.01f, targetMoveSeconds));
                t = t * t * (3f - 2f * t);
                target.localPosition = Vector3.LerpUnclamped(initial, destination, t);
                yield return null;
            }
            target.localPosition = destination;
        }
        private static Vector3 OffsetFor(IdleLookPattern pattern)
        {
            switch (pattern)
            {
                case IdleLookPattern.SideGlance:
                    return new Vector3(Random.value < .5f ? -.55f : .55f, Random.Range(-.08f, .12f), 0f);
                case IdleLookPattern.Thoughtful:
                    return new Vector3(Random.value < .5f ? -.3f : .3f, Random.Range(.18f, .34f), 0f);
                default:
                    return new Vector3(Random.Range(-.65f, .65f), Random.Range(-.2f, .3f), Random.Range(-.15f, .15f));
            }
        }
        private void OnDisable()
        {
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = null;
            if (target != null && hasLookTargetBase) target.localPosition = lookTargetBaseLocalPosition;
        }
        public static Vector2 ClampAngles(float yaw, float pitch, float yawLimit, float pitchLimit) => new Vector2(Mathf.Clamp(yaw, -yawLimit, yawLimit), Mathf.Clamp(pitch, -pitchLimit, pitchLimit));
    }
}
