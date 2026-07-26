using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarMotionValidator
    {
        [MenuItem("Iris/Avatar/Validate Avatar Motion Setup")]
        public static void Validate()
        {
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(AvatarMotionSetup.SettingsPath);
            var motion = Object.FindFirstObjectByType<AvatarMotionController>();
            var animator = motion != null ? motion.Animator : null;
            var errors = 0;
            if (motion == null) { Error("AvatarMotionController is missing from NeuroAsistAvatarRuntime."); errors++; }
            if (settings == null || settings.DefaultProfile == null) { Error("AvatarMotionSettings/default profile is missing."); errors++; }
            if (animator == null || animator.runtimeAnimatorController == null) { Error("Animator controller is missing."); errors++; }
            else
            {
                var gestureLayer = animator.GetLayerIndex(AvatarMotionNames.GestureLayer);
                if (gestureLayer < 0) { Error("Animator Gesture Layer is missing."); errors++; }
                if (!HasParameter(animator, "IsSpeaking", AnimatorControllerParameterType.Bool)) { Error("Animator parameter IsSpeaking is missing."); errors++; }
                if (gestureLayer >= 0 && animator.GetLayerWeight(gestureLayer) > 0.001f) Debug.LogWarning("[AvatarMotion] Gesture layer is weighted before runtime startup.");
            }
            if (AssetDatabase.LoadAssetAtPath<AvatarMask>(AvatarMotionSetup.MaskPath) == null) { Error("UpperBody AvatarMask is missing."); errors++; }
            if (settings != null)
            {
                foreach (var profile in settings.EmotionProfiles) if (profile.Profile == null) { Error("Emotion profile mapping is empty: " + profile.Emotion); errors++; }
                foreach (var definition in settings.GestureDefinitions)
                    if (definition == null) { Error("Gesture definition reference is empty."); errors++; }
                    else if (!StateHasMotion(animator, definition.AnimatorState)) Debug.LogWarning("[AvatarMotion] Gesture slot has no assigned AnimationClip: " + definition.Id);
            }
            Debug.Log(errors == 0 ? "[AvatarMotion] Validation passed; clip-slot warnings require manual Mixamo assignment." : "[AvatarMotion] Validation failed with " + errors + " error(s).");
        }
        private static bool HasParameter(Animator animator, string name, AnimatorControllerParameterType type)
        {
            foreach (var parameter in animator.parameters) if (parameter.name == name && parameter.type == type) return true;
            return false;
        }
        private static bool StateHasMotion(Animator animator, string stateName)
        {
            if (animator == null || !(animator.runtimeAnimatorController is AnimatorController controller)) return false;
            foreach (var layer in controller.layers)
                foreach (var state in layer.stateMachine.states)
                    if (state.state.name == stateName) return state.state.motion != null;
            return false;
        }
        private static void Error(string message) => Debug.LogError("[AvatarMotion] " + message);
    }
}
