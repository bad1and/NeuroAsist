using System.Collections;
using System.Collections.Generic;
using UniVRM10;
using UnityEngine;

namespace NeuroAsist.Avatar
{
    /// <summary>Low-energy breathing and persistent rest poses, below the director's gesture budget.</summary>
    [DefaultExecutionOrder(100)]
    public sealed class AvatarLifeController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private Vrm10Instance vrm;
        [SerializeField] private AvatarMotionController motion;
        [SerializeField] private AvatarStateController state;
        [SerializeField] private AvatarEmotionController emotionController;
        [Range(0f, 1.5f)] [SerializeField] private float intensity = 1f;
        private sealed class BoneOffset { public Transform Bone; public Quaternion Before, After; public bool Applied; }
        private readonly Dictionary<HumanBodyBones, BoneOffset> bones = new Dictionary<HumanBodyBones, BoneOffset>();
        private AvatarGestureController gestures;
        private float phase, breathRate = 1.1f, breathAmplitude = 1f, smoothedLife = 1f, lifeVelocity, restWeight = 1f;
        private float desiredBreathRate = 1.1f, desiredBreathAmplitude = 1f, breathRateVelocity, breathAmplitudeVelocity;
        private bool phaseInitialized;
        private Vector3 currentRest, desiredRest, restVelocity;
        private int previousRest = -1;
        private Coroutine blink;
        public int RestPose => previousRest;
        public float AutomaticBlinkWeight { get; private set; }

