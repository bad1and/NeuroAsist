using System;
using System.IO;
using UniVRM10;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarPromoRenderer
    {
        private const string ScenePath = "Assets/Scenes/AvatarOverlay.unity";

        private static AnimationClip LoadClip(string clipName)
        {
            string path = "Assets/NeuroAsistAvatar/Animations/" + clipName + ".fbx";
            foreach (var asset in AssetDatabase.LoadAllAssetsAtPath(path))
            {
                if (asset is AnimationClip clip && !clip.name.StartsWith("__preview__"))
                {
                    return clip;
                }
            }
            Debug.LogWarning("[PromoRenderer] Clip not found: " + path);
            return null;
        }

        private static void ResetBlendShapes(SkinnedMeshRenderer smr)
        {
            if (smr == null || smr.sharedMesh == null) return;
            for (int i = 0; i < smr.sharedMesh.blendShapeCount; i++)
            {
                smr.SetBlendShapeWeight(i, 0f);
            }
        }

        private static void SetBlendShape(SkinnedMeshRenderer smr, string name, float weight)
        {
            if (smr == null || smr.sharedMesh == null) return;
            int idx = smr.sharedMesh.GetBlendShapeIndex(name);
            if (idx >= 0)
            {
                smr.SetBlendShapeWeight(idx, weight);
            }
        }

        private static void SetupStudioLighting()
        {
            // 1. Key Light (Soft balanced directional light from front-right)
            var keyGo = GameObject.Find("Directional Light");
            if (keyGo == null) keyGo = new GameObject("Directional Light");
            var keyLight = keyGo.GetComponent<Light>();
            if (keyLight == null) keyLight = keyGo.AddComponent<Light>();
            keyLight.type = LightType.Directional;
            keyLight.color = new Color(1.0f, 0.98f, 0.95f, 1.0f);
            keyLight.intensity = 0.92f;
            keyLight.shadows = LightShadows.Soft;
            keyGo.transform.rotation = Quaternion.Euler(20f, -22f, 0f);

            // 2. Rim Light (Signature Iris Lavender rim light #c4b5fd to illuminate hair & contours)
            var rimGo = GameObject.Find("StudioRimLight");
            if (rimGo == null) rimGo = new GameObject("StudioRimLight");
            var rimLight = rimGo.GetComponent<Light>();
            if (rimLight == null) rimLight = rimGo.AddComponent<Light>();
            rimLight.type = LightType.Directional;
            rimLight.color = new Color(0.77f, 0.71f, 0.99f, 1.0f); // #c4b5fd
            rimLight.intensity = 0.75f;
            rimLight.shadows = LightShadows.None;
            rimGo.transform.rotation = Quaternion.Euler(15f, 155f, 0f);

            // 3. Fill Light (Cool ambient fill to keep shadows soft and clean)
            var fillGo = GameObject.Find("StudioFillLight");
            if (fillGo == null) fillGo = new GameObject("StudioFillLight");
            var fillLight = fillGo.GetComponent<Light>();
            if (fillLight == null) fillLight = fillGo.AddComponent<Light>();
            fillLight.type = LightType.Directional;
            fillLight.color = new Color(0.82f, 0.85f, 0.96f, 1.0f);
            fillLight.intensity = 0.35f;
            fillLight.shadows = LightShadows.None;
            fillGo.transform.rotation = Quaternion.Euler(-10f, -75f, 0f);

            // Ambient lighting
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.20f, 0.20f, 0.24f, 1.0f);
        }

        public static void RenderAllPromoAssets()
        {
            Debug.Log("[PromoRenderer] Starting Studio Promo Rendering Pass...");
            var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var vrm = UnityEngine.Object.FindFirstObjectByType<Vrm10Instance>();
            if (vrm == null)
            {
                Debug.LogError("[PromoRenderer] IRIS Vrm10Instance not found in scene!");
                return;
            }

            var anim = vrm.GetComponentInChildren<Animator>();
            if (anim == null)
            {
                Debug.LogError("[PromoRenderer] Animator not found on IRIS!");
                return;
            }

            // Find Face SkinnedMeshRenderer
            SkinnedMeshRenderer faceSmr = null;
            foreach (var smr in vrm.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                if (smr.name.IndexOf("Face", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    faceSmr = smr;
                    break;
                }
            }

            SetupStudioLighting();

            // Camera setup
            var camGo = GameObject.Find("PromoStudioCamera");
            if (camGo == null) camGo = new GameObject("PromoStudioCamera");
            var cam = camGo.GetComponent<Camera>();
            if (cam == null) cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 27f;
            cam.nearClipPlane = 0.01f;
            cam.farClipPlane = 50f;
            cam.allowHDR = true;
            cam.allowMSAA = true;

            // Load motion clips
            var clipIdle = LoadClip("X Bot@Idle");
            var clipWaving = LoadClip("X Bot@WavingGoodbye") ?? LoadClip("X Bot@Waving");
            var clipThinking = LoadClip("X Bot@Thinking");
            var clipShrugging = LoadClip("X Bot@Shrugging");
            var clipTalking = LoadClip("X Bot@Talking");

            // Absolute path to root promo/renders_and_art directory (3 levels up from Assets)
            string rootDir = Path.GetFullPath(Path.Combine(Application.dataPath, "../../../promo/renders_and_art"));
            string portraitsDir = Path.Combine(rootDir, "portraits");
            string posesDir = Path.Combine(rootDir, "poses");
            string bannersDir = Path.Combine(rootDir, "banners");

            Directory.CreateDirectory(rootDir);
            Directory.CreateDirectory(portraitsDir);
            Directory.CreateDirectory(posesDir);
            Directory.CreateDirectory(bannersDir);

            // Anchor points
            var head = anim.GetBoneTransform(HumanBodyBones.Head);
            Vector3 headPos = head != null ? head.position : new Vector3(0, 1.25f, 0);
            Vector3 eyeCenter = headPos + new Vector3(0, 0.04f, 0);
            Vector3 bodyCenter = new Vector3(headPos.x, 0.82f, headPos.z);
            Vector3 mediumCenter = headPos - new Vector3(0, 0.20f, 0);

            Vector3 fwd = Vector3.forward;
            Vector3 up = Vector3.up;
            Vector3 rgt = Vector3.right;

            Debug.Log("[PromoRenderer] Target Root: " + rootDir);
            Debug.Log("[PromoRenderer] HeadPos=" + headPos + ", EyeCenter=" + eyeCenter);

            // ==========================================================
            // SET 1: HIGH-RES PORTRAITS (1500 x 1500)
            // ==========================================================

            // 1.1 Frontal Open Eyes Smile (Natural Hero Portrait)
            ApplyPose(anim, clipIdle, 1.0f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 25f);
            SetBlendShape(faceSmr, "Fcl_MTH_Joy", 40f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 20f);
            SetBlendShape(faceSmr, "mouthSmileRight", 20f);
            RenderPair(cam, eyeCenter + fwd * 0.58f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_front_open_eyes", rootDir, "iris_portrait_front_smile");

            // 1.2 Three-Quarter Left (Classic VTuber Angle)
            RenderPair(cam, eyeCenter + fwd * 0.56f - rgt * 0.22f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_3quarter_left", rootDir, "iris_portrait_3quarter_left");

            // 1.3 Three-Quarter Right
            RenderPair(cam, eyeCenter + fwd * 0.56f + rgt * 0.22f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_3quarter_right", rootDir, "iris_portrait_3quarter_right");

            // 1.4 Side Profile
            RenderPair(cam, eyeCenter + rgt * 0.55f + fwd * 0.12f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_profile", rootDir, "iris_portrait_profile");

            // 1.5 Playful Wink (Left eye open with starry pupil, right eye winking closed)
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 30f);
            SetBlendShape(faceSmr, "Fcl_EYE_Close_R", 100f);
            SetBlendShape(faceSmr, "eyeBlinkRight", 100f);
            SetBlendShape(faceSmr, "mouthSmileRight", 45f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 18f);
            SetBlendShape(faceSmr, "browOuterUpRight", 30f);
            RenderPair(cam, eyeCenter + fwd * 0.56f - rgt * 0.15f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_playful_wink", rootDir, "iris_portrait_playful_wink");

            // 1.6 Ironic Smirk ("Своя в доску", playful tech banter)
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "mouthSmileRight", 65f);
            SetBlendShape(faceSmr, "Fcl_MTH_SkinFung_R", 40f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 10f);
            SetBlendShape(faceSmr, "browOuterUpRight", 50f);
            SetBlendShape(faceSmr, "browDownLeft", 22f);
            SetBlendShape(faceSmr, "eyeSquintRight", 15f);
            RenderPair(cam, eyeCenter + fwd * 0.56f + rgt * 0.14f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_smirk", rootDir, "iris_portrait_ironic_smirk");

            // 1.7 Cat Mouth (:3 Cute Anime expression)
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "_mouthPress+CatMouth", 85f);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 35f);
            RenderPair(cam, eyeCenter + fwd * 0.57f - rgt * 0.10f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_cat_mouth", rootDir, "iris_portrait_cat_mouth");

            // 1.8 Thoughtful / Curious Look
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "browInnerUp", 45f);
            SetBlendShape(faceSmr, "browDownLeft", 25f);
            SetBlendShape(faceSmr, "eyeLookUpRight", 30f);
            SetBlendShape(faceSmr, "mouthSmileRight", 18f);
            RenderPair(cam, eyeCenter + fwd * 0.57f - rgt * 0.18f, eyeCenter, 1500, 1500, portraitsDir, "iris_portrait_thoughtful", rootDir, "iris_portrait_thoughtful");

            // ==========================================================
            // SET 2: DYNAMIC POSES (FULL-BODY 1080x1920 & MEDIUM 1200x1600)
            // ==========================================================

            // 2.1 Waving / Greeting (Hand raised waving)
            ApplyPose(anim, clipWaving, 1.15f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 30f);
            SetBlendShape(faceSmr, "Fcl_MTH_Joy", 45f);
            SetBlendShape(faceSmr, "mouthSmileRight", 25f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 25f);
            // Full body vertical (1080x1920)
            RenderPair(cam, bodyCenter + fwd * 2.30f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_waving_fullbody", rootDir, "iris_pose_waving_fullbody");
            // Medium shot (1200x1600)
            RenderPair(cam, mediumCenter + fwd * 1.30f, mediumCenter, 1200, 1600, posesDir, "iris_pose_waving_medium", rootDir, "iris_pose_waving_medium");

            // 2.2 Thinking Pose (Hand on chin, analytical)
            ApplyPose(anim, clipThinking, 1.45f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "browInnerUp", 40f);
            SetBlendShape(faceSmr, "browDownLeft", 20f);
            SetBlendShape(faceSmr, "mouthSmileRight", 30f);
            SetBlendShape(faceSmr, "eyeLookUpLeft", 25f);
            RenderPair(cam, bodyCenter + fwd * 2.25f - rgt * 0.25f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_thinking_fullbody", rootDir, "iris_pose_thinking_fullbody");
            RenderPair(cam, mediumCenter + fwd * 1.30f - rgt * 0.15f, mediumCenter, 1200, 1600, posesDir, "iris_pose_thinking_medium", rootDir, "iris_pose_thinking_medium");

            // 2.3 Shrugging ("Ой, всё" / "Легко поправим")
            ApplyPose(anim, clipShrugging, 0.90f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 30f);
            SetBlendShape(faceSmr, "mouthSmileRight", 35f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 35f);
            SetBlendShape(faceSmr, "eyeWideLeft", 20f);
            SetBlendShape(faceSmr, "eyeWideRight", 20f);
            RenderPair(cam, bodyCenter + fwd * 2.25f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_shrugging_fullbody", rootDir, "iris_pose_shrugging_fullbody");
            RenderPair(cam, mediumCenter + fwd * 1.30f, mediumCenter, 1200, 1600, posesDir, "iris_pose_shrugging_medium", rootDir, "iris_pose_shrugging_medium");

            // 2.4 Idle Elegant Stance (Natural relaxed posture)
            ApplyPose(anim, clipIdle, 1.0f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 25f);
            SetBlendShape(faceSmr, "Fcl_MTH_Joy", 35f);
            SetBlendShape(faceSmr, "mouthSmileRight", 20f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 20f);
            // Full body front
            RenderPair(cam, bodyCenter + fwd * 2.35f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_idle_fullbody", rootDir, "iris_pose_idle_fullbody_front");
            // Full body 3/4 perspective
            RenderPair(cam, bodyCenter + fwd * 2.25f - rgt * 0.70f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_idle_3quarter", rootDir, "iris_pose_idle_fullbody_3quarter");

            // 2.5 Talking / Expressive
            ApplyPose(anim, clipTalking, 1.75f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 30f);
            SetBlendShape(faceSmr, "mouthSmileRight", 35f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 35f);
            RenderPair(cam, bodyCenter + fwd * 2.30f + up * 0.05f, bodyCenter, 1080, 1920, posesDir, "iris_pose_talking_expressive", rootDir, "iris_pose_talking_expressive");

            // ==========================================================
            // SET 3: PROMO BANNERS, HERO WALLPAPERS & OPENGRAPH
            // ==========================================================

            // 3.1 16:9 Desktop Hero Banner (2560 x 1440 2K QHD) - Iris framed on right side
            ApplyPose(anim, clipIdle, 1.0f);
            ResetBlendShapes(faceSmr);
            SetBlendShape(faceSmr, "Fcl_BRW_Joy", 25f);
            SetBlendShape(faceSmr, "Fcl_MTH_Joy", 35f);
            SetBlendShape(faceSmr, "mouthSmileRight", 25f);
            SetBlendShape(faceSmr, "mouthSmileLeft", 20f);

            Vector3 bannerTarget = headPos - up * 0.20f - rgt * 0.45f;
            RenderPair(cam, bannerTarget + fwd * 1.45f + up * 0.05f, bannerTarget, 2560, 1440, bannersDir, "iris_banner_desktop_hero_2k", rootDir, "iris_promo_banner_16x9_wide");

            // 3.2 1200 x 630 OpenGraph / Social Media Card
            ApplyPose(anim, clipWaving, 1.15f);
            Vector3 ogTarget = headPos - up * 0.16f - rgt * 0.32f;
            RenderPair(cam, ogTarget + fwd * 1.35f + up * 0.05f, ogTarget, 1200, 630, bannersDir, "iris_banner_opengraph_social", rootDir, "iris_opengraph_social_card");

            // 3.3 Streamer / VTuber Overlay Card (1920 x 1080)
            ApplyPose(anim, clipTalking, 1.75f);
            Vector3 streamerTarget = headPos - up * 0.15f;
            RenderPair(cam, streamerTarget + fwd * 1.25f, streamerTarget, 1920, 1080, bannersDir, "iris_banner_streamer_overlay", rootDir, "iris_render_upperbody_streamer");

            Debug.Log("[PromoRenderer] ALL STUDIO PROMO RENDERS FINISHED SUCCESSFULLY!");
        }

        private static void ApplyPose(Animator anim, AnimationClip clip, float time)
        {
            if (clip == null || anim == null) return;
            clip.SampleAnimation(anim.gameObject, time);
        }

        private static void RenderPair(Camera cam, Vector3 camPos, Vector3 lookTarget, int width, int height, string subDir, string subName, string rootDir, string legacyName)
        {
            // 1. Transparent version (.png with alpha)
            string transSubPath = Path.Combine(subDir, subName + "_trans.png");
            RenderCamera(cam, camPos, lookTarget, width, height, transSubPath, true);

            // 2. Graphite dark version (.png with brand surface #161922)
            string darkSubPath = Path.Combine(subDir, subName + "_dark.png");
            RenderCamera(cam, camPos, lookTarget, width, height, darkSubPath, false);

            // Copy to legacy root paths if requested for backward compatibility
            if (!string.IsNullOrEmpty(legacyName) && !string.IsNullOrEmpty(rootDir))
            {
                string transRootPath = Path.Combine(rootDir, legacyName + "_trans.png");
                string darkRootPath = Path.Combine(rootDir, legacyName + "_dark.png");
                try { File.Copy(transSubPath, transRootPath, true); } catch { }
                try { File.Copy(darkSubPath, darkRootPath, true); } catch { }
            }
        }

        private static void RenderCamera(Camera cam, Vector3 camPos, Vector3 lookTarget, int width, int height, string filePath, bool transparent)
        {
            cam.transform.position = camPos;
            cam.transform.LookAt(lookTarget);

            if (transparent)
            {
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = new Color(0, 0, 0, 0);
            }
            else
            {
                // Exact Iris Graphite Dark background (#161922)
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = new Color(0.086f, 0.098f, 0.133f, 1.0f);
            }

            // High quality render texture with 8x MSAA and sRGB format
            var rt = RenderTexture.GetTemporary(width, height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB, 8);
            cam.targetTexture = rt;
            cam.Render();

            RenderTexture.active = rt;
            var tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            tex.Apply();

            byte[] bytes = tex.EncodeToPNG();
            File.WriteAllBytes(filePath, bytes);
            Debug.Log("[PromoRenderer] Saved: " + Path.GetFileName(filePath) + " (" + width + "x" + height + ", " + bytes.Length + " bytes)");

            cam.targetTexture = null;
            RenderTexture.active = null;
            RenderTexture.ReleaseTemporary(rt);
            UnityEngine.Object.DestroyImmediate(tex);
        }
    }
}
