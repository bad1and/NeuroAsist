using System;
using System.Collections;
using System.IO;
using System.Linq;
using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    /// <summary>Repeatable rendered evidence using the real runtime, without a backend or microphone.</summary>
    [InitializeOnLoad]
    public static class AvatarMotionCapture
    {
        private const string Key = "Iris.MotionCapture";
        static AvatarMotionCapture() { EditorApplication.playModeStateChanged += Changed; }
        public static void PrepareCatalogue()
        {
            AvatarGestureLibrary.PackGeneratedClips();
            AvatarRuntimeSetup.Setup();
            AvatarMotionValidator.Validate();
            Capture();
        }
        public static void RebuildAndCapture()
        {
            AvatarGestureLibrary.RebuildGeneratedClips();
            PrepareCatalogue();
        }
        public static void Capture()
        {
            var args = Environment.GetCommandLineArgs();
            var output = Path.GetFullPath("../../output/avatar-behavior-20261016/before.mp4");
            var mode = "scenario";
            for (var i = 0; i + 1 < args.Length; i++)
                if (args[i] == "-captureOutput") output = Path.GetFullPath(args[i + 1]);
            for (var i = 0; i + 1 < args.Length; i++) if (args[i] == "-captureMode") mode = args[i + 1];
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            SessionState.SetString(Key, output);
            SessionState.SetString(Key + ".Mode", mode);
            EditorSceneManager.OpenScene("Assets/Scenes/AvatarOverlay.unity");
            EditorApplication.EnterPlaymode();
        }
        private static void Changed(PlayModeStateChange change)
        {
            var output = SessionState.GetString(Key, "");
            if (string.IsNullOrEmpty(output)) return;
            if (change == PlayModeStateChange.EnteredPlayMode)
            {
                foreach (var ws in UnityEngine.Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled = false;
                foreach (var overlay in UnityEngine.Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled = false;
                var runner = new GameObject("Motion evidence capture").AddComponent<AvatarMotionCaptureRunner>();
                runner.Output = output;
                runner.Mode = SessionState.GetString(Key + ".Mode", "scenario");
            }
            if (change == PlayModeStateChange.EnteredEditMode)
            {
                SessionState.EraseString(Key);
                EditorApplication.Exit(File.Exists(output) ? 0 : 1);
            }
        }
    }

    [DefaultExecutionOrder(20000)]
    public sealed class AvatarMotionCaptureRunner : MonoBehaviour
    {
        public string Output;
        public string Mode;
        private System.Diagnostics.Process encoder;
        private RenderTexture target;
        private Texture2D pixels;
        private Camera cameraToCapture;
        private Camera referenceCamera;
        private RenderTexture referenceTarget;
        private string caption = "Idle";
        private UnityEngine.UI.Text label;
        private bool frameRequested;
        private StreamWriter kinematics;
        private Animator sampledAnimator;
        private AvatarContactController sampledContact;
        private AvatarGestureController sampledGestures;
        private StreamWriter contacts;
        private StreamWriter armMeasurements;
        private AvatarArmRig sampledArms;
        private StreamWriter posture;
        private AvatarPoseFilter sampledPose;
        private string lastSkeleton;
        private readonly System.Collections.Generic.Dictionary<HumanBodyBones, Quaternion> previousRotations = new System.Collections.Generic.Dictionary<HumanBodyBones, Quaternion>();
        private void LateUpdate()
        {
            if (!frameRequested || encoder == null || encoder.HasExited) return;
            frameRequested = false;
            RenderFrame();
            if (Mode == "posture") lastSkeleton = sampledArms.DescribeArms();
            var headAngles = sampledPose.MeasureHeadAngles();
            posture.WriteLine(string.Join(",",caption,Time.time.ToString("F4",System.Globalization.CultureInfo.InvariantCulture),
                headAngles.x.ToString("F3",System.Globalization.CultureInfo.InvariantCulture),headAngles.y.ToString("F3",System.Globalization.CultureInfo.InvariantCulture),headAngles.z.ToString("F3",System.Globalization.CultureInfo.InvariantCulture),
                sampledArms.MeasureArmAbduction(true).ToString("F3",System.Globalization.CultureInfo.InvariantCulture),sampledArms.MeasureArmAbduction(false).ToString("F3",System.Globalization.CultureInfo.InvariantCulture)));
            if (sampledArms != null)
                foreach (var left in new[] { true, false }) armMeasurements.WriteLine(caption + "," + Time.time.ToString("F4", System.Globalization.CultureInfo.InvariantCulture) + "," + left + "," + sampledArms.Diagnostic(left));
            if (sampledContact.ContactWeight > .01f && sampledGestures.ActiveVariant != null)
            {
                var left = sampledGestures.ActiveVariant.Side == GestureSide.Left;
                var wrist = sampledAnimator.GetBoneTransform(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                var finger = sampledAnimator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                var eyes = (sampledAnimator.GetBoneTransform(HumanBodyBones.LeftEye).position + sampledAnimator.GetBoneTransform(HumanBodyBones.RightEye).position) * .5f;
                var front = Vector3.ProjectOnPlane(referenceCamera.transform.position - eyes, sampledAnimator.transform.up).normalized;
                var palm = Vector3.Lerp(wrist.position, finger.position, .55f);
                contacts.WriteLine(string.Join(",", caption, Time.time.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), sampledContact.ContactWeight.ToString("F3", System.Globalization.CultureInfo.InvariantCulture),
                    Vector3.Distance(sampledContact.PalmPosition, sampledContact.PalmTarget).ToString("F4", System.Globalization.CultureInfo.InvariantCulture),
                    Vector3.Distance(palm, sampledContact.PalmTarget).ToString("F4", System.Globalization.CultureInfo.InvariantCulture),
                    Vector3.Dot(palm - eyes, front).ToString("F4", System.Globalization.CultureInfo.InvariantCulture),
                    Vector3.Dot(sampledContact.PalmTarget - eyes, front).ToString("F4", System.Globalization.CultureInfo.InvariantCulture)));
            }
            foreach (var bone in new[] { HumanBodyBones.Head, HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm,
                HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm, HumanBodyBones.LeftHand, HumanBodyBones.RightHand })
            {
                var transform = sampledAnimator.GetBoneTransform(bone);
                var rotation = transform.localRotation;
                var speed = previousRotations.TryGetValue(bone, out var previous) ? Quaternion.Angle(previous, rotation) / Time.deltaTime : 0;
                previousRotations[bone] = rotation;
                var bend = 0f;
                if (bone == HumanBodyBones.LeftHand || bone == HumanBodyBones.RightHand)
                {
                    var left = bone == HumanBodyBones.LeftHand;
                    var elbow = sampledAnimator.GetBoneTransform(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm);
                    var finger = sampledAnimator.GetBoneTransform(left ? HumanBodyBones.LeftMiddleProximal : HumanBodyBones.RightMiddleProximal);
                    bend = Vector3.Angle(transform.position - elbow.position, finger.position - transform.position);
                }
                kinematics.WriteLine(string.Join(",", caption, Time.time.ToString("F4", System.Globalization.CultureInfo.InvariantCulture), bone,
                    speed.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), bend.ToString("F3", System.Globalization.CultureInfo.InvariantCulture)));
            }
        }
        private void LabelCamera()
        {
            var canvas = new GameObject("Capture caption").AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceCamera; canvas.worldCamera = cameraToCapture; canvas.planeDistance = .1f; canvas.sortingOrder = 30000;
            label = new GameObject("Caption").AddComponent<UnityEngine.UI.Text>();
            label.transform.SetParent(canvas.transform, false);
            label.font = Font.CreateDynamicFontFromOSFont("Arial", 18);
            label.fontSize = 18; label.color = Color.white; label.alignment = TextAnchor.UpperCenter;
            var rect = label.rectTransform; rect.anchorMin = new Vector2(0, 1); rect.anchorMax = new Vector2(1, 1); rect.pivot = new Vector2(.5f, 1); rect.sizeDelta = new Vector2(0, 52); rect.anchoredPosition = new Vector2(0, -8);
        }
        private void Frame() => frameRequested = true;
        private void RenderFrame()
        {
            label.text = caption;
            cameraToCapture.Render(); RenderTexture.active = target;
            pixels.ReadPixels(new Rect(0, 0, 640, 720), 0, 0, false); pixels.Apply(false);
            var data = pixels.GetRawTextureData<byte>().ToArray();
            encoder.StandardInput.BaseStream.Write(data, 0, data.Length); RenderTexture.active = null;
        }
        private IEnumerator Catalogue(AvatarMotionController motion, AvatarStateController state)
        {
            motion.enabled = false;
            state.SetState(AvatarState.Idle, false);
            var gestures = FindFirstObjectByType<AvatarGestureController>();
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(AvatarMotionSetup.SettingsPath);
            var folder = Path.Combine(Path.GetDirectoryName(Output), "catalog-frames"); Directory.CreateDirectory(folder);
            var report = new System.Text.StringBuilder("pattern,side,duration,minimum_hand_head_distance\n");
            if (Mode == "route")
            {
                caption="Rest"; var until=Time.time+3;
                while(Time.time<until){yield return null;Frame();}
            }
            foreach (var definition in settings.GestureDefinitions.Where(d => d.Tag == AvatarBehaviorPolicy.Family(d.Tag)))
            {
            if (Mode == "contacts" && definition.Tag != GestureTag.Facepalm && definition.Tag != GestureTag.Head_Scratch && definition.Tag != GestureTag.Thinking) continue;
            if (Mode == "polish" && definition.Tag != GestureTag.Farewell && definition.Tag != GestureTag.Thumbs_Up) continue;
            if (Mode == "face" && definition.Tag != GestureTag.Facepalm) continue;
            if (Mode == "arms" && definition.Tag != GestureTag.Thinking && definition.Tag != GestureTag.Thumbs_Up && definition.Tag != GestureTag.Explanation && definition.Tag != GestureTag.Talk) continue;
            if (Mode == "armcheck" && definition.Tag != GestureTag.Thinking && definition.Tag != GestureTag.Talk) continue;
            foreach (var variant in (Mode == "route" ? definition.Variants : definition.Variants.GroupBy(v => v.PatternId).Select(g => g.First())).Take(Mode == "armcheck" ? 1 : 100))
            {
                if (Mode=="route" && variant.Id!="Iris_Thumbs_Up_direct_Left" && variant.Id!="Iris_Facepalm_supported_Left") continue;
                if (Mode == "regression" && !new[] { "Talk_inclusive", "Talk_precision", "Explanation_present", "Thinking_chin_pause", "Thinking_folded_support", "Thinking_temple_approach", "Pointing_direct", "Thumbs_Up_direct", "Facepalm_direct" }.Contains(variant.PatternId)) continue;
                var single = Instantiate(definition); single.CooldownSeconds = 0;
                single.AllowedEmotions.Clear(); single.DeniedEmotions.Clear(); single.Variants = new System.Collections.Generic.List<GestureVariant> { variant };
                var isolated = Instantiate(settings); isolated.GestureDefinitions = new System.Collections.Generic.List<GestureDefinition> { single };
                gestures.Configure(isolated, motion.Animator);
                gestures.SetPolicy(new AvatarBehaviorPolicy());
                caption = variant.PatternId;
                if (!gestures.Trigger(single.Tag, AvatarEmotion.Neutral, false, .9f, false)) throw new InvalidOperationException("Could not capture " + variant.Id);
                var saved = false; var minimum = float.MaxValue;
                var until = Time.time + variant.Duration / .92f + (Mode=="route"?6f:.4f);
                while (Time.time < until)
                {
                    yield return null; Frame();
                    var head = motion.Animator.GetBoneTransform(HumanBodyBones.Head);
                    var hand = motion.Animator.GetBoneTransform(variant.Side == GestureSide.Left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                    minimum = Mathf.Min(minimum, Vector3.Distance(head.position, hand.position));
                    if (!saved && gestures.Elapsed >= variant.PreparationSeconds + variant.StrokeSeconds * .65f)
                    { File.WriteAllBytes(Path.Combine(folder, variant.PatternId + ".png"), pixels.EncodeToPNG()); saved = true; }
                }
                report.Append(variant.PatternId).Append(',').Append(variant.Side).Append(',').Append(variant.Duration.ToString(System.Globalization.CultureInfo.InvariantCulture)).Append(',').Append(minimum.ToString(System.Globalization.CultureInfo.InvariantCulture)).Append('\n');
                Destroy(single); Destroy(isolated);
            }
            }
            File.WriteAllText(Path.ChangeExtension(Output, ".csv"), report.ToString());
        }
        private IEnumerator Start()
        {
            yield return null;
            var motion = FindFirstObjectByType<AvatarMotionController>();
            var state = FindFirstObjectByType<AvatarStateController>();
            sampledAnimator = motion.Animator;
            sampledContact = FindFirstObjectByType<AvatarContactController>(); sampledGestures = FindFirstObjectByType<AvatarGestureController>();
            var armRig = FindFirstObjectByType<AvatarArmRig>();
            sampledArms = armRig;
            sampledPose = FindFirstObjectByType<AvatarPoseFilter>();
            posture = new StreamWriter(Path.ChangeExtension(Output,".posture.csv"));
            posture.WriteLine("pattern,time,head_pitch,head_yaw,head_roll,left_abduction,right_abduction");
            armMeasurements = new StreamWriter(Path.ChangeExtension(Output, ".arms.csv"));
            armMeasurements.WriteLine("pattern,time,left,x,y,z,source_x,source_y,source_z,goal_x,goal_y,goal_z,flex,twist,endpoint_error,body_clearance,elbow_side_bend,detour,blocked_steps,route_stage,solver_clearance,rotation_prediction_error,final_palm_error,orientation_error");
            if (armRig != null) File.WriteAllText(Path.ChangeExtension(Output, ".torso.txt"), armRig.DescribeTorso());
            contacts = new StreamWriter(Path.ChangeExtension(Output, ".contacts.csv"));
            contacts.WriteLine("pattern,time,weight,ik_palm_error,final_palm_error,palm_front,goal_front");
            kinematics = new StreamWriter(Path.ChangeExtension(Output, ".kinematics.csv"));
            kinematics.WriteLine("pattern,time,bone,angular_speed_degrees_s,wrist_bend_degrees");
            cameraToCapture = Camera.main; referenceCamera = cameraToCapture;
            if (motion == null || cameraToCapture == null) throw new InvalidOperationException("Canonical motion/camera missing");
            var angle = 0f; var args = Environment.GetCommandLineArgs();
            for (var i = 0; i + 1 < args.Length; i++) if (args[i] == "-captureAngle") angle = float.Parse(args[i+1], System.Globalization.CultureInfo.InvariantCulture);
            if (args.Contains("-rawRest")) armRig.enabled = false;
            if (Mathf.Abs(angle) > .01f)
            {
                // Observe the same performance from another angle without
                // changing the avatar's gaze or anatomical front reference.
                cameraToCapture = new GameObject("Evidence angle camera").AddComponent<Camera>();
                cameraToCapture.CopyFrom(referenceCamera); cameraToCapture.enabled = false;
                var pivot = sampledAnimator.GetBoneTransform(HumanBodyBones.Chest).position;
                pivot.y = referenceCamera.transform.position.y;
                cameraToCapture.transform.position = pivot + Quaternion.AngleAxis(angle, sampledAnimator.transform.up) * (referenceCamera.transform.position - pivot);
                cameraToCapture.transform.rotation = Quaternion.AngleAxis(angle, sampledAnimator.transform.up) * referenceCamera.transform.rotation;
                referenceTarget = new RenderTexture(64,64,16); referenceCamera.targetTexture = referenceTarget;
            }
            target = new RenderTexture(640, 720, 24);
            cameraToCapture.targetTexture = target;
            cameraToCapture.backgroundColor = new Color(.11f, .115f, .13f, 1);
            cameraToCapture.clearFlags = CameraClearFlags.SolidColor;
            pixels = new Texture2D(640, 720, TextureFormat.RGB24, false);
            LabelCamera();
            encoder = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo {
                FileName = "C:/ProgramData/chocolatey/bin/ffmpeg.exe",
                Arguments = "-y -loglevel error -f rawvideo -pixel_format rgb24 -video_size 640x720 -framerate 24 -i pipe:0 -vf vflip -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p \"" + Output + "\"",
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true
            });
            Time.captureFramerate = 24;
            UnityEngine.Random.InitState(7081);
            if (Mode == "body")
            {
                var body = FindFirstObjectByType<AvatarBodyController>();
                var folder = Path.Combine(Path.GetDirectoryName(Output), "body-frames"); Directory.CreateDirectory(folder);
                var measured = new System.Collections.Generic.List<AvatarActionResultPayload>();
                body.Completed += measured.Add;
                foreach (var action in new[] { "body_neutral", "raise_left_hand", "raise_right_hand", "lower_left_hand", "lower_both_hands",
                    "extend_left_hand", "lower_both_hands", "tilt_head_left", "head_neutral", "tilt_head_right", "head_neutral",
                    "turn_head_left", "head_neutral", "turn_head_right", "head_neutral", "blink_left", "blink_right", "blink", "greeting_left", "head_scratch_right", "body_neutral" })
                {
                    caption = action; measured.Clear();
                    if (!body.Execute(action, action)) throw new InvalidOperationException("Unsupported body action " + action);
                    var started = Time.time; var saved = false;
                    while (measured.Count == 0 && Time.time - started < 9)
                    {
                        yield return null; Frame();
                        if (action.StartsWith("blink") && !saved && Time.time - started >= .26f)
                        { File.WriteAllBytes(Path.Combine(folder, action + ".png"), pixels.EncodeToPNG()); saved = true; }
                    }
                    if (measured.Count == 0 || !measured[0].reached) throw new InvalidOperationException("Body action did not reach pose: " + action);
                    Debug.Log("[BodyCapture] " + JsonUtility.ToJson(measured[0]));
                    var until = Time.time + .65f;
                    while (Time.time < until) { yield return null; Frame(); }
                    if (!saved) File.WriteAllBytes(Path.Combine(folder, action + ".png"), pixels.EncodeToPNG());
                }
                encoder.StandardInput.Close(); encoder.WaitForExit(); Time.captureFramerate = 0; EditorApplication.ExitPlaymode(); yield break;
            }
            if (Mode == "posture")
            {
                motion.enabled = false; state.SetState(AvatarState.Idle,false); caption = "Rest";
                var until = Time.time + 8;
                while (Time.time < until) { yield return null; Frame(); }
                File.WriteAllText(Path.ChangeExtension(Output,".skeleton.txt"),lastSkeleton);
                encoder.StandardInput.Close(); encoder.WaitForExit(); Time.captureFramerate = 0; EditorApplication.ExitPlaymode(); yield break;
            }
            if (Mode == "catalog" || Mode == "contacts" || Mode == "polish" || Mode == "face" || Mode == "arms" || Mode == "armcheck" || Mode == "regression" || Mode == "route")
            {
                yield return Catalogue(motion, state);
                encoder.StandardInput.Close(); encoder.WaitForExit();
                if (encoder.ExitCode != 0) throw new InvalidOperationException("Video encoding failed");
                Time.captureFramerate = 0; EditorApplication.ExitPlaymode(); yield break;
            }
            var start = Time.time;
            var stage = -1;
            while (Time.time - start < 66f)
            {
                var elapsed = Time.time - start;
                var next = elapsed < 4 ? 0 : elapsed < 10 ? 1 : elapsed < 14 ? 2 : elapsed < 22 ? 3 : elapsed < 30 ? 4 : elapsed < 36 ? 5 : elapsed < 42 ? 6 : elapsed < 48 ? 7 : elapsed < 54 ? 8 : 9;
                if (next != stage)
                {
                    stage = next;
                    if (stage == 0 || stage == 9) { caption = "Idle"; state.SetState(AvatarState.Idle, false); }
                    if (stage == 1) { caption = "Listening"; state.SetState(AvatarState.Listening, false); }
                    if (stage == 2) { caption = "Thinking"; state.SetState(AvatarState.Thinking, false); }
                    if (stage == 3 || stage == 4)
                    {
                        caption = "Speaking / auto"; state.SetState(AvatarState.Speaking, false);
                        motion.QueueSpeechCue(stage, 8f, new AvatarMotionCuePayload { gesture = "auto" });
                        motion.OnSpeechSegmentStarted(stage);
                    }
                    if (stage >= 5 && stage <= 8)
                    {
                        var gestures = new[] { GestureTag.Greeting, GestureTag.Thinking, GestureTag.Shrug, GestureTag.Facepalm };
                        caption = gestures[stage - 5].ToString();
                        motion.TriggerGesture(gestures[stage - 5], .85f, true);
                    }
                }
                // WaitForEndOfFrame is not pumped by Unity's batch-mode editor.
                // Render explicitly after a normal frame yield instead.
                yield return null;
                Frame();
            }
            encoder.StandardInput.Close(); encoder.WaitForExit();
            if (encoder.ExitCode != 0) throw new InvalidOperationException("Video encoding failed");
            File.WriteAllText(Path.ChangeExtension(Output, ".txt"), "Scripted runtime capture, seed 7081, 24 fps. No microphone/TTS qualification.\n0 idle; 4 listening; 10 thinking; 14/22 speaking auto; 30 greeting; 36 thinking; 42 shrug; 48 facepalm; 54 idle.\n");
            Debug.Log("[MotionCapture] Saved " + Output);
            Time.captureFramerate = 0;
            EditorApplication.ExitPlaymode();
        }
        private void OnDestroy()
        {
            Time.captureFramerate = 0;
            if (encoder != null && !encoder.HasExited) { encoder.StandardInput.Close(); encoder.WaitForExit(5000); }
            kinematics?.Dispose();
            contacts?.Dispose();
            armMeasurements?.Dispose();
            posture?.Dispose();
            if (cameraToCapture != null) cameraToCapture.targetTexture = null;
            if (referenceTarget != null) { referenceCamera.targetTexture = null; Destroy(referenceTarget); }
            if (target != null) Destroy(target);
            if (pixels != null) Destroy(pixels);
        }
    }
}
