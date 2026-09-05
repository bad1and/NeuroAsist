using System.Collections.Generic;
using NeuroAsist.Avatar;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace NeuroAsist.AvatarEditor
{
    public static class AvatarMotionSetup
    {
        internal const string Root = "Assets/NeuroAsistAvatar/Motion";
        internal const string SettingsPath = Root + "/AvatarMotionSettings.asset";
        internal const string ControllerPath = Root + "/AvatarMotion.controller";
        internal const string MaskPath = Root + "/UpperBody.mask";

        [MenuItem("Iris/Avatar/Setup Motion Assets")]
        public static void SetupAssets()
        {
            EnsureFolders();
            ConfigureIncludedClipImporters();
            var settings = EnsureSettings();
            RepairLegacyIdleProfiles(settings);
            var controller = EnsureController();
            EnsureGestureVariants(settings, controller);
            var mask = EnsureMask();
            if (controller.layers.Length > 1) { var layers = controller.layers; layers[1].avatarMask = mask; controller.layers = layers; }
            AssignIncludedClips(controller);
            EditorUtility.SetDirty(settings);
            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();
            Debug.Log("[AvatarMotion] Motion assets and included Mixamo clips are configured. Run Setup Canonical Scene to assign the controller to the VRM Animator.");
        }

        internal static AvatarMotionSettings EnsureSettings()
        {
            EnsureFolders();
            var settings = AssetDatabase.LoadAssetAtPath<AvatarMotionSettings>(SettingsPath);
            if (settings == null)
            {
                settings = ScriptableObject.CreateInstance<AvatarMotionSettings>();
                var neutral = CreateProfile("Neutral", "neutral", 1f, 1f, 1f);
                settings.DefaultProfile = neutral;
                AssetDatabase.CreateAsset(settings, SettingsPath);
            }

            var existingEmotions = new HashSet<AvatarEmotion>();
            foreach (var ep in settings.EmotionProfiles) if (ep != null) existingEmotions.Add(ep.Emotion);

            foreach (var item in new[] {
                (AvatarEmotion.Neutral, settings.DefaultProfile ?? CreateProfile("Neutral", "neutral", 1f, 1f, 1f)),
                (AvatarEmotion.Happy, CreateProfile("Happy", "happy", 1.15f, 1.2f, 1.05f)),
                (AvatarEmotion.Sad, CreateProfile("Sad", "sad", .55f, .75f, .8f)),
                (AvatarEmotion.Angry, CreateProfile("Angry", "angry", .9f, 1.1f, 1.2f)),
                (AvatarEmotion.Surprised, CreateProfile("Surprised", "surprised", 1.05f, 1.05f, 1.1f)),
                (AvatarEmotion.Relaxed, CreateProfile("Relaxed", "relaxed", .65f, .8f, .8f)),
                (AvatarEmotion.Thinking, CreateProfile("Thinking", "thinking", .6f, .75f, .85f)),
                (AvatarEmotion.Annoyed, CreateProfile("Annoyed", "annoyed", .8f, .9f, 1.1f)),
                (AvatarEmotion.Smirk, CreateProfile("Smirk", "smirk", .9f, 1f, 1f)),
                (AvatarEmotion.Embarrassed, CreateProfile("Embarrassed", "embarrassed", .65f, .75f, .85f)),
                (AvatarEmotion.Concerned, CreateProfile("Concerned", "concerned", .7f, .85f, .9f)),
                (AvatarEmotion.Playful, CreateProfile("Playful", "playful", 1.0f, 1.05f, 1.0f)),
                (AvatarEmotion.Pouting, CreateProfile("Pouting", "pouting", .7f, .9f, 1.1f)),
                (AvatarEmotion.Wink, CreateProfile("Wink", "wink", 1.1f, 1.0f, 1.0f)),
                (AvatarEmotion.Wink_Left, CreateProfile("WinkLeft", "wink_left", 1.1f, 1.0f, 1.0f)),
                (AvatarEmotion.Skeptical, CreateProfile("Skeptical", "skeptical", .75f, .85f, .95f)),
                (AvatarEmotion.Proud, CreateProfile("Proud", "proud", 1.0f, 1.05f, 1.1f)),
                (AvatarEmotion.Sleepy, CreateProfile("Sleepy", "sleepy", .45f, .6f, .7f)),
                (AvatarEmotion.Excited, CreateProfile("Excited", "excited", 1.25f, 1.25f, 1.15f)),
                (AvatarEmotion.Shocked, CreateProfile("Shocked", "shocked", 1.1f, 1.15f, 1.2f)),
                (AvatarEmotion.Touched, CreateProfile("Touched", "touched", .7f, .85f, .95f)),
                (AvatarEmotion.Teasing, CreateProfile("Teasing", "teasing", .95f, 1.0f, 1.0f)),
                (AvatarEmotion.Curious, CreateProfile("Curious", "curious", .85f, .95f, 1.05f)),
                (AvatarEmotion.Confused, CreateProfile("Confused", "confused", .75f, .85f, .95f)),
            })
            {
                if (!existingEmotions.Contains(item.Item1))
                {
                    settings.EmotionProfiles.Add(new EmotionMotionProfile { Emotion = item.Item1, Profile = item.Item2 });
                }
            }

            var existingTags = new HashSet<GestureTag>();
            foreach (var g in settings.GestureDefinitions) if (g != null) existingTags.Add(g.Tag);

            foreach (var tag in new[] {
                GestureTag.Talk, GestureTag.Greeting, GestureTag.Agreement, GestureTag.Disagreement,
                GestureTag.Question, GestureTag.Explanation, GestureTag.Thinking, GestureTag.Surprise,
                GestureTag.Frustration, GestureTag.Farewell, GestureTag.Shrug,
                GestureTag.Greeting_Right, GestureTag.Greeting_Left, GestureTag.Greeting_Casual,
                GestureTag.Farewell_Right, GestureTag.Farewell_Left, GestureTag.Farewell_Casual,
                GestureTag.Thinking_Right, GestureTag.Thinking_Left,
                GestureTag.Question_Right, GestureTag.Question_Left,
                GestureTag.Explanation_Right, GestureTag.Explanation_Left,
                GestureTag.Talk_Right, GestureTag.Talk_Left, GestureTag.Nod
            })
            {
                if (!existingTags.Contains(tag))
                {
                    settings.GestureDefinitions.Add(CreateGesture(tag));
                }
            }
            return settings;
        }

        private static MotionProfile CreateProfile(string name, string id, float gestureFrequency, float intensity, float headWeight)
        {
            var path = Root + "/Profiles/" + name + "MotionProfile.asset";
            var existing = AssetDatabase.LoadAssetAtPath<MotionProfile>(path);
            if (existing != null) return existing;
            var profile = ScriptableObject.CreateInstance<MotionProfile>();
            profile.ProfileId = id; profile.GestureFrequencyMultiplier = gestureFrequency; profile.GestureIntensityMultiplier = intensity; profile.HeadLookWeight = headWeight;
            profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleLookWander", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Wander, Category = IdleCategory.Micro, DurationSeconds = 4.5f, CooldownSeconds = 25f });
            profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleSideGlance", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.SideGlance, Category = IdleCategory.Micro, DurationSeconds = 3.5f, CooldownSeconds = 25f });
            profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleThoughtfulLook", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Thoughtful, Category = IdleCategory.Micro, DurationSeconds = 4f, CooldownSeconds = 30f });
            profile.AlternativeIdleProbability = .35f;
            profile.IdleIntervalMinSeconds = 16f;
            profile.IdleIntervalMaxSeconds = 32f;
            AssetDatabase.CreateAsset(profile, path);
            return profile;
        }

        private static GestureDefinition CreateGesture(GestureTag tag)
        {
            var path = Root + "/Gestures/" + tag + ".asset";
            var existing = AssetDatabase.LoadAssetAtPath<GestureDefinition>(path);
            if (existing != null) return existing;
            var value = ScriptableObject.CreateInstance<GestureDefinition>();
            value.Id = tag + "Gesture";
            value.Tag = tag;
            switch (tag)
            {
                case GestureTag.Talk:
                case GestureTag.Talk_Right:
                    value.AnimatorState = "TalkGesture01"; break;
                case GestureTag.Talk_Left:
                    value.AnimatorState = "TalkGesture01Mirror"; break;
                case GestureTag.Greeting:
                case GestureTag.Greeting_Right:
                    value.AnimatorState = "Greeting"; break;
                case GestureTag.Greeting_Left:
                    value.AnimatorState = "GreetingMirror"; break;
                case GestureTag.Greeting_Casual:
                    value.AnimatorState = "GreetingCasual"; break;
                case GestureTag.Farewell:
                case GestureTag.Farewell_Right:
                    value.AnimatorState = "Farewell"; break;
                case GestureTag.Farewell_Left:
                    value.AnimatorState = "FarewellMirror"; break;
                case GestureTag.Farewell_Casual:
                    value.AnimatorState = "FarewellCasual"; break;
                case GestureTag.Thinking:
                case GestureTag.Thinking_Right:
                    value.AnimatorState = "Thinking"; break;
                case GestureTag.Thinking_Left:
                    value.AnimatorState = "ThinkingMirror"; break;
                case GestureTag.Question:
                case GestureTag.Question_Right:
                    value.AnimatorState = "Question"; break;
                case GestureTag.Question_Left:
                    value.AnimatorState = "QuestionMirror"; break;
                case GestureTag.Explanation:
                case GestureTag.Explanation_Right:
                    value.AnimatorState = "Explanation"; break;
                case GestureTag.Explanation_Left:
                    value.AnimatorState = "ExplanationMirror"; break;
                case GestureTag.Nod:
                    value.AnimatorState = "Agreement"; break;
                default:
                    value.AnimatorState = tag.ToString(); break;
            }
            value.Priority = tag == GestureTag.Greeting || tag == GestureTag.Farewell
                || tag == GestureTag.Greeting_Right || tag == GestureTag.Greeting_Left
                || tag == GestureTag.Greeting_Casual || tag == GestureTag.Farewell_Right
                || tag == GestureTag.Farewell_Left || tag == GestureTag.Farewell_Casual ? 50 : 10;
            value.HeadLookSuppression = tag == GestureTag.Thinking || tag == GestureTag.Thinking_Right || tag == GestureTag.Thinking_Left ? .3f : 0f;
            AssetDatabase.CreateAsset(value, path);
            return value;
        }

        private static AnimatorController EnsureController()
        {
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath);
            if (controller == null) controller = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            if (!HasParameter(controller, "IsSpeaking")) controller.AddParameter("IsSpeaking", AnimatorControllerParameterType.Bool);
            if (!HasParameter(controller, "MotionIntensity")) controller.AddParameter("MotionIntensity", AnimatorControllerParameterType.Float);
            if (!HasParameter(controller, "BaseIdle")) controller.AddParameter("BaseIdle", AnimatorControllerParameterType.Int);

            var baseMachine = controller.layers[0].stateMachine;
            AddStates(baseMachine, new[] { "IdleNeutral", "IdleRelaxed", "IdleEnergetic", "IdleSad", "IdleThinking", "IdleLookAround", "IdleShiftWeight", "IdleSmallStretch" }, "IdleNeutral");

            if (controller.layers.Length < 2) controller.AddLayer(AvatarMotionNames.GestureLayer);
            var layers = controller.layers;
            AddStates(layers[1].stateMachine, new[] {
                "Empty", "TalkGesture01", "Greeting", "GreetingCasual", "Agreement", "Disagreement",
                "Question", "Explanation", "Thinking", "Surprise", "Frustration", "Farewell", "FarewellCasual", "Shrug"
            }, "Empty");
            controller.layers = layers;
            return controller;
        }

        private static bool HasParameter(AnimatorController controller, string name)
        {
            foreach (var p in controller.parameters) if (p.name == name) return true;
            return false;
        }

        private static void AssignIncludedClips(AnimatorController controller)
        {
            var clips = new Dictionary<string, AnimationClip>();
            foreach (var item in new[] {
                "X Bot@Idle", "X Bot@Thinking",
                "X Bot@Talking", "X Bot@TalkingQuestion", "X Bot@Waving", "X Bot@WavingGoodbye", "X Bot@Agreeing",
                "X Bot@Shaking Head No", "X Bot@Shrugging", "X Bot@Surprised", "X Bot@Angry",
            })
            {
                var path = "Assets/NeuroAsistAvatar/Animations/" + item + ".fbx";
                foreach (var asset in AssetDatabase.LoadAllAssetsAtPath(path))
                    if (asset is AnimationClip clip && !clip.name.StartsWith("__preview__")) { clips[item] = clip; break; }
            }

            var assignments = new Dictionary<string, string>
            {
                ["IdleNeutral"] = "X Bot@Idle",
                // All persistent base states begin from the same stationary pose. Emotional
                // movement is an upper-body gesture, otherwise crossfading between arbitrary
                // Mixamo entry poses makes the portrait visibly pop or slide its feet.
                ["IdleRelaxed"] = "X Bot@Idle",
                ["IdleEnergetic"] = "X Bot@Idle",
                ["IdleSad"] = "X Bot@Idle",
                ["IdleThinking"] = "X Bot@Idle",
                ["IdleLookAround"] = "X Bot@Idle",
                ["IdleShiftWeight"] = "X Bot@Idle",
                ["IdleSmallStretch"] = "X Bot@Idle",
                ["TalkGesture01"] = "X Bot@Talking",
                ["Greeting"] = "X Bot@Waving",
                ["GreetingCasual"] = "X Bot@Talking",
                ["Agreement"] = "X Bot@Agreeing",
                ["Disagreement"] = "X Bot@Shaking Head No",
                ["Question"] = "X Bot@TalkingQuestion",
                ["Explanation"] = "X Bot@Talking",
                ["Thinking"] = "X Bot@Thinking",
                ["Surprise"] = "X Bot@Surprised",
                ["Frustration"] = "X Bot@Angry",
                ["Farewell"] = "X Bot@WavingGoodbye",
                ["FarewellCasual"] = "X Bot@Talking",
                ["Shrug"] = "X Bot@Shrugging",
                ["Nod"] = "X Bot@Agreeing",
            };
            foreach (var layer in controller.layers) AssignLayerClips(layer.stateMachine, assignments, clips);
        }
        private static void ConfigureIncludedClipImporters()
        {
            var looping = new HashSet<string> { "X Bot@Idle", "X Bot@Talking", "X Bot@TalkingQuestion" };
            foreach (var item in new[] {
                "X Bot@Idle", "X Bot@Thinking", "X Bot@Talking", "X Bot@TalkingQuestion", "X Bot@Waving",
                "X Bot@WavingGoodbye", "X Bot@Agreeing", "X Bot@Shaking Head No", "X Bot@Shrugging",
                "X Bot@Surprised", "X Bot@Angry",
            })
            {
                var path = "Assets/NeuroAsistAvatar/Animations/" + item + ".fbx";
                var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null) continue;
                importer.animationType = ModelImporterAnimationType.Human;
                importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
                importer.animationCompression = ModelImporterAnimationCompression.Off;
                var clips = importer.defaultClipAnimations;
                foreach (var clip in clips)
                {
                    var isLoop = looping.Contains(item);
                    clip.loopTime = isLoop;
                    clip.keepOriginalOrientation = true;
                    clip.keepOriginalPositionY = true;
                    clip.keepOriginalPositionXZ = true;
                }
                importer.clipAnimations = clips;
                importer.SaveAndReimport();
            }
        }
        private static void RepairLegacyIdleProfiles(AvatarMotionSettings settings)
        {
            if (settings == null) return;
            var profiles = new List<MotionProfile> { settings.DefaultProfile };
            foreach (var mapping in settings.EmotionProfiles) if (mapping != null) profiles.Add(mapping.Profile);
            var repaired = new HashSet<MotionProfile>();
            foreach (var profile in profiles)
            {
                if (profile == null || !repaired.Add(profile)) continue;
                profile.AlternativeIdles.Clear();
                profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleLookWander", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Wander, Category = IdleCategory.Micro, DurationSeconds = 4.5f, CooldownSeconds = 25f });
                profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleSideGlance", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.SideGlance, Category = IdleCategory.Micro, DurationSeconds = 3.5f, CooldownSeconds = 25f });
                profile.AlternativeIdles.Add(new AlternativeIdleDefinition { Id = "IdleThoughtfulLook", AnimatorState = AvatarMotionNames.DefaultIdleState, LookPattern = IdleLookPattern.Thoughtful, Category = IdleCategory.Micro, DurationSeconds = 4f, CooldownSeconds = 30f });
                profile.AlternativeIdleProbability = .35f;
                profile.IdleIntervalMinSeconds = 16f;
                profile.IdleIntervalMaxSeconds = 32f;
                EditorUtility.SetDirty(profile);
            }
        }
        private static void EnsureGestureVariants(AvatarMotionSettings settings, AnimatorController controller)
        {
            if (settings == null || controller == null || controller.layers.Length < 2) return;
            var safe = new HashSet<GestureTag> {
                GestureTag.Talk, GestureTag.Question, GestureTag.Thinking, GestureTag.Explanation,
                GestureTag.Agreement, GestureTag.Disagreement, GestureTag.Shrug,
                GestureTag.Greeting, GestureTag.Greeting_Casual, GestureTag.Farewell, GestureTag.Farewell_Casual,
                GestureTag.Surprise, GestureTag.Frustration, GestureTag.Nod,
            };
            var machine = controller.layers[1].stateMachine;
            foreach (var definition in settings.GestureDefinitions)
            {
                if (definition == null || !safe.Contains(definition.Tag)) continue;
                var mirrorName = definition.AnimatorState + "Mirror";
                var mirror = FindState(machine, mirrorName);
                if (mirror == null)
                {
                    mirror = machine.AddState(mirrorName);
                    mirror.mirror = true;
                }
                if (!definition.VariantAnimatorStates.Contains(mirrorName))
                {
                    definition.VariantAnimatorStates.Add(mirrorName);
                    EditorUtility.SetDirty(definition);
                }
            }
        }
        private static void AssignLayerClips(AnimatorStateMachine machine, IDictionary<string, string> assignments, IDictionary<string, AnimationClip> clips)
        {
            foreach (var child in machine.states)
            {
                var stateName = child.state.name.EndsWith("Mirror")
                    ? child.state.name.Substring(0, child.state.name.Length - "Mirror".Length)
                    : child.state.name;
                if (assignments.TryGetValue(stateName, out var assetName) && clips.TryGetValue(assetName, out var clip)) child.state.motion = clip;
            }
            foreach (var child in machine.stateMachines) AssignLayerClips(child.stateMachine, assignments, clips);
        }
        private static AnimatorState FindState(AnimatorStateMachine machine, string name)
        {
            foreach (var child in machine.states) if (child.state.name == name) return child.state;
            return null;
        }

        private static void AddStates(AnimatorStateMachine machine, IEnumerable<string> names, string defaultName)
        {
            var statesToRemove = new List<ChildAnimatorState>();
            foreach (var child in machine.states)
            {
                var sName = child.state.name;
                var spaceIdx = sName.LastIndexOf(' ');
                if (spaceIdx > 0 && int.TryParse(sName.Substring(spaceIdx + 1), out _))
                {
                    statesToRemove.Add(child);
                }
            }
            foreach (var child in statesToRemove)
            {
                machine.RemoveState(child.state);
            }

            foreach (var name in names)
            {
                var existing = FindState(machine, name);
                if (existing == null)
                {
                    var state = machine.AddState(name);
                    if (name == defaultName) machine.defaultState = state;
                }
                else if (name == defaultName && machine.defaultState == null)
                {
                    machine.defaultState = existing;
                }
            }
        }

        private static AvatarMask EnsureMask()
        {
            var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(MaskPath);
            if (mask == null) { mask = new AvatarMask(); AssetDatabase.CreateAsset(mask, MaskPath); }
            // LastBodyPart is a sentinel enum value. Passing it to AvatarMask produces
            // Unity's "Invalid BodyPart Index" error, so configure real parts explicitly.
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.Root, false);
            // Mixamo clips frequently animate Hips/Body even in a seemingly upper-body
            // gesture. Keeping Body off prevents an overlay clip from lowering or
            // rotating the avatar while the base idle owns the stance.
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.Body, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.Head, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftLeg, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightLeg, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftArm, true);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightArm, true);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftFingers, true);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightFingers, true);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftFootIK, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightFootIK, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftHandIK, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightHandIK, false);
            EditorUtility.SetDirty(mask);
            return mask;
        }
        private static void EnsureFolders()
        {
            if (!AssetDatabase.IsValidFolder(Root)) AssetDatabase.CreateFolder("Assets/NeuroAsistAvatar", "Motion");
            if (!AssetDatabase.IsValidFolder(Root + "/Profiles")) AssetDatabase.CreateFolder(Root, "Profiles");
            if (!AssetDatabase.IsValidFolder(Root + "/Gestures")) AssetDatabase.CreateFolder(Root, "Gestures");
        }
    }
}
