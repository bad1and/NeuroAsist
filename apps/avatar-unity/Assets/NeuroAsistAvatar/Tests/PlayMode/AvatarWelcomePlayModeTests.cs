using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using UniVRM10;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarWelcomePlayModeTests
    {
        private static void Offline(Scene scene, LoadSceneMode mode)
        {
            foreach (var ws in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
        }

        [UnitySetUp] public IEnumerator Load()
        {
            SceneManager.sceneLoaded += Offline;
            SceneManager.LoadScene("AvatarOverlay");
            yield return null;
            SceneManager.sceneLoaded -= Offline;
            yield return new WaitForSeconds(.6f);
        }

        [UnityTest] public IEnumerator SeatedClipLoopsWithoutRootDriftAndRestoresConversationRig()
        {
            var welcome = Object.FindFirstObjectByType<AvatarWelcomeController>();
            var motion = Object.FindFirstObjectByType<AvatarMotionController>();
            var arms = Object.FindFirstObjectByType<AvatarArmRig>();
            var life = Object.FindFirstObjectByType<AvatarLifeController>();
            var animator = motion.Animator;
            var original = animator.runtimeAnimatorController;
            var vrm = animator.GetComponent<Vrm10Instance>();
            var originalColliderCount = vrm.SpringBone.ColliderGroups.Count;
            var originalColliderComponents = animator.GetComponentsInChildren<VRM10SpringBoneCollider>().Length;
            var clothParents = new Dictionary<Transform, Transform>();
            var clothPositions = new Dictionary<Transform, Vector3>();
            var clothSettings = new Dictionary<VRM10SpringBoneJoint, Vector3>();
            foreach(var spring in vrm.SpringBone.Springs)
                if(spring.Name == "Skirt")
                    foreach(var joint in spring.Joints)
                    { clothParents[joint.transform] = joint.transform.parent; clothPositions[joint.transform] = joint.transform.localPosition;
                      clothSettings[joint] = new Vector3(joint.m_stiffnessForce,joint.m_gravityPower,joint.m_dragForce); }
            var legProbe = welcome.gameObject.AddComponent<AvatarWelcomeLegProbe>();
            legProbe.Configure(animator, welcome);
            var root = animator.transform.localPosition;
            var face = animator.GetComponentInChildren<SkinnedMeshRenderer>();
            var originalOffscreen = face.updateWhenOffscreen;
            Assert.That(welcome, Is.Not.Null);
            Assert.That(welcome.SittingIdle, Is.Not.Null, "Import the selected Mixamo source clip first.");
            life.enabled = false;
            Assert.That(welcome.SetPresentation("welcome_seated", true), Is.True);
            var seatedController = animator.runtimeAnimatorController;
            Assert.That(welcome.SetPresentation("welcome_seated", true), Is.True);
            Assert.That(animator.runtimeAnimatorController, Is.SameAs(seatedController));
            Assert.That(arms.enabled, Is.False);
            Assert.That(GameObject.Find("Welcome graphite stool"), Is.Null);
            Assert.That(vrm.SpringBone.ColliderGroups.Count, Is.EqualTo(originalColliderCount + 1));
            Assert.That(GameObject.Find("Welcome floor support"), Is.Not.Null);
            Assert.That(face.updateWhenOffscreen, Is.True);
            Assert.That(welcome.SittingIdle.length, Is.InRange(10.8f, 10.9f), "Use the supplied floor-sitting clip.");
            Assert.That(motion.enabled, Is.False);
            Assert.That(motion.CanPerformGesture(GestureTag.Greeting), Is.False);
            for (var time = 0f; time < welcome.SittingIdle.length + 1; time += .5f)
            {
                yield return new WaitForSeconds(.5f);
                Assert.That(Vector3.Distance(root, animator.transform.localPosition), Is.LessThan(.001f));
                foreach (var bone in new[] { HumanBodyBones.Head, HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot })
                {
                    var point = Camera.main.WorldToViewportPoint(animator.GetBoneTransform(bone).position);
                    Assert.That(point.x, Is.InRange(.02f, .98f), bone.ToString());
                    Assert.That(point.y, Is.InRange(.02f, .98f), bone.ToString());
                }
            }
            Assert.That(legProbe.Samples, Is.GreaterThan(10));
            Assert.That(legProbe.MaxFootBend, Is.LessThan(48.1f), "The rendered feet must stay inside the neutral-relative bend budget.");
            Assert.That(legProbe.MaxContactError, Is.LessThan(.001f), "The knee correction must keep both ankle contacts fixed.");
            Assert.That(legProbe.MaxLengthError, Is.LessThan(.001f), "Retargeting must preserve both leg segment lengths.");
            Assert.That(welcome.SetPresentation("portrait", true), Is.True);
            yield return new WaitForSeconds(.8f);
            Assert.That(animator.runtimeAnimatorController, Is.SameAs(original));
            Assert.That(arms.enabled, Is.True);
            Assert.That(motion.enabled, Is.True);
            Assert.That(life.enabled, Is.False, "Restore each component's original enabled state.");
            Assert.That(Vector3.Distance(root, animator.transform.localPosition), Is.LessThan(.001f));
            Assert.That(welcome.IsSeated, Is.False);
            Assert.That(face.updateWhenOffscreen, Is.EqualTo(originalOffscreen));
            Assert.That(vrm.SpringBone.ColliderGroups.Count, Is.EqualTo(originalColliderCount));
            Assert.That(GameObject.Find("Welcome floor support"), Is.Null);
            Assert.That(animator.GetComponentsInChildren<VRM10SpringBoneCollider>().Length, Is.EqualTo(originalColliderComponents));
            foreach(var item in clothParents) Assert.That(item.Key.parent, Is.SameAs(item.Value), item.Key.name);
            foreach(var item in clothPositions) Assert.That(Vector3.Distance(item.Key.localPosition,item.Value), Is.LessThan(.00001f), item.Key.name);
            foreach(var item in clothSettings)
                Assert.That(new Vector3(item.Key.m_stiffnessForce,item.Key.m_gravityPower,item.Key.m_dragForce), Is.EqualTo(item.Value));
            var body = Object.FindFirstObjectByType<AvatarBodyController>();
            AvatarActionResultPayload measured = null;
            body.Completed += result => { if (result.reply_to == "after-welcome") measured = result; };
            Assert.That(body.Execute("raise_right_hand", "after-welcome"), Is.True);
            var deadline = Time.time + 10;
            while (measured == null && Time.time < deadline) yield return null;
            Assert.That(measured, Is.Not.Null, "The restored body rig must report a measured action.");
            Assert.That(measured.reached, Is.True, measured.reason);
        }

        [UnityTest] public IEnumerator FullBodyRemainsInsideTheFrameAtDifferentHostAspects()
        {
            var welcome = Object.FindFirstObjectByType<AvatarWelcomeController>();
            var presentation = Object.FindFirstObjectByType<AvatarPresentationController>();
            Assert.That(welcome.SetPresentation("welcome_seated", true), Is.True);
            yield return new WaitForSeconds(1f);
            foreach (var aspect in new[] { .55f, .97f, 1.4f })
            {
                Camera.main.aspect = aspect;
                presentation.FrameNow();
                var bottom = 1f;
                foreach (var vertex in welcome.VisiblePoints)
                {
                    var point = Camera.main.WorldToViewportPoint(vertex);
                    Assert.That(point.x, Is.InRange(0f, 1f), "Horizontal crop at " + aspect);
                    Assert.That(point.y, Is.InRange(0f, 1f), "Vertical crop at " + aspect);
                    bottom = Mathf.Min(bottom, point.y);
                }
                Assert.That(bottom, Is.InRange(.004f, .006f), "The silhouette rests on the button plane at " + aspect);
            }
            welcome.SetPresentation("portrait", true);
        }
    }
    [DefaultExecutionOrder(12500)]
    public sealed class AvatarWelcomeLegProbe : MonoBehaviour
    {
        private Animator animator;
        private AvatarWelcomeController welcome;
        private AvatarWelcomeLegInputProbe input;
        private readonly Dictionary<Transform, Quaternion> feet = new Dictionary<Transform, Quaternion>();
        private readonly List<(Transform from, Transform to, float length)> segments = new List<(Transform, Transform, float)>();
        public int Samples { get; private set; }
        public float MaxFootBend { get; private set; }
        public float MaxLengthError { get; private set; }
        public float MaxContactError { get; private set; }
        public void Configure(Animator value, AvatarWelcomeController controller)
        {
            animator = value; welcome = controller;
            input = gameObject.AddComponent<AvatarWelcomeLegInputProbe>(); input.Configure(value, controller);
            foreach(var side in new[] { true, false })
            {
                var hip = animator.GetBoneTransform(side ? HumanBodyBones.LeftUpperLeg : HumanBodyBones.RightUpperLeg);
                var knee = animator.GetBoneTransform(side ? HumanBodyBones.LeftLowerLeg : HumanBodyBones.RightLowerLeg);
                var foot = animator.GetBoneTransform(side ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot);
                feet[foot] = foot.localRotation;
                segments.Add((hip,knee,Vector3.Distance(hip.position,knee.position)));
                segments.Add((knee,foot,Vector3.Distance(knee.position,foot.position)));
            }
        }
        private void LateUpdate()
        {
            if(welcome == null || !welcome.IsSeated) return;
            Samples++;
            MaxContactError = Mathf.Max(MaxContactError,Vector3.Distance(animator.GetBoneTransform(HumanBodyBones.LeftFoot).position,input.Left),Vector3.Distance(animator.GetBoneTransform(HumanBodyBones.RightFoot).position,input.Right));
            foreach(var item in feet) MaxFootBend = Mathf.Max(MaxFootBend,Quaternion.Angle(item.Value,item.Key.localRotation));
            foreach(var segment in segments) MaxLengthError = Mathf.Max(MaxLengthError,Mathf.Abs(Vector3.Distance(segment.from.position,segment.to.position)-segment.length));
        }
    }

    [DefaultExecutionOrder(10400)]
    public sealed class AvatarWelcomeLegInputProbe : MonoBehaviour
    {
        private Animator animator; private AvatarWelcomeController welcome;
        public Vector3 Left { get; private set; }
        public Vector3 Right { get; private set; }
        public void Configure(Animator value, AvatarWelcomeController controller) { animator = value; welcome = controller; }
        private void LateUpdate()
        {
            if(welcome == null || !welcome.IsSeated) return;
            Left = animator.GetBoneTransform(HumanBodyBones.LeftFoot).position;
            Right = animator.GetBoneTransform(HumanBodyBones.RightFoot).position;
        }
    }

}
