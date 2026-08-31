export interface AudioBands {
  low: number;   // 20 - 250 Hz (bass/punch) [0.0 - 1.0]
  mid: number;   // 250 - 2500 Hz (vocal body) [0.0 - 1.0]
  high: number;  // 2500 - 8000 Hz (sibilance/clarity) [0.0 - 1.0]
  level: number; // overall RMS amplitude [0.0 - 1.0]
}

class AudioAnalyzerService {
  private analyser: AnalyserNode | null = null;
  private audioContext: AudioContext | null = null;
  private frequencyData: Uint8Array<ArrayBuffer> | null = null;
  private mediaElementSources = new WeakMap<HTMLAudioElement, MediaElementAudioSourceNode>();

  private smoothedBands: AudioBands = {
    low: 0,
    mid: 0,
    high: 0,
    level: 0,
  };

  /**
   * Initializes or returns the existing AnalyserNode for a given AudioContext.
   */
  getOrCreateAnalyser(context: AudioContext): AnalyserNode | null {
    if (typeof window === "undefined" || !context) return null;
    if (this.analyser && this.audioContext === context) {
      return this.analyser;
    }

    try {
      this.audioContext = context;
      this.analyser = context.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.6;
      this.frequencyData = new Uint8Array(this.analyser.frequencyBinCount);
      return this.analyser;
    } catch {
      return null;
    }
  }

  /**
   * Connects an HTMLAudioElement to the analyzer graph so playback is measured.
   */
  attachAudioElement(audio: HTMLAudioElement): void {
    if (typeof window === "undefined" || !audio) return;
    try {
      const AudioContextClass = window.AudioContext
        || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextClass) return;

      if (!this.audioContext || this.audioContext.state === "closed") {
        this.audioContext = new AudioContextClass();
      }
      const analyser = this.getOrCreateAnalyser(this.audioContext);
      if (!analyser) return;

      // Avoid creating multiple MediaElementSourceNodes for the same element
      let source = this.mediaElementSources.get(audio);
      if (!source) {
        source = this.audioContext.createMediaElementSource(audio);
        this.mediaElementSources.set(audio, source);
        source.connect(analyser);
        analyser.connect(this.audioContext.destination);
      }
    } catch {
      // Browsers may restrict MediaElementSource across origins or contexts
    }
  }

  /**
   * Samples the current frequency spectrum and returns smoothed band values.
   */
  getAudioBands(): AudioBands {
    if (!this.analyser || !this.frequencyData) {
      // Natural decay to 0 if no active audio
      this.smoothedBands.low *= 0.85;
      this.smoothedBands.mid *= 0.85;
      this.smoothedBands.high *= 0.85;
      this.smoothedBands.level *= 0.85;
      return { ...this.smoothedBands };
    }

    try {
      this.analyser.getByteFrequencyData(this.frequencyData);
      const binCount = this.frequencyData.length;
      if (binCount === 0) return { ...this.smoothedBands };

      // Map bins based on sampleRate (typically 44100 or 48000, bin width ~170-190Hz)
      const sampleRate = this.audioContext?.sampleRate ?? 44100;
      const binHz = (sampleRate / 2) / binCount;

      let lowSum = 0;
      let lowCount = 0;
      let midSum = 0;
      let midCount = 0;
      let highSum = 0;
      let highCount = 0;
      let totalSum = 0;

      for (let i = 0; i < binCount; i++) {
        const val = this.frequencyData[i] / 255;
        const freq = i * binHz;
        totalSum += val;

        if (freq < 300) {
          lowSum += val;
          lowCount++;
        } else if (freq < 2800) {
          midSum += val;
          midCount++;
        } else if (freq < 8000) {
          highSum += val;
          highCount++;
        }
      }

      const targetLow = lowCount > 0 ? (lowSum / lowCount) : 0;
      const targetMid = midCount > 0 ? (midSum / midCount) : 0;
      const targetHigh = highCount > 0 ? (highSum / highCount) : 0;
      const targetLevel = totalSum / binCount;

      // Fast attack (~15ms), smooth release (~100ms)
      const attack = 0.65;
      const decay = 0.18;

      this.smoothedBands.low += (targetLow - this.smoothedBands.low) * (targetLow > this.smoothedBands.low ? attack : decay);
      this.smoothedBands.mid += (targetMid - this.smoothedBands.mid) * (targetMid > this.smoothedBands.mid ? attack : decay);
      this.smoothedBands.high += (targetHigh - this.smoothedBands.high) * (targetHigh > this.smoothedBands.high ? attack : decay);
      this.smoothedBands.level += (targetLevel - this.smoothedBands.level) * (targetLevel > this.smoothedBands.level ? attack : decay);

      return { ...this.smoothedBands };
    } catch {
      return { ...this.smoothedBands };
    }
  }

  /**
   * Resets audio bands to silent state.
   */
  reset(): void {
    this.smoothedBands = { low: 0, mid: 0, high: 0, level: 0 };
  }
}

export const audioAnalyzer = new AudioAnalyzerService();
