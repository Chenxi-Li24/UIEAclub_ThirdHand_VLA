/**
 * TTS Player — browser-side MP3 playback via Web Audio API.
 *
 * Receives base64-encoded MP3 data (from ``assistant.audio`` voice-protocol
 * messages) and plays it through a dedicated ``AudioContext``.
 *
 * Usage::
 *
 *   import { TTSPlayer } from './tts-player.js';
 *
 *   const player = new TTSPlayer({ onState: s => console.log(s) });
 *   await player.init();                                // user-gesture safe
 *   await player.playBase64(base64String, 'audio/mpeg'); // play MP3
 *   player.stop();                                       // stop mid-playback
 *   await player.dispose();                              // cleanup
 */

export class TTSPlayer {
  /**
   * @param {object} [options]
   * @param {(state: 'playing'|'idle'|'error') => void} [options.onState]
   * @param {number} [options.sampleRate]  — AudioContext sample rate (default: system default)
   * @param {string} [options.sinkId]      — output device ID ('' = system default)
   */
  constructor(options = {}) {
    this.onState = options.onState || (() => {});
    /** @type {AudioContext|null} */
    this.audioContext = null;
    /** @type {AudioBufferSourceNode|null} */
    this._source = null;
    this._playbackGeneration = 0;
    this._sampleRate = options.sampleRate || undefined;
    this._sinkId = options.sinkId || '';
  }

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  /** Create (or re-create) the AudioContext.  Idempotent. */
  async init() {
    if (this.audioContext && this.audioContext.state !== 'closed') return;
    try {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)(
        this._sampleRate ? { sampleRate: this._sampleRate } : undefined
      );
      // Apply stored sink on fresh AudioContext.
      if (this._sinkId && typeof this.audioContext.setSinkId === 'function') {
        try { await this.audioContext.setSinkId(this._sinkId); } catch (_) {}
      }
    } catch (err) {
      console.warn('[TTSPlayer] AudioContext creation failed:', err);
      this.audioContext = null;
    }
  }

  /**
   * Route audio to a specific output device.
   *
   * @param {string} deviceId  — device ID from enumerateDevices, or '' for default
   */
  async setSinkId(deviceId) {
    this._sinkId = deviceId;
    if (!this.audioContext) return;
    if (typeof this.audioContext.setSinkId !== 'function') return;
    try {
      await this.audioContext.setSinkId(deviceId || '');
    } catch (err) {
      console.warn('[TTSPlayer] setSinkId failed:', err);
    }
  }

  /** Ensure AudioContext is ready to play (resume if suspended). */
  async _ensureReady() {
    if (!this.audioContext) await this.init();
    if (!this.audioContext) throw new Error('AudioContext unavailable');
    if (this.audioContext.state === 'suspended') {
      try {
        await this.audioContext.resume();
      } catch (err) {
        console.warn('[TTSPlayer] AudioContext resume failed:', err);
        throw err;
      }
    }
  }

  // ------------------------------------------------------------------
  // Playback
  // ------------------------------------------------------------------

  /**
   * Decode a base64-encoded audio blob and start playback.
   *
   * @param {string} base64Data  — raw base64 MP3 bytes
   * @param {string} [format]    — MIME type (default ``"audio/mpeg"``)
   * @returns {Promise<void>}    — resolves when playback *starts* (not when it ends)
   */
  async playBase64(base64Data, format = 'audio/mpeg') {
    if (!base64Data) return;

    const playbackGeneration = ++this._playbackGeneration;
    await this._ensureReady();
    if (playbackGeneration !== this._playbackGeneration) return;

    // Stop any currently-playing source first (last utterance wins).
    this._stopSource();

    // Decode base64 → raw bytes
    let raw;
    try {
      const binary = atob(base64Data);
      raw = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        raw[i] = binary.charCodeAt(i);
      }
    } catch (err) {
      console.warn('[TTSPlayer] base64 decode failed:', err);
      this.onState('error');
      throw err;
    }

    // Decode audio
    let audioBuffer;
    try {
      audioBuffer = await this.audioContext.decodeAudioData(raw.buffer.slice(0));
    } catch (err) {
      if (playbackGeneration !== this._playbackGeneration) return;
      console.warn('[TTSPlayer] decodeAudioData failed:', err);
      this.onState('error');
      throw err;
    }
    if (playbackGeneration !== this._playbackGeneration) return;

    // Play
    try {
      const source = this.audioContext.createBufferSource();
      this._source = source;
      source.buffer = audioBuffer;
      source.connect(this.audioContext.destination);
      source.onended = () => {
        try { source.disconnect(); } catch (_) { /* noop */ }
        if (this._source === source) {
          this._source = null;
          this.onState('idle');
        }
      };
      source.start();
      this.onState('playing');
    } catch (err) {
      console.warn('[TTSPlayer] playback start failed:', err);
      this.onState('error');
      throw err;
    }
  }

  /** Stop any currently-playing audio immediately. */
  stop() {
    this._playbackGeneration += 1;
    this._stopSource();
  }

  _stopSource() {
    const source = this._source;
    if (!source) return;
    this._source = null;
    source.onended = null;
    try {
      source.stop();
    } catch (_) {
      // Already stopped — fine.
    }
    try {
      source.disconnect();
    } catch (_) {
      // Already disconnected — fine.
    }
    this.onState('idle');
  }

  /** Release the AudioContext.  Call when tearing down the voice panel. */
  async dispose() {
    this.stop();
    if (this.audioContext && this.audioContext.state !== 'closed') {
      try {
        await this.audioContext.close();
      } catch (_) {
        // Browser may have already closed it.
      }
    }
    this.audioContext = null;
  }
}
