using NeuroAsist.Avatar;
using UnityEditor;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarWelcomeSetup
    {
        public const string ClipPath = "Assets/NeuroAsistAvatar/Animations/X Bot@Welcome Floor.fbx";

        public static void Configure(GameObject root, Animator animator, AvatarPresentationController presentation)
        {
            var seated = ImportClip(ClipPath);
            var welcome = root.GetComponent<AvatarWelcomeController>() ?? root.AddComponent<AvatarWelcomeController>();
            welcome.Configure(animator, presentation, seated, false);
            EditorUtility.SetDirty(welcome);
            if (seated == null) Debug.LogWarning("[AvatarWelcome] Import the documented Mixamo seated idle FBX to enable the welcome pose; portrait remains available.");
        }

        public static AnimationClip ImportClip(string path)
        {
            var importer = AssetImporter.GetAtPath(path) as ModelImporter;
            AnimationClip seated = null;
            if (importer != null)
            {
                importer.animationType = ModelImporterAnimationType.Human;
                importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
                importer.animationCompression = ModelImporterAnimationCompression.Off;
                importer.materialImportMode = ModelImporterMaterialImportMode.None;
                importer.importCameras = false;
                importer.importLights = false;
                var clips = importer.defaultClipAnimations;
                foreach (var clip in clips)
                {
                    clip.name = "WelcomeSittingIdle";
                    clip.loopTime = true;
                    clip.loopPose = true;
                    clip.lockRootRotation = true;
                    clip.lockRootHeightY = true;
                    clip.lockRootPositionXZ = true;
                    clip.keepOriginalOrientation = true;
                    clip.keepOriginalPositionY = true;
                    clip.keepOriginalPositionXZ = true;
                }
                importer.clipAnimations = clips;
                importer.SaveAndReimport();
                foreach (var asset in AssetDatabase.LoadAllAssetsAtPath(path))
                    if (asset is AnimationClip candidate && !candidate.name.StartsWith("__preview__")) { seated = candidate; break; }
            }
            return seated;
        }
    }
}
