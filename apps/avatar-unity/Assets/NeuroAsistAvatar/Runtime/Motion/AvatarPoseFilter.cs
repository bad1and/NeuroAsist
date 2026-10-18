using System.Collections.Generic;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>One final, bounded skeletal pose, before VRM eyes/expressions/spring bones.</summary>
    [DefaultExecutionOrder(300)]
    public sealed class AvatarPoseFilter : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [Range(25, 50)] [SerializeField] private float wristSwingLimit = 45;
        [Range(5, 30)] [SerializeField] private float wristTwistLimit = 20;
        private sealed class Joint
        {
            public Transform Bone;
            public Quaternion Rest, Input, Output;
            public Quaternion FacingInParent, FacingInBone;
            public HumanBodyBones Id;
            public Vector3 Axis, Velocity, AccelerationState;
            public float SmoothTime, Speed, Acceleration, Swing = 180, Twist = 180;
            public bool Initialized;
        }
        private readonly List<Joint> joints = new List<Joint>();
        private bool applied;
        private Transform measuredHead, measuredChest;
        private Quaternion facingInHead, facingInChest;
        private Quaternion neutralFacing;
        public Vector3 MeasureHeadAngles() => measuredHead == null ? Vector3.zero : AnatomicalAngles(Quaternion.Inverse(measuredChest.rotation * facingInChest) * measuredHead.rotation * facingInHead);
        public static Vector3 AnatomicalAngles(Quaternion rotation)
        {
            var forward = rotation * Vector3.forward;
            var yaw = Mathf.Atan2(forward.x,forward.z) * Mathf.Rad2Deg;
            var pitch = -Mathf.Atan2(forward.y,new Vector2(forward.x,forward.z).magnitude) * Mathf.Rad2Deg;
            var upright = Quaternion.Euler(pitch,yaw,0) * Vector3.up;
            var actualUp = rotation * Vector3.up;
            var roll = Mathf.Atan2(Vector3.Dot(forward,Vector3.Cross(upright,actualUp)),Vector3.Dot(upright,actualUp)) * Mathf.Rad2Deg;
            return new Vector3(pitch,yaw,roll);
        }
        public static Quaternion LimitAnatomical(Quaternion rotation, float yaw, float up, float down, float roll)
        {
            var angles = AnatomicalAngles(rotation);
            var pitch = angles.x >= 0 ? down : up;
            var budget = Mathf.Sqrt(Mathf.Pow(angles.x/pitch,2) + Mathf.Pow(angles.y/yaw,2) + Mathf.Pow(angles.z/roll,2));
            if (budget > 1) angles /= budget;
            return Quaternion.Euler(angles.x,angles.y,angles.z);
        }
        public void Configure(Animator value) { animator = value; }
        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (animator == null || !animator.isHuman) return;
            measuredHead = animator.GetBoneTransform(HumanBodyBones.Head);
            measuredChest = animator.GetBoneTransform(HumanBodyBones.UpperChest) ?? animator.GetBoneTransform(HumanBodyBones.Chest);
            var forward = Camera.main != null ? Camera.main.transform.position - measuredHead.position : animator.transform.forward;
            var facing = Quaternion.LookRotation(Vector3.ProjectOnPlane(forward,animator.transform.up).normalized,animator.transform.up);
            neutralFacing = facing;
            facingInHead = Quaternion.Inverse(measuredHead.rotation) * facing;
            facingInChest = Quaternion.Inverse(measuredChest.rotation) * facing;
            // Awake precedes the first Animator evaluation: the imported bind pose
            // supplies anatomical axes, independent of the current gesture.
            Add(HumanBodyBones.Spine, .15f, 60, 500);
            Add(HumanBodyBones.Chest, .15f, 60, 500);
            Add(HumanBodyBones.UpperChest, .15f, 60, 500);
            Add(HumanBodyBones.Neck, .20f, 40, 240);
            Add(HumanBodyBones.Head, .18f, 60, 350);
            foreach (var left in new[] { true, false })
            {
                Add(left ? HumanBodyBones.LeftShoulder : HumanBodyBones.RightShoulder, .13f, 110, 800);
                if (GetComponent<AvatarArmRig>() != null) continue;
                Add(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm, .12f, 180, 1400);
                var forearm = Add(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm, .11f, 210, 1600);
                var hand = Add(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand, .10f, 240, 1800);
                if (forearm != null && hand != null)
                {
                    forearm.Axis = forearm.Bone.InverseTransformDirection(hand.Bone.position - forearm.Bone.position).normalized;
                    forearm.Swing = 145; forearm.Twist = 80;
                }
                var finger = animator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                if (hand != null && finger != null)
                {
                    hand.Axis = hand.Bone.InverseTransformDirection(finger.position - hand.Bone.position).normalized;
                    hand.Swing = Mathf.Min(wristSwingLimit, 45); hand.Twist = wristTwistLimit;
                }
            }
            // Hand shapes also arrive gradually. Eyes and jaw deliberately remain
            // under VRM/lip sync control and are never filtered here.
            for (var bone = HumanBodyBones.LeftThumbProximal; bone <= HumanBodyBones.RightLittleDistal; bone++)
                Add(bone, .07f, 300, 2400);
            var reset = gameObject.AddComponent<AvatarPoseInputRestore>();
            reset.Filter = this;
            reset.Body = GetComponent<AvatarBodyController>();
            reset.Arms = GetComponent<AvatarArmRig>();
            reset.Contact = GetComponent<AvatarContactController>();
            reset.Life = GetComponent<AvatarLifeController>();
            reset.Look = GetComponent<AvatarLookController>();
        }
        private Joint Add(HumanBodyBones id, float time, float speed, float acceleration)
        {
            var bone = animator.GetBoneTransform(id);
            if (bone == null) return null;
            var joint = new Joint { Bone = bone, Id = id, Rest = bone.localRotation, SmoothTime = time, Speed = speed, Acceleration = acceleration,
                FacingInParent = Quaternion.Inverse(bone.parent.rotation) * neutralFacing, FacingInBone = Quaternion.Inverse(bone.rotation) * neutralFacing };
            joints.Add(joint);
            return joint;
        }
        internal void RestoreInput()
        {
            if (!applied) return;
            foreach (var joint in joints) if (joint.Bone != null) joint.Bone.localRotation = joint.Input;
            applied = false;
        }
        private void LateUpdate()
        {
            var dt = Mathf.Min(Time.deltaTime, .1f);
            if (dt <= 0 || animator == null || !animator.enabled) return;
            foreach (var joint in joints)
            {
                joint.Input = joint.Bone.localRotation;
                var target = joint.Axis.sqrMagnitude > .1f
                    ? LimitJoint(joint.Input, joint.Rest, joint.Axis, joint.Swing, joint.Twist) : joint.Input;
                target = LimitHead(joint,target);
                if (!joint.Initialized) { joint.Output = target; joint.Velocity = joint.AccelerationState = Vector3.zero; joint.Initialized = true; }
                var previousOutput = joint.Output;
                joint.Output = DampRotation(joint.Output, target, ref joint.Velocity, ref joint.AccelerationState, dt, joint.SmoothTime, joint.Speed, joint.Acceleration);
                if (joint.Id == HumanBodyBones.Neck || joint.Id == HumanBodyBones.Head)
                {
                    var bounded = LimitHead(joint,joint.Output);
                    var correction = bounded * Quaternion.Inverse(joint.Output);
                    correction.ToAngleAxis(out var angle,out var axis);
                    if (angle > .02f && axis.sqrMagnitude > .1f && Vector3.Dot(joint.Velocity,axis) < 0)
                        joint.Velocity = Vector3.ProjectOnPlane(joint.Velocity,axis);
                    joint.Output = bounded;
                }
                // Forearm roll limits apply to the spring target. Projecting an
                // in-flight elbow back into swing/twist coordinates can jump to
                // the other branch near a folded, mirrored arm.
                if (joint.Axis.sqrMagnitude > .1f && joint.Swing <= 50)
                {
                    var limited = LimitJoint(joint.Output, joint.Rest, joint.Axis, joint.Swing, joint.Twist);
                    var correction = limited * Quaternion.Inverse(joint.Output);
                    correction.ToAngleAxis(out var angle, out var axis);
                    if (angle > .02f && axis.sqrMagnitude > .1f && Vector3.Dot(joint.Velocity, axis) < 0)
                        joint.Velocity = Vector3.ProjectOnPlane(joint.Velocity, axis);
                    joint.Output = Quaternion.RotateTowards(previousOutput, limited, joint.Speed * dt);
                }
                joint.Bone.localRotation = joint.Output;
            }
            applied = true;
        }
        private Quaternion LimitHead(Joint joint, Quaternion local)
        {
            if (joint.Id != HumanBodyBones.Head && joint.Id != HumanBodyBones.Neck) return local;
            var delta = Quaternion.Inverse(joint.FacingInParent) * local * joint.FacingInBone;
            var bounded = joint.Id == HumanBodyBones.Neck ? LimitAnatomical(delta,10,10,12,5) : LimitAnatomical(delta,28,14,22,10);
            local = joint.FacingInParent * bounded * Quaternion.Inverse(joint.FacingInBone);
            if (joint.Id == HumanBodyBones.Neck) return local;
            // Neck + head + look/gesture layers share one budget relative to the
            // chest. Two individually legal rotations must not add into a twist.
            var chestFacing = measuredChest.rotation * facingInChest;
            delta = Quaternion.Inverse(chestFacing) * joint.Bone.parent.rotation * local * joint.FacingInBone;
            bounded = LimitAnatomical(delta,32,16,26,12);
            return Quaternion.Inverse(joint.Bone.parent.rotation) * chestFacing * bounded * Quaternion.Inverse(joint.FacingInBone);
        }
        private void OnDisable() { RestoreInput(); foreach (var joint in joints) { joint.Velocity = joint.AccelerationState = Vector3.zero; joint.Initialized = false; } }
        public static Quaternion LimitJoint(Quaternion value, Quaternion rest, Vector3 axis, float swingLimit, float twistLimit)
        {
            var delta = Quaternion.Inverse(rest) * value;
            var projection = Vector3.Project(new Vector3(delta.x, delta.y, delta.z), axis);
            var twist = new Quaternion(projection.x, projection.y, projection.z, delta.w);
            twist = Quaternion.Dot(twist, twist) > .000001f ? twist.normalized : Quaternion.identity;
            var swing = delta * Quaternion.Inverse(twist);
            return rest * Quaternion.RotateTowards(Quaternion.identity, swing, swingLimit)
                * Quaternion.RotateTowards(Quaternion.identity, twist, twistLimit);
        }
        public static Quaternion DampRotation(Quaternion value, Quaternion target, ref Vector3 velocity, float dt, float smoothTime, float maxSpeed, float maxAcceleration)
        {
            var acceleration = Vector3.zero;
            return DampRotation(value, target, ref velocity, ref acceleration, dt, smoothTime, maxSpeed, maxAcceleration, false);
        }
        public static Quaternion DampRotation(Quaternion value, Quaternion target, ref Vector3 velocity, ref Vector3 acceleration, float dt, float smoothTime, float maxSpeed, float maxAcceleration)
            => DampRotation(value, target, ref velocity, ref acceleration, dt, smoothTime, maxSpeed, maxAcceleration, true);

        // atan2 keeps the tiny vector part of a quaternion. ToAngleAxis uses its
        // scalar part, which rounds to 1 near rest and creates a visible dead zone.
        public static Vector3 RotationDisplacement(Quaternion rotation)
        {
            if (rotation.w < 0) rotation = new Quaternion(-rotation.x, -rotation.y, -rotation.z, -rotation.w);
            var vector = new Vector3(rotation.x, rotation.y, rotation.z);
            var length = vector.magnitude;
            return length > 1e-8f ? vector * (2f * Mathf.Atan2(length, rotation.w) * Mathf.Rad2Deg / length) : Vector3.zero;
        }

        // Keep acceleration continuous when a target changes or a gesture is
        // cancelled. Full acceleration takes at least 25 ms to acquire; a reversal
        // takes twice that. Existing speed and anatomical limits still win.
        public static Vector3 SpringVelocity(Vector3 displacement, Vector3 velocity, ref Vector3 acceleration,
            float dt, float stiffness, float damping, float maxSpeed, float maxAcceleration)
        {
            if (dt <= 0) return velocity;
            var desired = Vector3.ClampMagnitude(displacement * stiffness - velocity * damping, maxAcceleration);
            acceleration = Vector3.MoveTowards(acceleration, desired, maxAcceleration * 40f * dt);
            return Vector3.ClampMagnitude(velocity + acceleration * dt, maxSpeed);
        }
        private static Quaternion DampRotation(Quaternion value, Quaternion target, ref Vector3 velocity, ref Vector3 acceleration,
            float dt, float smoothTime, float maxSpeed, float maxAcceleration, bool softenAcceleration)
        {
            if (dt <= 0) return value;
            // Integrate a critically damped angular spring in small steps. Both
            // velocity and acceleration stay bounded at 24/30/60/120 fps, including
            // cancelled gestures and arbitrarily distant next poses.
            var steps = Mathf.Max(1, Mathf.CeilToInt(dt * 120));
            var step = dt / steps;
            var omega = 2f / Mathf.Max(.03f, smoothTime);
            for (var i = 0; i < steps; i++)
            {
                var displacement = RotationDisplacement(target * Quaternion.Inverse(value));
                if (softenAcceleration)
                    velocity = SpringVelocity(displacement, velocity, ref acceleration, step, omega * omega, 2 * omega, maxSpeed, maxAcceleration);
                else
                {
                    acceleration = Vector3.ClampMagnitude(displacement * (omega * omega) - velocity * (2 * omega), maxAcceleration);
                    velocity = Vector3.ClampMagnitude(velocity + acceleration * step, maxSpeed);
                }
                var speed = velocity.magnitude;
                if (speed > .0001f) value = (Quaternion.AngleAxis(speed * step, velocity / speed) * value).normalized;
            }
            return value;
        }
    }
}
