using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarPostureTests
    {
        private static void Offline(Scene scene,LoadSceneMode mode)
        {
            foreach (var ws in Object.FindObjectsByType<AvatarWebSocketClient>(FindObjectsSortMode.None)) ws.enabled=false;
            foreach (var overlay in Object.FindObjectsByType<WindowsDesktopOverlay>(FindObjectsSortMode.None)) overlay.enabled=false;
        }
        private static IEnumerator Load()
        {
            SceneManager.sceneLoaded+=Offline;SceneManager.LoadScene("AvatarOverlay");yield return null;SceneManager.sceneLoaded-=Offline;
        }
        internal static void AssertRelaxedLoweredHands(AvatarPostureProbe probe,string context)
        {
            foreach(var left in new[]{true,false})
            {
                var label=context+(left?" left":" right");
                Assert.That(left?probe.LeftForearm:probe.RightForearm,Is.InRange(-10f,18f),label+" forearm must not flare outward\n"+probe.Arms.DescribeArms()+"\n"+probe.Arms.Diagnostic(left));
                var hand=left?probe.LeftHand:probe.RightHand;
                Assert.That(Mathf.Abs(hand.x),Is.InRange(.13f,.20f),label+" hand hangs beside the hip: "+hand);
                Assert.That(hand.y,Is.InRange(-.05f,.07f),label+" hand remains lowered");
                Assert.That(hand.z,Is.InRange(-.20f,-.09f),label+" hand has a modest rear offset, not a folded-back pose: "+hand);
            }
        }
        [UnityTest,Timeout(120000)] public IEnumerator RestAndHeadOnlyCuesKeepTheOriginalNarrowArmSilhouette()
        {
            yield return Load();
            var motion=Object.FindFirstObjectByType<AvatarMotionController>();motion.enabled=false;
            var state=Object.FindFirstObjectByType<AvatarStateController>();
            var arms=Object.FindFirstObjectByType<AvatarArmRig>();
            var gestures=Object.FindFirstObjectByType<AvatarGestureController>();
            var probe=new GameObject("Posture probe").AddComponent<AvatarPostureProbe>();probe.Arms=arms;probe.Filter=Object.FindFirstObjectByType<AvatarPoseFilter>();
            var previousRate=Time.captureFramerate;Time.captureFramerate=30;
            try
            {
                foreach (var presence in new[]{AvatarState.Idle,AvatarState.Listening,AvatarState.Thinking,AvatarState.Speaking})
                {
                    state.SetState(presence,false);
                    for(var i=0;i<180;i++)
                    {
                        yield return null;
                        if(i<90)continue;
                        Assert.That(probe.LeftAbduction,Is.InRange(-10f,20f),presence+" left resting sleeve flares");
                        Assert.That(probe.RightAbduction,Is.InRange(-10f,20f),presence+" right resting sleeve flares");
                        Assert.That(probe.Clearance,Is.GreaterThanOrEqualTo(-.003f),"Narrow rest must remain outside clothing");
                        AssertRelaxedLoweredHands(probe,presence.ToString());
                    }
                }
                state.SetState(AvatarState.Idle,false);
                Assert.That(gestures.Trigger(GestureTag.Agreement,AvatarEmotion.Neutral,false,.9f,true),Is.True);
                while(gestures.IsPlaying)
                {
                    yield return null;
                    Assert.That(probe.LeftAbduction,Is.InRange(-10f,20f),"A head-only cue cannot widen the arms");
                    Assert.That(probe.RightAbduction,Is.InRange(-10f,20f),"A head-only cue cannot widen the arms");
                    AssertRelaxedLoweredHands(probe,"Head-only cue");
                }
                Assert.That(gestures.Trigger(GestureTag.Explanation,AvatarEmotion.Neutral,false,.9f,true),Is.True);
                while(gestures.IsPlaying)yield return null;
                for(var i=0;i<90;i++)yield return null;
                Assert.That(probe.LeftAbduction,Is.InRange(-10f,20f),"Left arm returns to narrow rest after a real stroke\n"+arms.DescribeArms());
                Assert.That(probe.RightAbduction,Is.InRange(-10f,20f),"Right arm returns to narrow rest after a real stroke");
                AssertRelaxedLoweredHands(probe,"After explanation");
            }
            finally{Time.captureFramerate=previousRate;Object.Destroy(probe.gameObject);}
        }
        [UnityTest,Timeout(120000)] public IEnumerator CombinedNeckAndHeadStayInsideConversationalLimitsUnderExtremeInputs()
        {
            yield return Load();
            var motion=Object.FindFirstObjectByType<AvatarMotionController>();motion.enabled=false;
            var filter=Object.FindFirstObjectByType<AvatarPoseFilter>();
            var injector=new GameObject("Extreme source neck/head input").AddComponent<AvatarPostureStress>();
            injector.Head=motion.Animator.GetBoneTransform(HumanBodyBones.Head);injector.Neck=motion.Animator.GetBoneTransform(HumanBodyBones.Neck);
            injector.HeadRest=injector.Head.localRotation;injector.NeckRest=injector.Neck.localRotation;
            var probe=new GameObject("Final head probe").AddComponent<AvatarPostureProbe>();probe.Filter=filter;
            var previousRate=Time.captureFramerate;
            try
            {
                foreach(var fps in new[]{24,60})
                {
                    Time.captureFramerate=fps;
                    for(var i=0;i<fps*7;i++)
                    {
                        injector.Pose=i/(fps/2)%4;yield return null;
                        var a=probe.HeadAngles;
                        Assert.That(a.x,Is.InRange(-16.1f,26.1f),"Head pitch after all layers");
                        Assert.That(Mathf.Abs(a.y),Is.LessThanOrEqualTo(32.1f),"Head yaw after neck + gesture + gaze");
                        Assert.That(Mathf.Abs(a.z),Is.LessThanOrEqualTo(12.1f),"Head cannot roll upside down");
                        var budget=Mathf.Pow(a.x/(a.x>=0?26:16),2)+Mathf.Pow(a.y/32,2)+Mathf.Pow(a.z/12,2);
                        Assert.That(budget,Is.LessThanOrEqualTo(1.02f),"Combined anatomical rotation budget");
                    }
                }
            }
            finally{Time.captureFramerate=previousRate;Object.Destroy(injector.gameObject);Object.Destroy(probe.gameObject);}
        }
    }
    [DefaultExecutionOrder(250)] public sealed class AvatarPostureStress:MonoBehaviour
    {
        public Transform Head,Neck;public Quaternion HeadRest,NeckRest;public int Pose;
        private void LateUpdate()
        {
            var a=Pose==0?new Vector3(80,150,120):Pose==1?new Vector3(-85,-170,-150):Pose==2?new Vector3(0,180,180):new Vector3(50,-120,90);
            Neck.localRotation=NeckRest*Quaternion.Euler(a*.6f);Head.localRotation=HeadRest*Quaternion.Euler(a);
        }
    }
    [DefaultExecutionOrder(12000)] public sealed class AvatarPostureProbe:MonoBehaviour
    {
        public AvatarArmRig Arms;public AvatarPoseFilter Filter;
        public Vector3 HeadAngles,LeftHand,RightHand;public float LeftAbduction,RightAbduction,LeftForearm,RightForearm,Clearance;
        private void LateUpdate()
        {
            if(Filter!=null)HeadAngles=Filter.MeasureHeadAngles();
            if(Arms==null)return;
            LeftAbduction=Arms.MeasureArmAbduction(true);RightAbduction=Arms.MeasureArmAbduction(false);
            LeftForearm=Arms.MeasureForearmAbduction(true);RightForearm=Arms.MeasureForearmAbduction(false);
            LeftHand=Arms.MeasureHandPosition(true);RightHand=Arms.MeasureHandPosition(false);
            Clearance=Mathf.Min(Arms.MeasureBodyClearance(true),Arms.MeasureBodyClearance(false));
        }
    }
}
