class NeuroVadProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.frameSamples = Math.max(1, Math.round(sampleRate * 0.020));
    this.gain = 1;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length || !channels[0]?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let mono = 0;
      for (let channel = 0; channel < channels.length; channel++) mono += channels[channel][i] || 0;
      this.pending.push(mono / channels.length);
    }
    while (this.pending.length >= this.frameSamples) {
      const samples = this.pending.splice(0, this.frameSamples);
      const pcm = new Int16Array(samples.length);
      let inputSum = 0;
      for (let i = 0; i < samples.length; i++) inputSum += samples[i] * samples[i];
      const inputRms = Math.sqrt(inputSum / samples.length);
      if (inputRms > 0.0025) {
        const targetGain = Math.max(0.65, Math.min(2.0, 0.045 / inputRms));
        this.gain += (targetGain - this.gain) * 0.12;
      } else {
        this.gain += (1 - this.gain) * 0.04;
      }
      for (let i = 0; i < samples.length; i++) {
        const amplified = Math.max(-1.2, Math.min(1.2, samples[i] * this.gain));
        const value = Math.tanh(amplified * 1.25);
        pcm[i] = Math.round(value * 32767);
      }
      this.port.postMessage({
        // VAD needs the physical microphone level.  The adaptive gain below
        // improves STT input, but using its amplified value here makes quiet
        // breaths look like speech and causes accidental barge-ins.
        rms: inputRms,
        pcm: pcm.buffer,
        sampleRate,
        inputChannels: channels.length,
      }, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('neuro-vad', NeuroVadProcessor);
