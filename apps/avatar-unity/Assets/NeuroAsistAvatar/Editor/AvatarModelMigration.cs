using System.Collections.Generic;
using NeuroAsist.Avatar;
using UniVRM10;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarModelMigration
    {
        private const string ScenePath = "Assets/Scenes/AvatarOverlay.unity";
        private const string IrisPath = "Assets/IRIS.vrm";

        [MenuItem("Iris/Avatar/Replace Current Model With IRIS")]
        public static void ReplaceWithIris()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var irisPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(IrisPath);
            var oldVrm = Object.FindFirstObjectByType<Vrm10Instance>();
            if (irisPrefab == null || oldVrm == null)
            {
                Debug.LogError("[AvatarMigration] IRIS.vrm or the current avatar instance is missing. Scene was not changed.");
                return;
            }

            var oldRoot = oldVrm.transform.root;
            var preservedChildren = DetachSceneOnlyChildren(oldRoot);
            var replacement = (GameObject)PrefabUtility.InstantiatePrefab(irisPrefab, scene);
            replacement.name = "IRIS";
            replacement.transform.SetPositionAndRotation(oldRoot.position, oldRoot.rotation);
            replacement.transform.localScale = oldRoot.localScale;
            foreach (var child in preservedChildren) child.SetParent(replacement.transform, true);

            Object.DestroyImmediate(oldRoot.gameObject);
            // Setup() intentionally reloads the canonical scene. Persist the replacement first,
            // otherwise that reload would restore the previous avatar from disk.
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AvatarRuntimeSetup.Setup();
            EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());
            EditorSceneManager.SaveOpenScenes();
            AssetDatabase.SaveAssets();
            Debug.Log("[AvatarMigration] IRIS is now the active avatar. Motion, expressions and lip sync were rebound.");
        }

        private static List<Transform> DetachSceneOnlyChildren(Transform root)
        {
            var result = new List<Transform>();
            for (var i = root.childCount - 1; i >= 0; i--)
            {
                var child = root.GetChild(i);
                if (PrefabUtility.GetCorrespondingObjectFromSource(child.gameObject) != null) continue;
                child.SetParent(null, true);
                result.Add(child);
            }
            return result;
        }
    }
}
