using UnityEngine;
using UnityEngine.Animations.Rigging;
using UniVRM10;

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
        private float currentSuppression;
        private float suppressionVelocity;
        private Coroutine lookAroundRoutine;
        private Vector3 lookTargetBaseLocalPosition;
        private bool hasLookTargetBase;
        private float gazeInterest = .6f;
        private AvatarState presence = AvatarState.Idle;
        private bool isSpeaking;
        private float currentYaw;
        private float currentPitch;
        private float yawVelocity;
        private float pitchVelocity;
        private Vrm10Instance vrm;
        private float presenceSince, nextAttentionShift;
        private Quaternion beforeLook, afterLook;
        private bool appliedLook;

        public bool IsSpeaking => isSpeaking;

        public void Configure(Animator valueAnimator, Transform valueTarget) { animator = valueAnimator; target = valueTarget; FindHead(); }

        public void SetProfile(MotionProfile profile)
        {
            if (profile == null) return;
            weight = profile.HeadLookWeight;
            gazeInterest = profile.GazeInterest;
            turnSpeed = Mathf.Min(profile.HeadTurnSpeed, 3.25f);
            targetMoveSeconds = Mathf.Lerp(1.05f, .55f, gazeInterest);
        }

        public void SetSuppression(float value) => suppression = Mathf.Clamp01(value);

        public void SetSpeaking(bool value)
        {
            if (isSpeaking == value) return;
            isSpeaking = value;
            if (lookAroundRoutine != null)
            {
                StopCoroutine(lookAroundRoutine);
                lookAroundRoutine = StartCoroutine(ReturnTargetToBase());
            }
        }

        public void SetPresence(AvatarState value)
        {
            if (presence == value) return;
            presence = value;
            presenceSince = Time.time;
            nextAttentionShift = Time.time + (value == AvatarState.Thinking ? 1.2f : Random.Range(7f, 13f));
            if (presence == AvatarState.Listening)
            {
                SetSpeaking(false);
                StopLookAround();
            }
            else if (presence == AvatarState.Speaking)
            {
                SetSpeaking(true);
            }
            else
            {
                SetSpeaking(false);
                StopLookAround();
            }
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
            // During speech: constrain glance duration to brief natural beats (~1.0 - 1.4s)
            // During idle: full authored duration (3.5 - 4.5s)
            float actualDuration = isSpeaking || presence == AvatarState.Listening ? Mathf.Min(durationSeconds * .35f, 1.2f) : durationSeconds;
            lookAroundRoutine = StartCoroutine(LookAround(actualDuration, pattern));
        }

        public void StopLookAround()
        {
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = hasLookTargetBase && target != null
                ? StartCoroutine(ReturnTargetToBase())
                : null;
        }

        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            vrm = animator != null ? animator.GetComponent<Vrm10Instance>() : null;
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            if (vrm != null && target != null)
            {
                vrm.LookAtTarget = target;
                vrm.LookAtTargetType = VRM10ObjectLookAt.LookAtTargetTypes.SpecifiedTransform;
            }
            nextAttentionShift = Time.time + Random.Range(7f, 13f);
            FindHead();
        }

        internal void RestoreLook()
        {
            if (appliedLook && head != null && Quaternion.Angle(head.localRotation, afterLook) < .01f) head.localRotation = beforeLook;
            appliedLook = false;
        }
        private void Update()
        {
            RestoreLook();
            if (Time.time < nextAttentionShift || lookAroundRoutine != null || suppression > .1f) return;
            if (presence == AvatarState.Thinking || presence == AvatarState.Downloading)
            {
                if (Time.time - presenceSince >= 1.2f) PlayLookAround(2.2f, IdleLookPattern.Thoughtful);
                nextAttentionShift = Time.time + Random.Range(12f, 20f);
            }
            else if (presence == AvatarState.Listening || presence == AvatarState.Speaking)
            {
                PlayLookAround(1.3f, IdleLookPattern.SideGlance);
                nextAttentionShift = Time.time + Random.Range(8f, 16f);
            }
        }

        private void FindHead()
        {
            if (animator == null || !animator.isHuman) return;
            head = animator.GetBoneTransform(HumanBodyBones.Head);
            if (head != null) baseLocalRotation = head.localRotation;
        }

        private void LateUpdate()
        {
            currentSuppression = Mathf.SmoothDamp(currentSuppression, suppression, ref suppressionVelocity, 0.22f, 10f, Time.deltaTime);
            var appliedWeight = weight * (1f - currentSuppression);
            if (headLookRig != null) { headLookRig.weight = appliedWeight; return; }
            if (head == null || target == null || appliedWeight <= 0f) return;
            var direction = target.position - head.position;
            if (direction.sqrMagnitude < .0001f) return;
            var localDirection = animator.transform.InverseTransformDirection(direction.normalized);

            // During speech, limit pitch to avoid looking over the user's head (subtle vertical cone)
            // and keep yaw within a natural conversational angle (±14°), while idle retains full freedom
            float limitYaw = isSpeaking ? 14f : maxYaw;
            float limitPitch = isSpeaking ? 8f : maxPitch;
            var angles = ClampAngles(Mathf.Atan2(localDirection.x, localDirection.z) * Mathf.Rad2Deg, -Mathf.Asin(localDirection.y) * Mathf.Rad2Deg, limitYaw, limitPitch);
            var yaw = angles.x;
            var pitch = angles.y;

            if (isSpeaking)
            {
                // In Unity coordinate system, negative pitch tilts the head UP, positive tilts DOWN.
                // Strictly avoid looking upwards over user's head while speaking:
                pitch = Mathf.Max(-1.5f, pitch);
                // Level gaze directly into user's eyes (+3.0° downward leveling lowers chin and aligns eye contact)
                pitch += 3.0f;
            }

            var targetYaw = yaw * appliedWeight * .65f;
            var targetPitch = pitch * appliedWeight * .6f;

            // Physical neck inertia via unconditionally stable spring-damper with natural pendulum elasticity
            // Frequency ~3.8 - 4.8 rad/s and underdamped ratio ~0.68 allows a clearly visible ~8% momentum overshoot and harmonic pendulum rebound
            float springFreq = Mathf.Lerp(3.8f, 4.8f, Mathf.Clamp01(turnSpeed / 3.25f));
            currentYaw = SpringDamp(currentYaw, targetYaw, ref yawVelocity, springFreq, .95f, Time.deltaTime);
            currentPitch = SpringDamp(currentPitch, targetPitch, ref pitchVelocity, springFreq, .95f, Time.deltaTime);

            // Apply look orientation additively to animator's frame rotation, preserving natural posture
            beforeLook = head.localRotation;
            afterLook = beforeLook * Quaternion.Euler(currentPitch, currentYaw, 0f);
            head.localRotation = afterLook;
            appliedLook = true;
        }

        private System.Collections.IEnumerator LookAround(float durationSeconds, IdleLookPattern pattern)
        {
            var elapsed = 0f;
            while (elapsed < durationSeconds)
            {
                // The target is a child of the camera. Moving this target changes only
                // the head aim; it never changes the avatar root, hips, or feet.
                var offset = OffsetFor(pattern, isSpeaking);
                if (presence == AvatarState.Listening) offset *= .18f;
                yield return MoveTargetTo(lookTargetBaseLocalPosition + offset);
                var pause = isSpeaking
                    ? Random.Range(0.6f, 1.1f)
                    : Random.Range(Mathf.Lerp(1.9f, 1.25f, gazeInterest), Mathf.Lerp(3.1f, 2.1f, gazeInterest));
                yield return new WaitForSeconds(pause);
                elapsed += targetMoveSeconds + pause;
                if (isSpeaking || presence == AvatarState.Listening) break;
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
            yield return new WaitForSeconds(Random.Range(1.25f, 2.1f));
            if (presence == AvatarState.Thinking)
                yield return LookAround(Random.Range(2.4f, 3.6f), IdleLookPattern.Thoughtful);
            lookAroundRoutine = null;
        }

        private System.Collections.IEnumerator MoveTargetTo(Vector3 destination)
        {
            if (target == null) yield break;
            var initial = target.localPosition;
            // Eyes acquire the target first; the damped neck follows behind them.
            float moveDuration = isSpeaking || presence == AvatarState.Listening ? .16f : .24f;
            for (var elapsed = 0f; elapsed < moveDuration; elapsed += Time.deltaTime)
            {
                var t = Mathf.Clamp01(elapsed / Mathf.Max(.01f, moveDuration));
                t = t * t * (3f - 2f * t);
                target.localPosition = Vector3.LerpUnclamped(initial, destination, t);
                yield return null;
            }
            target.localPosition = destination;
        }

        private static Vector3 OffsetFor(IdleLookPattern pattern, bool speaking)
        {
            Vector3 offset;
            switch (pattern)
            {
                case IdleLookPattern.SideGlance:
                    offset = new Vector3(Random.value < .5f ? -.55f : .55f, Random.Range(-.08f, .12f), 0f);
                    break;
                case IdleLookPattern.Thoughtful:
                    offset = new Vector3(Random.value < .5f ? -.3f : .3f, Random.Range(.18f, .34f), 0f);
                    break;
                default:
                    offset = new Vector3(Random.Range(-.65f, .65f), Random.Range(-.2f, .3f), Random.Range(-.15f, .15f));
                    break;
            }

            if (speaking)
            {
                // When conversing with the user: allow gentle head turns side-to-side (±0.11m),
                // but strictly avoid looking upwards above user eye level.
                offset.x *= 0.20f;
                offset.y = Mathf.Min(0f, offset.y) * 0.10f; // never look upwards during speech
                offset.z *= 0.15f;
            }

            return offset;
        }

        private void OnDisable()
        {
            RestoreLook();
            if (lookAroundRoutine != null) StopCoroutine(lookAroundRoutine);
            lookAroundRoutine = null;
            if (target != null && hasLookTargetBase) target.localPosition = lookTargetBaseLocalPosition;
        }

        public static Vector2 ClampAngles(float yaw, float pitch, float yawLimit, float pitchLimit) => new Vector2(Mathf.Clamp(yaw, -yawLimit, yawLimit), Mathf.Clamp(pitch, -pitchLimit, pitchLimit));

        /// <summary>
        /// Unconditionally stable implicit spring-damper producing organic pendulum inertia and subtle viscoelastic rebound.
        /// </summary>
        public static float SpringDamp(float current, float target, ref float velocity, float frequency, float dampingRatio, float dt)
        {
            if (dt <= 0f) return current;
            dt = Mathf.Min(dt, 0.05f);
            float f = 1f + 2f * dt * dampingRatio * frequency;
            float oo = frequency * frequency;
            float hoo = dt * oo;
            float hhoo = dt * hoo;
            float detInv = 1f / (f + hhoo);
            float detCurrent = f * current + dt * velocity + hhoo * target;
            float detVelocity = velocity + hoo * (target - current);
            current = detCurrent * detInv;
            velocity = detVelocity * detInv;
            return current;
        }
    }
}
