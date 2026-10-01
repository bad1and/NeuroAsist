using System.IO;
using UnityEditor;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarBuild
    {
        public static void BuildWindows()
        {
            // The avatar is a ScriptedImporter asset.  When this project is first
            // cloned, Unity may parse the scene before compiling that importer and
            // leave IRIS as a "Missing Prefab" in Library.  Reimport it before
            // opening the canonical scene so its stable GUID resolves correctly.
            AssetDatabase.ImportAsset("Assets/IRIS.vrm", ImportAssetOptions.ForceUpdate);
            AssetDatabase.SaveAssets();
            AvatarRuntimeSetup.Setup();
            var output = Path.GetFullPath(Path.Combine("Builds", "NeuroAsistAvatar", "NeuroAsistAvatar.exe"));
            // Allow verification builds beside an avatar currently owned by Tauri.
            var args = System.Environment.GetCommandLineArgs();
            for (var i = 0; i + 1 < args.Length; i++)
                if (args[i] == "-avatarOutput") output = Path.GetFullPath(args[i + 1]);
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            if (File.Exists(output))
            {
                File.Delete(output);
            }
            var report = BuildPipeline.BuildPlayer(
                EditorBuildSettings.scenes,
                output,
                BuildTarget.StandaloneWindows64,
                BuildOptions.None
            );
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                throw new System.Exception("NeuroAsist Avatar Windows build failed: " + report.summary.result);
        }
    }
}