        public void Configure(Animator valueAnimator, Vrm10Instance valueVrm, AvatarMotionController valueMotion, AvatarStateController valueState, AvatarEmotionController valueEmotion = null)
        { animator = valueAnimator; vrm = valueVrm; motion = valueMotion; state = valueState; emotionController = valueEmotion; FindBones(); }
        private void Awake()
        {
            if (animator == null) animator = GetComponentInChildren<Animator>();
            if (vrm == null) vrm = GetComponentInChildren<Vrm10Instance>();
            if (motion == null) motion = GetComponent<AvatarMotionController>();
            if (state == null) state = GetComponent<AvatarStateController>();
            if (emotionController == null) emotionController = GetComponent<AvatarEmotionController>();
            gestures = GetComponent<AvatarGestureController>();
            FindBones();
        }
        private void FindBones()
        {
            if (animator == null || !animator.isHuman) return;
            RestoreOffsets(); bones.Clear();
            foreach (var bone in new[] { HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest,
                HumanBodyBones.LeftShoulder, HumanBodyBones.RightShoulder, HumanBodyBones.LeftUpperArm,
                HumanBodyBones.RightUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm })
            {
                var transform = animator.GetBoneTransform(bone);
                if (transform != null) bones[bone] = new BoneOffset { Bone = transform };
            }
        }
        private void OnEnable()
        {
            if (!phaseInitialized) { phase = Random.Range(0f, Mathf.PI * 2f); phaseInitialized = true; }
            blink = StartCoroutine(BlinkLoop());
        }
        private void OnDisable() { if (blink != null) StopCoroutine(blink); blink = null; SetBlink(0); RestoreOffsets(); }
        // Undo before Animator evaluation, including bones a sparse clip did not write.
        private void Update() => RestoreOffsets();
        internal void RestoreOffsets()
        {
            foreach (var entry in bones.Values)
            {
                if (entry.Applied && entry.Bone != null && Quaternion.Angle(entry.Bone.localRotation, entry.After) < .01f)
                    entry.Bone.localRotation = entry.Before;
                entry.Applied = false;
            }
        }
        public void ChangeRestPose()
        {
            var next = Random.Range(0, 5);
            if (next == previousRest) next = (next + 1) % 5;
            previousRest = next;
            var poses = new[] { new Vector3(0, 0, 0), new Vector3(.8f, -.6f, .4f),
                new Vector3(-.6f, .9f, -.35f), new Vector3(.4f, .6f, .25f), new Vector3(-.9f, -.3f, -.2f) };
            desiredRest = poses[next];
        }
        private void LateUpdate()
        {
            if (animator == null) return;
            var profile = motion != null ? motion.CurrentProfile : null;
            var life = intensity * (profile != null ? profile.LifeMotionIntensity : 1) * (motion != null ? motion.QuietActivity : 1);
            var gestureWeight = gestures != null ? gestures.GestureWeight : 0;
            life *= Mathf.Lerp(1, .65f, gestureWeight);
            smoothedLife = Mathf.SmoothDamp(smoothedLife, life, ref lifeVelocity, .7f);
            breathRate = Mathf.SmoothDamp(breathRate, desiredBreathRate, ref breathRateVelocity, .8f);
            breathAmplitude = Mathf.SmoothDamp(breathAmplitude, desiredBreathAmplitude, ref breathAmplitudeVelocity, .8f);
            phase += Time.deltaTime * breathRate;
            if (phase >= Mathf.PI * 2)
            { phase %= Mathf.PI * 2; desiredBreathRate = Random.Range(.98f, 1.25f); desiredBreathAmplitude = Random.Range(.9f, 1.08f); }
            var p = phase / (Mathf.PI * 2);
            var breath = (p < .42f ? Mathf.SmoothStep(-.5f, .5f, p / .42f) : Mathf.SmoothStep(.5f, -.5f, (p - .42f) / .58f)) * smoothedLife * breathAmplitude;
            currentRest = Vector3.SmoothDamp(currentRest, desiredRest, ref restVelocity, 1.6f);
            restWeight = Mathf.MoveTowards(restWeight, 1 - gestureWeight, Time.deltaTime * 3f);
            var rest = currentRest * restWeight;
            var torso = gestures?.ActiveVariant != null ? gestures.ActiveVariant.TorsoAccent * gestureWeight : Vector3.zero;
            // Torso accents are explicit tiny rotations; hips, root and feet are never touched.
            Apply(HumanBodyBones.Spine, new Vector3(.12f * breath, 0, rest.z * .25f) + torso * .25f);
            Apply(HumanBodyBones.Chest, new Vector3(.28f * breath, 0, rest.z * .45f) + torso * .5f);
            Apply(HumanBodyBones.UpperChest, new Vector3(.16f * breath, 0, 0) + torso * .25f);
            Apply(HumanBodyBones.LeftShoulder, new Vector3(.08f * breath, rest.x * .4f, rest.y * .45f));
            Apply(HumanBodyBones.RightShoulder, new Vector3(-.08f * breath, -rest.y * .4f, -rest.x * .45f));
            Apply(HumanBodyBones.LeftUpperArm, new Vector3(rest.x * 1.3f, 0, rest.y));
            Apply(HumanBodyBones.RightUpperArm, new Vector3(-rest.y, 0, -rest.x));
            Apply(HumanBodyBones.LeftLowerArm, new Vector3(0, rest.x * 1.2f, 0));
            Apply(HumanBodyBones.RightLowerArm, new Vector3(0, rest.y * 1.2f, 0));
        }
        private void Apply(HumanBodyBones bone, Vector3 euler)
        {
            if (!bones.TryGetValue(bone, out var entry) || entry.Bone == null) return;
            entry.Before = entry.Bone.localRotation;
            entry.After = entry.Before * Quaternion.Euler(euler);
            entry.Bone.localRotation = entry.After; entry.Applied = true;
        }
        private bool EyesOccupied()
        {
            var body = GetComponent<AvatarBodyController>();
            if (body != null && body.EyesControlled) return body.IsBlinking;
            if (emotionController == null) return false;
            return emotionController.GetWeight(ExpressionKey.Blink) > .2f
                || emotionController.GetWeight(ExpressionKey.BlinkLeft) > .1f || emotionController.GetWeight(ExpressionKey.BlinkRight) > .1f
                || emotionController.GetWeight(ExpressionKey.CreateCustom("EyeBlinkLeft")) > .1f
                || emotionController.GetWeight(ExpressionKey.CreateCustom("EyeBlinkRight")) > .1f;
        }
        private IEnumerator BlinkLoop()
        {
            while (true)
            {
                yield return new WaitForSeconds(Random.Range(2.7f, 6.2f));
                if (EyesOccupied()) continue;
                yield return BlinkOnce();
                if (Random.value < .10f) { yield return new WaitForSeconds(Random.Range(.12f, .22f)); if (!EyesOccupied()) yield return BlinkOnce(); }
            }
        }
        private IEnumerator BlinkOnce()
        {
            var close = Random.Range(.065f, .09f); var open = Random.Range(.12f, .17f);
            for (var t = 0f; t < close; t += Time.deltaTime) { if (EyesOccupied()) { SetBlink(0); yield break; } SetBlink(Mathf.SmoothStep(0, 1, t / close)); yield return null; }
            for (var t = 0f; t < open; t += Time.deltaTime) { SetBlink(Mathf.SmoothStep(1, 0, t / open)); yield return null; }
            SetBlink(0);
        }
        private void SetBlink(float value)
        {
            AutomaticBlinkWeight = Mathf.Clamp01(value);
            if (GetComponent<AvatarBodyController>()?.EyesControlled == true) return;
            if (vrm != null && vrm.Runtime != null)
                vrm.Runtime.Expression.SetWeight(ExpressionKey.Blink, Mathf.Max(Mathf.Clamp01(value), emotionController != null ? emotionController.GetWeight(ExpressionKey.Blink) : 0));
        }
    }
}
