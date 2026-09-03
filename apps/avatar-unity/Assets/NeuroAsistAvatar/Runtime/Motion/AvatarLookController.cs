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
            if (isSpeaking)
            {
                // When speaking begins, smoothly return gaze target to anchor directly at the user
                if (lookAroundRoutine != null)
                {
                    StopCoroutine(lookAroundRoutine);
                    lookAroundRoutine = StartCoroutine(ReturnTargetToBase());
                }
            }
            else
            {
                // Visible continuation momentum when speech finishes:
                // Prominently carries the head in current motion direction (~2.5°-3.5°), then naturally swings back like an elastic pendulum
                float impulseSign = Mathf.Abs(yawVelocity) > 0.3f ? Mathf.Sign(yawVelocity) : (Random.value < 0.5f ? -1f : 1f);
                yawVelocity = impulseSign * Mathf.Max(Mathf.Abs(yawVelocity) * 1.5f, 9.5f);
                pitchVelocity = Mathf.Max(pitchVelocity, 5.5f); // visible, warm affirmative settling nod
            }
        }

        public void SetPresence(AvatarState value)
        {
            presence = value;
            if (presence == AvatarState.Listening)
            {
                SetSpeaking(false);
                StopLookAround();
            }
            else if (presence == AvatarState.Thinking && target != null && lookAroundRoutine == null)
            {
                SetSpeaking(false);
                lookAroundRoutine = StartCoroutine(ThoughtfulAfterPause());
            }
            else if (presence == AvatarState.Speaking)
            {
                SetSpeaking(true);
            }
            else
            {
                SetSpeaking(false);
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
            float actualDuration = isSpeaking ? Mathf.Min(durationSeconds * 0.35f, 1.4f) : durationSeconds;
            lookAroundRoutine = StartCoroutine(LookAround(actualDuration, pattern));
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

            var targetYaw = yaw * appliedWeight;
            var targetPitch = pitch * appliedWeight;

            // Physical neck inertia via unconditionally stable spring-damper with natural pendulum elasticity
            // Frequency ~3.8 - 4.8 rad/s and underdamped ratio ~0.68 allows a clearly visible ~8% momentum overshoot and harmonic pendulum rebound
            float springFreq = Mathf.Lerp(3.8f, 4.8f, Mathf.Clamp01(turnSpeed / 3.25f));
            currentYaw = SpringDamp(currentYaw, targetYaw, ref yawVelocity, springFreq, 0.68f, Time.deltaTime);
            currentPitch = SpringDamp(currentPitch, targetPitch, ref pitchVelocity, springFreq, 0.70f, Time.deltaTime);

            float effectivePitch = currentPitch;
            float effectiveYaw = currentYaw;

            if (isSpeaking && appliedWeight > 0.1f)
            {
                // Natural conversational micro-movements:
                // Gentle side-to-side inflection (±1.2°)
                float conversationalYaw = Mathf.Sin(Time.time * 1.5f) * 1.2f;
                // Subtle affirming micro-nods DOWN (0 to +0.8° down, never upward)
                float conversationalPitch = Mathf.Max(0f, Mathf.Sin(Time.time * 2.0f)) * 0.8f;

                effectiveYaw += conversationalYaw * (1f - currentSuppression);
                effectivePitch += conversationalPitch * (1f - currentSuppression);
            }

            // Apply look orientation additively to animator's frame rotation, preserving natural breathing/nodding motion
            head.localRotation = head.localRotation * Quaternion.Euler(effectivePitch, effectiveYaw, 0f);
        }

        private System.Collections.IEnumerator LookAround(float durationSeconds, IdleLookPattern pattern)
        {
            var elapsed = 0f;
            while (elapsed < durationSeconds)
            {
                // The target is a child of the camera. Moving this target changes only
                // the head aim; it never changes the avatar root, hips, or feet.
                yield return MoveTargetTo(lookTargetBaseLocalPosition + OffsetFor(pattern, isSpeaking));
                var pause = isSpeaking
                    ? Random.Range(0.6f, 1.1f)
                    : Random.Range(Mathf.Lerp(1.9f, 1.25f, gazeInterest), Mathf.Lerp(3.1f, 2.1f, gazeInterest));
                yield return new WaitForSeconds(pause);
                elapsed += targetMoveSeconds + pause;
                if (isSpeaking) break; // one brief conversational glance is enough, then return to user
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
            float moveDuration = isSpeaking ? Mathf.Min(targetMoveSeconds * 0.65f, 0.45f) : targetMoveSeconds;
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
