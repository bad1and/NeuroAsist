using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    /// <summary>Rendered comparisons on the actual Iris rig; never edits source motion curves.</summary>
    [InitializeOnLoad]
    public static class AvatarWelcomeAudition
    {
        private const string Key = "Iris.WelcomeAudition";
        public static string[] Paths
        {
            get
            {
                var paths = new List<string>();
                var args = Environment.GetCommandLineArgs();
                for (var i = 0; i + 1 < args.Length; i++)
                    if (args[i] == "-welcomeCandidate") paths.Add(args[i + 1]);
                return paths.Count > 0 ? paths.ToArray() : new[] { AvatarWelcomeSetup.ClipPath };
            }
        }
        static AvatarWelcomeAudition() { EditorApplication.playModeStateChanged += Changed; }

        public static void Capture()
        {
            foreach (var path in Paths) AvatarWelcomeSetup.ImportClip(path);
            AvatarRuntimeSetup.Setup();
            SessionState.SetBool(Key, true);
            EditorSceneManager.OpenScene("Assets/Scenes/AvatarOverlay.unity");
            EditorApplication.EnterPlaymode();
        }

        private static void Changed(PlayModeStateChange change)
        {
            if (!SessionState.GetBool(Key, false)) return;
            if (change == PlayModeStateChange.EnteredPlayMode)
            {
                foreach (var ws in UnityEngine.Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
                foreach (var overlay in UnityEngine.Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
                new GameObject("Welcome audition").AddComponent<AvatarWelcomeAuditionRunner>();
            }
            if (change == PlayModeStateChange.EnteredEditMode)
            {
                SessionState.EraseBool(Key);
                EditorApplication.Exit(SessionState.GetBool(Key + ".Success", false) ? 0 : 1);
            }
        }
        public static void Complete(bool success)
        { SessionState.SetBool(Key + ".Success", success); EditorApplication.ExitPlaymode(); }
    }

    [DefaultExecutionOrder(13000)]
    public sealed class AvatarWelcomeAuditionRunner : MonoBehaviour
    {
        private Action lateCapture;
        private void LateUpdate() { var capture = lateCapture; lateCapture = null; capture?.Invoke(); }
        private IEnumerator CaptureAfterRig(Action capture)
        {
            var completed = false;
            lateCapture = () => { capture(); completed = true; };
            yield return new WaitUntil(() => completed);
        }
        private IEnumerator Start()
        {
            var args = Environment.GetCommandLineArgs();
            var output = Path.GetFullPath("../../output/avatar-floor-welcome-20261022/audition");
            for (var n = 0; n + 1 < args.Length; n++) if (args[n] == "-welcomeOutput") output = Path.GetFullPath(args[n + 1]);
            Directory.CreateDirectory(output);
            var welcome = FindFirstObjectByType<AvatarWelcomeController>();
            var presentation = FindFirstObjectByType<AvatarPresentationController>();
            var animator = FindFirstObjectByType<AvatarMotionController>().Animator;
            var camera = Camera.main;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.clear;
            camera.aspect = 500f / 540;
            yield return new WaitForSeconds(.5f);
            using (var measurements = new StreamWriter(Path.Combine(output, "poses.csv")))
            {
                measurements.WriteLine("candidate,clip_seconds,stool,hips_y,left_foot_y,right_foot_y,knee_angle_left,hips_camera_x,head_camera_y,foot_camera_y");
                for (var i = 0; i < AvatarWelcomeAudition.Paths.Length; i++)
                {
                    var clip = Load(AvatarWelcomeAudition.Paths[i]);
                    if (clip == null) continue;
                    welcome.Configure(animator, presentation, clip, false);
                    if (!welcome.SetPresentation("welcome_seated", true)) throw new InvalidOperationException("Could not play candidate " + i);
                    yield return new WaitForSeconds(.4f);
                    var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
                    var footL = animator.GetBoneTransform(HumanBodyBones.LeftFoot);
                    var footR = animator.GetBoneTransform(HumanBodyBones.RightFoot);
                    var seatedHeight = hips.position.y - Mathf.Min(footL.position.y, footR.position.y);
                    var stool = Array.IndexOf(Environment.GetCommandLineArgs(), "-welcomeStool") >= 0;
                    welcome.SetPresentation("portrait", true);
                    welcome.Configure(animator, presentation, clip, stool);
                    welcome.SetPresentation("welcome_seated", true);
                    var knee = animator.GetBoneTransform(HumanBodyBones.LeftLowerLeg);
                    var thigh = animator.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
                    var head = animator.GetBoneTransform(HumanBodyBones.Head);
                    var sampleTimes = new[] { 1f, 3f, 5f, 8f, 11f, 12.5f };
                    for (var sample = 0; sample < sampleTimes.Length; sample++)
                    {
                        yield return new WaitForSeconds(sampleTimes[sample] - (sample == 0 ? 0 : sampleTimes[sample - 1]));
                        var kneeAngle = Vector3.Angle(thigh.position - knee.position, footL.position - knee.position);
                        var headView = camera.WorldToViewportPoint(head.position);
                        var footView = camera.WorldToViewportPoint(footL.position);
                        measurements.WriteLine(string.Join(",", i + 1, clip.length.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), stool,
                            hips.position.y.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), footL.position.y.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), footR.position.y.ToString("F3", System.Globalization.CultureInfo.InvariantCulture),
                            kneeAngle.ToString("F2", System.Globalization.CultureInfo.InvariantCulture), camera.WorldToViewportPoint(hips.position).x.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), headView.y.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), footView.y.ToString("F3", System.Globalization.CultureInfo.InvariantCulture)));
                        yield return CaptureAfterRig(() =>
                        {
                        if (sample == 0)
                        {
                            var report = new System.Text.StringBuilder();
                            using (var handler = new HumanPoseHandler(animator.avatar, animator.transform))
                            {
                                var pose = new HumanPose(); handler.GetHumanPose(ref pose);
                                for (var m = 0; m < HumanTrait.MuscleCount; m++) if (HumanTrait.MuscleName[m].Contains("Leg") || HumanTrait.MuscleName[m].Contains("Foot")) report.AppendLine(HumanTrait.MuscleName[m] + ": " + pose.muscles[m]);
                            }
                            var vrm = animator.GetComponent<UniVRM10.Vrm10Instance>();
                            foreach (var spring in vrm.SpringBone.Springs)
                            { report.AppendLine("SPRING " + spring.Name); foreach(var joint in spring.Joints) report.AppendLine("  " + joint.name + " at " + joint.transform.position + " rotation " + joint.transform.localEulerAngles + " gravity " + joint.m_gravityPower + " stiffness " + joint.m_stiffnessForce); }
                            for (var bone = HumanBodyBones.Hips; bone < HumanBodyBones.LastBone; bone++)
                            { var tf = animator.GetBoneTransform(bone); if(tf!=null) report.AppendLine("BONE " + bone + " " + tf.name + " pos " + tf.position + " rot " + tf.localEulerAngles); }
                            File.WriteAllText(Path.Combine(output,"rig-" + i + ".txt"), report.ToString());
                        }
                            SaveFrame(camera, Path.Combine(output, "candidate-" + (i + 1) + "-" + sample + ".png"));
                        });

                    }
                    welcome.SetPresentation("portrait", true);
                    yield return new WaitForSeconds(.4f);
                }
            }
            AvatarWelcomeAudition.Complete(true);
        }

        private static AnimationClip Load(string path)
        {
            foreach (var item in AssetDatabase.LoadAllAssetsAtPath(path))
                if (item is AnimationClip clip && !clip.name.StartsWith("__preview__")) return clip;
            return null;
        }

        public static void SaveFrame(Camera camera, string path)
        {
            var texture = new RenderTexture(500, 540, 24, RenderTextureFormat.ARGB32);
            var pixels = new Texture2D(500, 540, TextureFormat.RGBA32, false);
            var previous = camera.targetTexture;
            var active = RenderTexture.active;
            camera.targetTexture = texture;
            camera.Render();
            RenderTexture.active = texture;
            pixels.ReadPixels(new Rect(0, 0, 500, 540), 0, 0);
            pixels.Apply();
            File.WriteAllBytes(path, pixels.EncodeToPNG());
            camera.targetTexture = previous;
            RenderTexture.active = active;
            Destroy(texture); Destroy(pixels);
        }
    }
}
