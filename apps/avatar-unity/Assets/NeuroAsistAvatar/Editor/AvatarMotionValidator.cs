using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using System.Linq;

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
                var controller = animator.runtimeAnimatorController as AnimatorController;
                var gestureLayer = controller == null ? -1 : System.Array.FindIndex(controller.layers, layer => layer.name == AvatarMotionNames.GestureLayer);
                if (gestureLayer < 0) { Error("Animator Gesture Layer is missing."); errors++; }
                if (!HasParameter(animator, "IsSpeaking", AnimatorControllerParameterType.Bool)) { Error("Animator parameter IsSpeaking is missing."); errors++; }
                if (!HasParameter(animator, "GesturePlaybackSpeed", AnimatorControllerParameterType.Float)) { Error("Animator parameter GesturePlaybackSpeed is missing."); errors++; }
                if (gestureLayer >= 0 && controller.layers[gestureLayer].defaultWeight > .001f) Debug.LogWarning("[AvatarMotion] Gesture layer is weighted before runtime startup.");
            }
            if (AssetDatabase.LoadAssetAtPath<AvatarMask>(AvatarMotionSetup.MaskPath) == null) { Error("UpperBody AvatarMask is missing."); errors++; }
            if (settings != null)
            {
                foreach (var profile in settings.EmotionProfiles) if (profile.Profile == null) { Error("Emotion profile mapping is empty: " + profile.Emotion); errors++; }
                foreach (var definition in settings.GestureDefinitions)
                    if (definition == null) { Error("Gesture definition reference is empty."); errors++; }
                    else
                    {
                        var minimum = AvatarGestureLibrary.RequiredPatterns(definition.Tag);
                        if (definition.Variants.Select(v => v.PatternId).Distinct().Count() < minimum) { Error("Insufficient distinct performances: " + definition.Id); errors++; }
                        foreach (var variant in definition.Variants)
                            if (variant.Clip == null || !variant.Clip.humanMotion || !StateHasMotion(animator, variant.AnimatorState)) { Error("Invalid Humanoid performance: " + variant.Id); errors++; }
                    }
            }
            if (errors > 0) throw new System.InvalidOperationException("[AvatarMotion] Validation failed with " + errors + " error(s).");
            Debug.Log("[AvatarMotion] Validated all performance clips, variants and Animator states.");
        }
        private static bool HasParameter(Animator animator, string name, AnimatorControllerParameterType type)
        {
            var controller = animator.runtimeAnimatorController as AnimatorController;
            if (controller == null) return false;
            foreach (var parameter in controller.parameters) if (parameter.name == name && parameter.type == type) return true;
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
