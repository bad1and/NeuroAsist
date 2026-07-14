using System;
using NUnit.Framework;
using UnityEngine;

namespace NeuroAsist.Avatar.Tests
{
    public sealed class AvatarAudioPlayerTests
    {
        [Test]
        public void DecodesPcm16MonoWav()
        {
            var clip = WavClipDecoder.Decode(CreatePcm16Wav(new short[] { 0, 16384, -16384 }), "test");
            try
            {
                Assert.That(clip.channels, Is.EqualTo(1));
                Assert.That(clip.frequency, Is.EqualTo(16000));
                Assert.That(clip.samples, Is.EqualTo(3));
            }
            finally { UnityEngine.Object.DestroyImmediate(clip); }
        }

        [Test]
        public void RejectsCorruptedWav()
        {
            Assert.That(() => WavClipDecoder.Decode(new byte[44], "bad"), Throws.ArgumentException);
        }

        [Test]
        public void RejectsNonPcm16Wav()
        {
            var wav = CreatePcm16Wav(new short[] { 0 });
            BitConverter.GetBytes((short)8).CopyTo(wav, 34);
            Assert.That(() => WavClipDecoder.Decode(wav, "bad-format"), Throws.ArgumentException);
        }

        private static byte[] CreatePcm16Wav(short[] samples)
        {
            const int channels = 1;
            const int sampleRate = 16000;
            var bytes = new byte[44 + samples.Length * sizeof(short)];
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("RIFF"), 0, bytes, 0, 4);
            BitConverter.GetBytes(bytes.Length - 8).CopyTo(bytes, 4);
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("WAVEfmt "), 0, bytes, 8, 8);
            BitConverter.GetBytes(16).CopyTo(bytes, 16);
            BitConverter.GetBytes((short)1).CopyTo(bytes, 20);
            BitConverter.GetBytes((short)channels).CopyTo(bytes, 22);
            BitConverter.GetBytes(sampleRate).CopyTo(bytes, 24);
            BitConverter.GetBytes(sampleRate * channels * sizeof(short)).CopyTo(bytes, 28);
            BitConverter.GetBytes((short)(channels * sizeof(short))).CopyTo(bytes, 32);
            BitConverter.GetBytes((short)16).CopyTo(bytes, 34);
            Array.Copy(System.Text.Encoding.ASCII.GetBytes("data"), 0, bytes, 36, 4);
            BitConverter.GetBytes(samples.Length * sizeof(short)).CopyTo(bytes, 40);
            Buffer.BlockCopy(samples, 0, bytes, 44, samples.Length * sizeof(short));
            return bytes;
        }
    }
}
