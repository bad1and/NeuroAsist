using System;
using NeuroAsist.Avatar;
using UniVRM10;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarIrisValidation
    {
        private const string ScenePath = "Assets/Scenes/AvatarOverlay.unity";
        private const string IrisPath = "Assets/IRIS.vrm";

        public static void Validate()
        {
            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var vrm = UnityEngine.Object.FindFirstObjectByType<Vrm10Instance>();
            var audio = GameObject.Find("LipSyncAudio");
            var animator = vrm != null ? vrm.GetComponentInChildren<Animator>() : null;
            var lipSync = audio != null ? audio.GetComponent<global::uLipSync.uLipSync>() : null;
            var bridge = audio != null ? audio.GetComponent<Vrm10PhonemeLipSync>() : null;
            var presentation = UnityEngine.Object.FindFirstObjectByType<AvatarPresentationController>();
            var settings = AssetDatabase.LoadAssetAtPath<AvatarRuntimeSettings>("Assets/NeuroAsistAvatar/AvatarRuntimeSettings.asset");
            var source = vrm == null ? string.Empty : AssetDatabase.GetAssetPath(PrefabUtility.GetCorrespondingObjectFromSource(vrm.gameObject));

            if (vrm == null || !string.Equals(source, IrisPath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Active avatar is not Assets/IRIS.vrm.");
            if (animator == null || animator.runtimeAnimatorController == null)
                throw new InvalidOperationException("IRIS Animator Controller is missing.");
            if (lipSync == null || bridge == null || lipSync.onLipSyncUpdate.GetPersistentEventCount() != 1)
                throw new InvalidOperationException("uLipSync-to-VRM phoneme bridge is not configured.");
            if (presentation == null || settings == null || settings.ApplyAvatarLowProfile)
                throw new InvalidOperationException("High-quality avatar presentation is not configured.");

            var controller = animator.runtimeAnimatorController as UnityEditor.Animations.AnimatorController;
            if (controller == null) throw new InvalidOperationException("AvatarMotion Controller is not editable.");
            foreach (var layer in controller.layers)
                foreach (var child in layer.stateMachine.states)
                    if (child.state.name != "Empty" && child.state.motion == null)
                        throw new InvalidOperationException("Animator state has no clip: " + child.state.name);
            Debug.Log("[AvatarValidation] IRIS, lip sync bridge and all motion slots validated.");
        }
    }
}
