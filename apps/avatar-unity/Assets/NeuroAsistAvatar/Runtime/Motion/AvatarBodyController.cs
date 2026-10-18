using System;
using System.Collections.Generic;
using System.Linq;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    // Model-owned channels. Runs before the final anatomical filter and arm solver.
    [DefaultExecutionOrder(200)]
    public sealed class AvatarBodyController : MonoBehaviour
    {
        public static readonly string[] BodyActions = {
            "raise_left_hand", "raise_right_hand", "raise_both_hands",
            "lower_left_hand", "lower_right_hand", "lower_both_hands",
            "extend_left_hand", "extend_right_hand", "extend_both_hands",
            "tilt_head_left", "tilt_head_right", "turn_head_left", "turn_head_right",
            "look_up", "look_down", "head_neutral",
            "blink_left", "blink_right", "blink", "close_left_eye", "close_right_eye",
            "close_eyes", "open_left_eye", "open_right_eye", "open_eyes", "body_neutral", "body_status"
        };
        public static readonly string[] Actions = BodyActions.Concat(Enum.GetValues(typeof(GestureTag)).Cast<GestureTag>()
            .Where(tag => tag != GestureTag.Auto && tag != GestureTag.None).Select(tag => tag.ToTransport())).ToArray();
        private Animator animator;
        private AvatarArmRig arms;
        private AvatarPoseFilter filter;
        private AvatarWebSocketClient client;
        private AvatarMotionController motion;
        private AvatarGestureController gestures;
        private AvatarLifeController life;
        private AvatarEmotionController expression;
        private GestureTag semantic = GestureTag.None;
        private bool semanticStarted, semanticFinished;
        private Vrm10Instance vrm;
        private Transform head, chest;
        private Quaternion facingInHead, facingInChest, headInput;
        private bool headApplied, ownsHead, releaseHeadWhenIdle;
        private Vector3 headTarget;
        private float leftTarget = -1, rightTarget = -1, leftWeight, rightWeight;
        private float blinkStarted = -1;
        private int blinkSide;
        private bool blinkPeaked, blinkWasOpen;
        private string pendingId, pendingAction;
        private float requestedAt, stableSince = -1;
        private readonly HashSet<ExpressionKey> eyeKeys = new HashSet<ExpressionKey>(ExpressionKey.Comparer);
        public bool EyesControlled => isActiveAndEnabled && (leftTarget >= 0 || rightTarget >= 0 || blinkStarted >= 0);
        public bool IsBlinking => blinkStarted >= 0;
        public bool HeadControlled => ownsHead;
        public Vector3 HeadTarget => headTarget;
        public float LeftEyeWeight => leftWeight;
        public float RightEyeWeight => rightWeight;
        public Vector3 MeasuredLeftHand { get; private set; }
        public Vector3 MeasuredRightHand { get; private set; }
        public float MeasuredLeftAbduction { get; private set; }
        public float MeasuredRightAbduction { get; private set; }
        public float MeasuredLeftEye { get; private set; }
        public float MeasuredRightEye { get; private set; }
        private Vector3 measuredHeadAngles;
        private string measuredLeftPose = "unavailable", measuredRightPose = "unavailable";
        public event Action<AvatarActionResultPayload> Completed;

        private void Awake()
        {
            animator = GetComponent<AvatarMotionController>()?.Animator ?? GetComponentInChildren<Animator>();
            if (animator == null) animator = FindFirstObjectByType<Animator>();
            arms = GetComponent<AvatarArmRig>(); filter = GetComponent<AvatarPoseFilter>();
            motion = GetComponent<AvatarMotionController>(); gestures = GetComponent<AvatarGestureController>();
            life = GetComponent<AvatarLifeController>(); expression = GetComponent<AvatarEmotionController>();
            if (gestures != null) { gestures.Started += OnGestureStarted; gestures.Finished += OnGestureFinished; gestures.Failed += OnGestureFailed; }
            gameObject.AddComponent<AvatarBodyResultProbe>().Body = this;
            client = GetComponent<AvatarWebSocketClient>();
            vrm = FindFirstObjectByType<Vrm10Instance>();
            if (animator == null || !animator.isHuman) return;
            head = animator.GetBoneTransform(HumanBodyBones.Head);
            chest = animator.GetBoneTransform(HumanBodyBones.UpperChest) ?? animator.GetBoneTransform(HumanBodyBones.Chest);
            var forward = Camera.main != null ? Camera.main.transform.position - head.position : animator.transform.forward;
            var facing = Quaternion.LookRotation(Vector3.ProjectOnPlane(forward, animator.transform.up).normalized, animator.transform.up);
            facingInHead = Quaternion.Inverse(head.rotation) * facing;
            facingInChest = Quaternion.Inverse(chest.rotation) * facing;
        }
        public bool CanExecute(string action)
        {
            if (Array.IndexOf(Actions, action) < 0 || head == null || arms == null || !isActiveAndEnabled || !animator.enabled) return false;
            var tag = AvatarMotionNames.ParseGesture(action);
            if (tag != GestureTag.Auto && tag != GestureTag.None) return motion != null && motion.CanPerformGesture(tag);
            if (IsEyeAction(action))
            {
                if (vrm == null || vrm.Runtime == null) return false;
                eyeKeys.Clear(); foreach (var key in vrm.Runtime.Expression.ExpressionKeys) eyeKeys.Add(key);
                return SupportsEye(true) && SupportsEye(false);
            }
            return true;
        }
        private bool SupportsEye(bool left) => eyeKeys.Contains(left ? ExpressionKey.BlinkLeft : ExpressionKey.BlinkRight)
            || eyeKeys.Contains(ExpressionKey.CreateCustom(left ? "EyeBlinkLeft" : "EyeBlinkRight"));
        private static bool IsEyeAction(string action) => action.Contains("eye") || action.StartsWith("blink");
        public bool Execute(string action, string requestId = null)
        {
            if (!CanExecute(action)) return false;
            if (pendingAction != null) { if (semantic != GestureTag.None) motion?.StopGesture(true); Report(false, "superseded"); }
            pendingId = requestId; pendingAction = action; requestedAt = Time.time; stableSince = -1;
            semantic = AvatarMotionNames.ParseGesture(action);
            if (semantic == GestureTag.Auto) semantic = GestureTag.None;
            semanticStarted = semanticFinished = false;
            if (semantic != GestureTag.None)
            {
                motion.TriggerGesture(semantic, 1, true, controlled: true);
            }
            else if (action == "body_status") { }
            else if (action == "body_neutral") ResetChannels();
            else if (action.Contains("hand"))
            {
                var pose = action.StartsWith("raise") ? 1 : action.StartsWith("extend") ? 2 : 0;
                if (!action.Contains("right")) arms.SetBodyPose(true, pose);
                if (!action.Contains("left")) arms.SetBodyPose(false, pose);
            }
            else if (IsEyeAction(action))
            {
                if (action.StartsWith("blink"))
                {
                    blinkSide = action == "blink_left" ? -1 : action == "blink_right" ? 1 : 0;
                    // A new blink replaces a held closure on its own channel.
                    // Open first, then measure a complete close/open cycle.
                    if (blinkSide <= 0) leftTarget = 0;
                    if (blinkSide >= 0) rightTarget = 0;
                    blinkStarted = Time.time; blinkPeaked = blinkWasOpen = false;
                }
                else
                {
                    var close = action.StartsWith("close") ? 1f : 0f;
                    if (!action.Contains("right")) leftTarget = close;
                    if (!action.Contains("left")) rightTarget = close;
                }
            }
            else
            {
                ownsHead = true;
                releaseHeadWhenIdle = false;
                // Anatomical left/right belong to Iris, independent of the viewer.
                if (action.StartsWith("tilt")) headTarget.z = action.EndsWith("left") ? 10 : -10;
                if (action.StartsWith("turn")) headTarget.y = action.EndsWith("left") ? -24 : 24;
                if (action == "look_up") headTarget.x = -12;
                if (action == "look_down") headTarget.x = 18;
                if (action == "head_neutral") headTarget = Vector3.zero;
                headTarget = AvatarPoseFilter.AnatomicalAngles(AvatarPoseFilter.LimitAnatomical(Quaternion.Euler(headTarget), 28, 14, 22, 11));
            }
            return true;
        }
        private void OnGestureStarted(GestureDefinition definition)
        {
            if (semantic == GestureTag.None || AvatarMotionNames.BaseGesture(semantic) != AvatarMotionNames.BaseGesture(definition.Tag)) return;
            var side = gestures.ActiveVariant != null ? gestures.ActiveVariant.Side : GestureSide.Either;
            if (AvatarMotionNames.IsExplicitLeftHand(semantic) && side != GestureSide.Left) return;
            if (AvatarMotionNames.IsExplicitRightHand(semantic) && side != GestureSide.Right) return;
            var channels = gestures.ActiveVariant != null ? gestures.ActiveVariant.Channels : MotionChannels.BothArms;
            if ((channels & MotionChannels.LeftArm) != 0 && !AvatarMotionNames.IsExplicitRightHand(semantic)) arms.SetBodyPose(true, -1);
            if ((channels & MotionChannels.RightArm) != 0 && !AvatarMotionNames.IsExplicitLeftHand(semantic)) arms.SetBodyPose(false, -1);
            if ((channels & MotionChannels.Head) != 0) { ownsHead = false; releaseHeadWhenIdle = false; }
            semanticStarted = true;
        }
        private void OnGestureFinished(GestureDefinition definition)
        {
            if (!semanticStarted || AvatarMotionNames.BaseGesture(semantic) != AvatarMotionNames.BaseGesture(definition.Tag)) return;
            if (gestures.WasInterrupted) Report(false, "animation_cancelled"); else semanticFinished = true;
        }
        private void OnGestureFailed(GestureDefinition definition, string reason)
        { if (semantic != GestureTag.None && AvatarMotionNames.BaseGesture(semantic) == AvatarMotionNames.BaseGesture(definition.Tag)) Report(false, "animation_failed"); }
        public void ResetBody(string reason = "cancelled")
        {
            if (pendingAction != null) Report(false, reason);
            ResetChannels();
            pendingAction = "body_neutral"; pendingId = null; requestedAt = Time.time; stableSince = -1;
        }
        private void ResetChannels()
        {
            if (vrm != null && vrm.Runtime != null)
                foreach (var key in vrm.Runtime.Expression.ExpressionKeys) eyeKeys.Add(key);
            arms?.SetBodyPose(true, 0); arms?.SetBodyPose(false, 0);
            ownsHead = true; releaseHeadWhenIdle = false; headTarget = Vector3.zero;
            leftTarget = rightTarget = 0; blinkStarted = -1;
            expression?.SetEmotion("neutral", 1);
        }
        internal void RestoreInput() { if (headApplied && head != null) head.localRotation = headInput; headApplied = false; }
        private void LateUpdate()
        {
            if (head == null || !animator.enabled) return;
            if (releaseHeadWhenIdle && (gestures?.ActiveVariant == null || (gestures.ActiveVariant.Channels & MotionChannels.Head) == 0))
            { releaseHeadWhenIdle = false; ownsHead = false; }
            if (ownsHead)
            {
                headInput = head.localRotation;
                head.rotation = chest.rotation * facingInChest * Quaternion.Euler(headTarget) * Quaternion.Inverse(facingInHead);
                headApplied = true;
            }
            if (EyesControlled)
            {
                var blink = 0f;
                if (blinkStarted >= 0)
                {
                    var t = Time.time - blinkStarted;
                    blink = t < .08f ? 0 : t < .18f ? Mathf.SmoothStep(0, 1, (t - .08f) / .10f)
                        : t < .32f ? 1 : Mathf.SmoothStep(1, 0, (t - .32f) / .20f);
                    if (t >= .52f) { blinkStarted = -1; blink = 0; }
                }
                var automatic = IsBlinking ? 0 : life != null ? life.AutomaticBlinkWeight : 0;
                var leftBase = leftTarget >= 0 ? leftTarget : IntendedEye(true);
                var rightBase = rightTarget >= 0 ? rightTarget : IntendedEye(false);
                leftWeight = Mathf.MoveTowards(leftWeight, Mathf.Max(leftBase, Mathf.Max(automatic, blinkSide <= 0 ? blink : 0)), Time.deltaTime * 14);
                rightWeight = Mathf.MoveTowards(rightWeight, Mathf.Max(rightBase, Mathf.Max(automatic, blinkSide >= 0 ? blink : 0)), Time.deltaTime * 14);
                ApplyEyes(leftWeight, rightWeight);
            }
        }
        // The probe runs after the constrained solver, including in batch mode.
        internal void SampleResult()
        {
            if (arms == null) return;
            MeasuredLeftHand = arms.MeasureHandPosition(true); MeasuredRightHand = arms.MeasureHandPosition(false);
            MeasuredLeftAbduction = arms.MeasureArmAbduction(true); MeasuredRightAbduction = arms.MeasureArmAbduction(false);
            measuredLeftPose = arms.BodyPoseName(true); measuredRightPose = arms.BodyPoseName(false);
            measuredHeadAngles = filter != null ? filter.MeasureHeadAngles() : Vector3.zero;
            MeasuredLeftEye = ActualEye(true); MeasuredRightEye = ActualEye(false);
            if (blinkStarted >= 0 && !blinkPeaked && (blinkSide > 0 || MeasuredLeftEye < .2f) && (blinkSide < 0 || MeasuredRightEye < .2f)) blinkWasOpen = true;
            if (blinkStarted >= 0 && (blinkSide > 0 || MeasuredLeftEye > .9f) && (blinkSide < 0 || MeasuredRightEye > .9f)) blinkPeaked = true;
            if (pendingAction == null) return;
            var reached = semantic != GestureTag.None ? semanticStarted && semanticFinished : Reached(pendingAction);
            if (!reached) stableSince = -1;
            else if (stableSince < 0) stableSince = Time.time;
            if (reached && Time.time - stableSince >= .12f) Report(true, null);
            else if (Time.time - requestedAt > (semantic != GestureTag.None ? 16 : 8)) Report(false, semantic != GestureTag.None ? "animation_not_completed" : "pose_not_reached");
        }
        private bool Reached(string action)
        {
            if (action == "body_status") return true;
            if (action.Contains("hand"))
                return (action.Contains("right") || arms.BodyPoseReached(true)) && (action.Contains("left") || arms.BodyPoseReached(false));
            if (IsEyeAction(action))
            {
                if (action.StartsWith("blink")) return blinkWasOpen && blinkPeaked && blinkStarted < 0
                    && (blinkSide > 0 || MeasuredLeftEye < .05f) && (blinkSide < 0 || MeasuredRightEye < .05f);
                return (action.Contains("right") || Mathf.Abs(MeasuredLeftEye - Mathf.Max(0, leftTarget)) < .05f)
                    && (action.Contains("left") || Mathf.Abs(MeasuredRightEye - Mathf.Max(0, rightTarget)) < .05f);
            }
            var headReady = Quaternion.Angle(Quaternion.Euler(measuredHeadAngles), Quaternion.Euler(headTarget)) < 3;
            return action == "body_neutral" ? headReady && arms.BodyPoseReached(true) && arms.BodyPoseReached(false) && MeasuredLeftEye < .05f && MeasuredRightEye < .05f : headReady;
        }
        private void Report(bool reached, string reason)
        {
            var result = new AvatarActionResultPayload { reply_to = pendingId, action = pendingAction, reached = reached, reason = reason,
                left_hand = measuredLeftPose, right_hand = measuredRightPose,
                left_hand_y = MeasuredLeftHand.y, right_hand_y = MeasuredRightHand.y,
                head_pitch = measuredHeadAngles.x, head_yaw = measuredHeadAngles.y, head_roll = measuredHeadAngles.z,
                left_eye = MeasuredLeftEye, right_eye = MeasuredRightEye };
            var completed = pendingAction; pendingAction = pendingId = null; semantic = GestureTag.None;
            if (completed == "head_neutral" || completed == "body_neutral") releaseHeadWhenIdle = true;
            if (completed == "body_neutral") leftTarget = rightTarget = -1;
            if (reached) arms?.ReleaseLoweredBodyPoses();
            if (client != null && client.isActiveAndEnabled) client.Send("avatar.action.result", result);
            Completed?.Invoke(result);
        }
        private void ApplyEyes(float left, float right)
        {
            if (vrm == null || vrm.Runtime == null) return;
            vrm.Runtime.Expression.SetWeight(ExpressionKey.Blink, 0);
            foreach (var key in new[] { ExpressionKey.BlinkLeft, ExpressionKey.CreateCustom("EyeBlinkLeft") })
                if (eyeKeys.Contains(key)) vrm.Runtime.Expression.SetWeight(key, left);
            foreach (var key in new[] { ExpressionKey.BlinkRight, ExpressionKey.CreateCustom("EyeBlinkRight") })
                if (eyeKeys.Contains(key)) vrm.Runtime.Expression.SetWeight(key, right);
        }
        private float ActualEye(bool left)
        {
            if (vrm == null || vrm.Runtime == null) return 0;
            var weights = vrm.Runtime.Expression.ActualWeights;
            var value = weights.TryGetValue(ExpressionKey.Blink, out var both) ? both : 0;
            foreach (var key in new[] { left ? ExpressionKey.BlinkLeft : ExpressionKey.BlinkRight,
                ExpressionKey.CreateCustom(left ? "EyeBlinkLeft" : "EyeBlinkRight") })
                if (weights.TryGetValue(key, out var weight)) value = Mathf.Max(value, weight);
            return value;
        }
        private float IntendedEye(bool left)
        {
            if (expression == null) return 0;
            return Mathf.Max(expression.GetWeight(ExpressionKey.Blink),
                Mathf.Max(expression.GetWeight(left ? ExpressionKey.BlinkLeft : ExpressionKey.BlinkRight),
                expression.GetWeight(ExpressionKey.CreateCustom(left ? "EyeBlinkLeft" : "EyeBlinkRight"))));
        }
        private void OnDisable() { RestoreInput(); if (pendingAction != null) Report(false, "disabled"); ApplyEyes(0, 0); }
    }
    [DefaultExecutionOrder(12000)]
    public sealed class AvatarBodyResultProbe : MonoBehaviour
    {
        internal AvatarBodyController Body;
        private void LateUpdate() => Body?.SampleResult();
    }
}
