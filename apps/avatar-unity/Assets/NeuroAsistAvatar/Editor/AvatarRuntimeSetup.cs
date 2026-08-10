using NeuroAsist.Avatar;
using UniVRM10;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarRuntimeSetup
    {
        private const string ScenePath = "Assets/Scenes/AvatarOverlay.unity";
        [MenuItem("Iris/Avatar/Setup Canonical Scene")]
        public static void Setup()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var audio = GameObject.Find("LipSyncAudio");
            var vrm = Object.FindFirstObjectByType<Vrm10Instance>();
            if (audio == null || vrm == null) { EditorUtility.DisplayDialog("Iris Avatar", "LipSyncAudio or Vrm10Instance is missing. Existing scene was not changed.", "OK"); return; }
            var root = GameObject.Find("NeuroAsistAvatarRuntime") ?? new GameObject("NeuroAsistAvatarRuntime");
            AvatarMotionSetup.SetupAssets();
            var settings = AssetDatabase.LoadAssetAtPath<AvatarRuntimeSettings>("Assets/NeuroAsistAvatar/AvatarRuntimeSettings.asset");
            if (settings == null) { settings = ScriptableObject.CreateInstance<AvatarRuntimeSettings>(); AssetDatabase.CreateAsset(settings, "Assets/NeuroAsistAvatar/AvatarRuntimeSettings.asset"); }
            var motionSettings = AvatarMotionSetup.EnsureSettings();
            var animator = vrm.GetComponentInChildren<Animator>();
            if (animator == null) { EditorUtility.DisplayDialog("Iris Avatar", "No Animator was found below Vrm10Instance. Existing scene was not changed.", "OK"); return; }
            var motionController = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(AvatarMotionSetup.ControllerPath);
            if (motionController != null)
            {
                animator.runtimeAnimatorController = motionController;
                EditorUtility.SetDirty(animator);
            }
            var state = Get<AvatarStateController>(root); var player = Get<AvatarAudioPlayer>(audio); var fallback = Get<VolumeLipSyncFallback>(audio); var emotion = Get<AvatarEmotionController>(root); var speech = Get<AvatarSpeechCoordinator>(root); var router = Get<AvatarCommandRouter>(root); var client = Get<AvatarWebSocketClient>(root); var performance = Get<AvatarPerformanceProfile>(root); var overlay = Get<WindowsDesktopOverlay>(root);
            var presentation = Get<AvatarPresentationController>(root);
            var idle = Get<AvatarIdleScheduler>(root); var gesture = Get<AvatarGestureController>(root); var look = Get<AvatarLookController>(root); var motion = Get<AvatarMotionController>(root);
            var target = GameObject.Find("AvatarHeadLookTarget") ?? new GameObject("AvatarHeadLookTarget");
            if (Camera.main != null) target.transform.SetParent(Camera.main.transform, false); else target.transform.position = vrm.transform.position + vrm.transform.forward * 2f + Vector3.up * 1.5f;
            player.Configure(settings, audio.GetComponent<AudioSource>());
            // Keep uLipSync as the primary renderer in Auto/ULipSync modes.
            // This also repairs a scene saved after toggling the fallback mode.
            var lipSync = audio.GetComponent<global::uLipSync.uLipSync>();
            if (lipSync != null)
            {
                lipSync.enabled = settings.LipSyncMode != LipSyncMode.Disabled
                    && settings.LipSyncMode != LipSyncMode.VolumeFallback;
                var phoneme = Get<Vrm10PhonemeLipSync>(audio);
                phoneme.Configure(vrm, audio.GetComponent<AudioSource>());
                while (lipSync.onLipSyncUpdate.GetPersistentEventCount() > 0)
                    UnityEventTools.RemovePersistentListener(lipSync.onLipSyncUpdate, 0);
                UnityEventTools.AddPersistentListener(lipSync.onLipSyncUpdate, phoneme.OnLipSyncUpdate);
                EditorUtility.SetDirty(lipSync);
                EditorUtility.SetDirty(phoneme);
            }
            SerializedObject fallbackSerialized = new SerializedObject(fallback); fallbackSerialized.FindProperty("settings").objectReferenceValue = settings; fallbackSerialized.FindProperty("audioSource").objectReferenceValue = audio.GetComponent<AudioSource>(); fallbackSerialized.FindProperty("vrm").objectReferenceValue = vrm; fallbackSerialized.ApplyModifiedPropertiesWithoutUndo();
            Link(state, "client", client); Link(emotion, "settings", settings); Link(emotion, "vrm", vrm); Link(speech, "client", client); Link(speech, "player", player); Link(speech, "emotion", emotion); Link(speech, "state", state); Link(speech, "fallback", fallback); Link(router, "client", client); Link(router, "speech", speech); Link(router, "emotion", emotion); Link(router, "state", state); Link(client, "settings", settings); Link(client, "router", router); Link(client, "state", state);
            Link(performance, "settings", settings);
            presentation.Configure(Camera.main, vrm);
            Link(speech, "motion", motion); Link(router, "motion", motion); Link(router, "overlay", overlay);
            Link(idle, "settings", motionSettings); Link(gesture, "settings", motionSettings); Link(gesture, "animator", animator); Link(look, "animator", animator); Link(look, "target", target.transform);
            Link(motion, "settings", motionSettings); Link(motion, "animator", animator); Link(motion, "avatarRoot", vrm.transform); Link(motion, "state", state); Link(motion, "client", client); Link(motion, "idleScheduler", idle); Link(motion, "gestureController", gesture); Link(motion, "lookController", look);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            EditorSceneManager.MarkSceneDirty(scene); EditorSceneManager.SaveScene(scene); AssetDatabase.SaveAssets();
            Debug.Log("[AvatarSetup] Canonical avatar runtime configured. Existing VRM and uLipSync profile were preserved.");
        }
        [MenuItem("Iris/Avatar/Validate Canonical Scene")]
        public static void Validate()
        {
            var audio = GameObject.Find("LipSyncAudio"); var vrm = Object.FindFirstObjectByType<Vrm10Instance>();
            if (audio == null || audio.GetComponent<AudioSource>() == null || vrm == null) Debug.LogError("[AvatarSetup] Missing LipSyncAudio/AudioSource/Vrm10Instance.");
            else Debug.Log("[AvatarSetup] Scene validation passed. Run Iris/Avatar/Validate Avatar Motion Setup and verify uLipSync movement with a real WAV in Play mode.");
        }
        private static T Get<T>(GameObject gameObject) where T : Component => gameObject.GetComponent<T>() ?? gameObject.AddComponent<T>();
        private static void Link(Object target, string field, Object value) { var serialized = new SerializedObject(target); serialized.FindProperty(field).objectReferenceValue = value; serialized.ApplyModifiedPropertiesWithoutUndo(); }
    }
}
