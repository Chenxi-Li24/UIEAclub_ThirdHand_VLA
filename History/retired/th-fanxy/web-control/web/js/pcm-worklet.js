class ThirdHandPcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.pendingLength = 0;
    this.flushAt = 2048;
  }

  process(inputs) {
    const input = inputs[0];
    const channel = input && input[0];
    if (!channel || channel.length === 0) return true;

    this.pending.push(new Float32Array(channel));
    this.pendingLength += channel.length;

    if (this.pendingLength >= this.flushAt) {
      const samples = new Float32Array(this.pendingLength);
      let offset = 0;
      for (const chunk of this.pending) {
        samples.set(chunk, offset);
        offset += chunk.length;
      }
      this.pending = [];
      this.pendingLength = 0;
      this.port.postMessage({ samples }, [samples.buffer]);
    }

    return true;
  }
}

registerProcessor('thirdhand-pcm-capture', ThirdHandPcmCaptureProcessor);
