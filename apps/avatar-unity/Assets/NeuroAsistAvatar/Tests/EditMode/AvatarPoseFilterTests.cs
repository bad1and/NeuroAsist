using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarPoseFilterTests
    {
        [TestCase(24)] [TestCase(30)] [TestCase(60)] [TestCase(120)]
        public void SoftAccelerationSurvivesReversalAndSettlesAtEveryFrameRate(int fps)
        {
            var value = Quaternion.identity; var velocity = Vector3.zero; var acceleration = Vector3.zero;
            var dt = 1f / fps;
            for (var i = 0; i < fps * 5; i++)
            {
                var target = i < fps / 2 ? Quaternion.Euler(75, -40, 15) : Quaternion.Euler(-35, 25, -10);
                var before = value; var beforeVelocity = velocity; var beforeAcceleration = acceleration;
                value = AvatarPoseFilter.DampRotation(value, target, ref velocity, ref acceleration, dt, .15f, 120, 700);
                Assert.That(AvatarPoseFilter.RotationDisplacement(value * Quaternion.Inverse(before)).magnitude / dt, Is.LessThanOrEqualTo(120.1f));
                Assert.That((velocity - beforeVelocity).magnitude / dt, Is.LessThanOrEqualTo(700.1f));
                Assert.That((acceleration - beforeAcceleration).magnitude / dt, Is.LessThanOrEqualTo(28001));
                if (i > fps * 4) Assert.That(AvatarPoseFilter.RotationDisplacement(target * Quaternion.Inverse(value)).magnitude, Is.LessThan(.005f));
            }
        }
        [TestCase(.005f)] [TestCase(-.005f)]
        public void TinyRotationsReachRestWithoutAQuaternionDeadZone(float degrees)
        {
            var value = Quaternion.identity; var velocity = Vector3.zero; var acceleration = Vector3.zero;
            var target = Quaternion.AngleAxis(degrees, new Vector3(1, 2, 3).normalized);
            for (var i = 0; i < 240; i++)
                value = AvatarPoseFilter.DampRotation(value, target, ref velocity, ref acceleration, 1f / 120, .18f, 60, 350);
            // Quaternion.Angle itself rounds tiny rotations to zero, so measure
            // the vector part rather than allowing the same bug into the test.
            var error = AvatarPoseFilter.RotationDisplacement(target * Quaternion.Inverse(value)).magnitude;
            Assert.That(error, Is.LessThan(.0001f));
            var opposite = new Quaternion(-target.x, -target.y, -target.z, -target.w);
            Assert.That(Vector3.Distance(AvatarPoseFilter.RotationDisplacement(target), AvatarPoseFilter.RotationDisplacement(opposite)), Is.LessThan(.00001f));
        }
        [Test] public void SpringAccelerationBuildsGraduallyAndReversesContinuously()
        {
            var velocity = Vector3.zero; var acceleration = Vector3.zero; const float dt = 1f / 120;
            for (var i = 0; i < 360; i++)
            {
                var previous = acceleration;
                velocity = AvatarPoseFilter.SpringVelocity(Vector3.up * (i < 15 ? 100 : -100), velocity, ref acceleration, dt, 85, 18.5f, 95, 320);
                Assert.That((acceleration - previous).magnitude, Is.LessThanOrEqualTo(320 * 40 * dt + .001f));
                Assert.That(acceleration.magnitude, Is.LessThanOrEqualTo(320));
                Assert.That(velocity.magnitude, Is.LessThanOrEqualTo(95));
                if (i == 0) Assert.That(acceleration.y, Is.InRange(100, 110), "First frame must not jump to full acceleration");
                if (i == 15) Assert.That(acceleration.y, Is.GreaterThan(0), "Reversal must brake the previous motion first");
            }
        }
        [Test] public void PausedRotationPreservesItsMotionState()
        {
            var value = Quaternion.Euler(15, 25, -10); var velocity = Vector3.one; var acceleration = Vector3.up;
            var result = AvatarPoseFilter.DampRotation(value, Quaternion.identity, ref velocity, ref acceleration, 0, .18f, 60, 350);
            Assert.That(result, Is.EqualTo(value));
            Assert.That(velocity, Is.EqualTo(Vector3.one));
            Assert.That(acceleration, Is.EqualTo(Vector3.up));
        }
        [TestCase(24)] [TestCase(30)] [TestCase(60)] [TestCase(120)]
        public void AbruptTargetsHaveBoundedSpeedAndAccelerationAndSettle(int fps)
        {
            var value = Quaternion.identity; var velocity = Vector3.zero;
            var dt = 1f / fps;
            for (var i = 0; i < fps * 4; i++)
            {
                var target = Quaternion.Euler(i < fps ? 150 : -100, i < fps ? -80 : 60, 40);
                var before = value; var beforeVelocity = velocity;
                value = AvatarPoseFilter.DampRotation(value, target, ref velocity, dt, .12f, 180, 1400);
                Assert.That(Quaternion.Angle(before, value) / dt, Is.LessThanOrEqualTo(181));
                Assert.That((velocity - beforeVelocity).magnitude / dt, Is.LessThanOrEqualTo(1401));
                if (i > fps * 3) Assert.That(Quaternion.Angle(value, target), Is.LessThan(.15f));
            }
        }
        [Test] public void WristLimitsUseBindAxesAndBothQuaternionSigns()
        {
            var rest = Quaternion.Euler(13, 54, -32); var axis = new Vector3(.8f, .2f, -.1f).normalized;
            var swingAxis = Vector3.Cross(axis, Vector3.up).normalized;
            var pose = rest * Quaternion.AngleAxis(95, swingAxis) * Quaternion.AngleAxis(140, axis);
            var clamped = AvatarPoseFilter.LimitJoint(pose, rest, axis, 50, 20);
            var opposite = new Quaternion(-pose.x, -pose.y, -pose.z, -pose.w);
            Assert.That(Quaternion.Angle(clamped, AvatarPoseFilter.LimitJoint(opposite, rest, axis, 50, 20)), Is.LessThan(.05f));
            Assert.That(Quaternion.Angle(clamped, rest), Is.LessThan(55));
            Assert.That(Quaternion.Angle(clamped, AvatarPoseFilter.LimitJoint(clamped, rest, axis, 50, 20)), Is.LessThan(.05f));
        }
    }
}
