// Rust WASM Audio Processor Integration for Chrome Extension
// Provides real-time audio processing using compiled Rust code

let audioProcessor = null;
let audioProcessorInitialized = false;

// Load the Rust WASM module
async function loadAudioProcessor() {
    if (audioProcessorInitialized) return audioProcessor;
    
    try {
        const module = await import('./pkg/audio_processor.js');
        await module.default();
        audioProcessor = module;
        audioProcessorInitialized = true;
        console.log('✅ Rust audio processor loaded successfully');
        return audioProcessor;
    } catch (error) {
        console.error('❌ Failed to load Rust audio processor:', error);
        console.log('📝 Falling back to JavaScript audio processing');
        return null;
    }
}

// Audio processing functions using Rust WASM
class AudioProcessorWASM {
    constructor(sampleRate = 44100) {
        this.sampleRate = sampleRate;
        this.processor = null;
    }

    async init() {
        this.processor = await loadAudioProcessor();
        if (this.processor) {
            this.rustProcessor = new this.processor.AudioProcessor(this.sampleRate);
        }
    }

    // Apply noise gate to remove background noise
    async applyNoiseGate(audioBuffer, threshold = 0.05) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            this.rustProcessor.apply_noise_gate(float32Array, threshold);
            return audioBuffer;
        }
        // Fallback to JavaScript
        return this.jsApplyNoiseGate(audioBuffer, threshold);
    }

    // Normalize audio volume
    async normalizeAudio(audioBuffer, targetLevel = 0.8) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            this.rustProcessor.normalize_audio(float32Array, targetLevel);
            return audioBuffer;
        }
        // Fallback to JavaScript
        return this.jsNormalizeAudio(audioBuffer, targetLevel);
    }

    // Apply low-pass filter for noise reduction
    async applyLowPassFilter(audioBuffer, cutoffFreq = 1000) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            this.rustProcessor.apply_low_pass_filter(float32Array, cutoffFreq);
            return audioBuffer;
        }
        // Fallback to JavaScript
        return this.jsApplyLowPassFilter(audioBuffer, cutoffFreq);
    }

    // Apply pitch shift
    async applyPitchShift(audioBuffer, shiftFactor = 1.0) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            const shifted = this.rustProcessor.apply_pitch_shift(float32Array, shiftFactor);
            const newBuffer = new AudioContext().createBuffer(1, shifted.length, this.sampleRate);
            newBuffer.getChannelData(0).set(shifted);
            return newBuffer;
        }
        // Fallback to JavaScript
        return this.jsApplyPitchShift(audioBuffer, shiftFactor);
    }

    // Apply compression
    async applyCompression(audioBuffer, threshold = 0.5, ratio = 4.0) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            this.rustProcessor.apply_compression(float32Array, threshold, ratio);
            return audioBuffer;
        }
        // Fallback to JavaScript
        return this.jsApplyCompression(audioBuffer, threshold, ratio);
    }

    // Trim silence from audio
    async trimSilence(audioBuffer, silenceThreshold = 0.01) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            const trimmed = this.rustProcessor.trim_silence(float32Array, silenceThreshold);
            const newBuffer = new AudioContext().createBuffer(1, trimmed.length, this.sampleRate);
            newBuffer.getChannelData(0).set(trimmed);
            return newBuffer;
        }
        // Fallback to JavaScript
        return this.jsTrimSilence(audioBuffer, silenceThreshold);
    }

    // Calculate RMS for audio level
    async calculateRMS(audioBuffer) {
        if (this.rustProcessor) {
            const float32Array = audioBuffer.getChannelData(0);
            return this.rustProcessor.calculate_rms(float32Array);
        }
        // Fallback to JavaScript
        return this.jsCalculateRMS(audioBuffer);
    }

    // Process voice sample for training
    async processVoiceSample(audioBuffer) {
        await this.init();
        
        // Apply processing pipeline
        let processed = await this.trimSilence(audioBuffer, 0.01);
        processed = await this.applyNoiseGate(processed, 0.05);
        processed = await this.normalizeAudio(processed, 0.8);
        processed = await this.applyLowPassFilter(processed, 8000);
        
        return processed;
    }

    // JavaScript fallback implementations
    jsApplyNoiseGate(audioBuffer, threshold) {
        const channelData = audioBuffer.getChannelData(0);
        for (let i = 0; i < channelData.length; i++) {
            if (Math.abs(channelData[i]) < threshold) {
                channelData[i] = 0;
            }
        }
        return audioBuffer;
    }

    jsNormalizeAudio(audioBuffer, targetLevel) {
        const channelData = audioBuffer.getChannelData(0);
        let maxSample = 0;
        for (let i = 0; i < channelData.length; i++) {
            const abs = Math.abs(channelData[i]);
            if (abs > maxSample) maxSample = abs;
        }
        if (maxSample > 0) {
            const scale = targetLevel / maxSample;
            for (let i = 0; i < channelData.length; i++) {
                channelData[i] *= scale;
            }
        }
        return audioBuffer;
    }

    jsApplyLowPassFilter(audioBuffer, cutoffFreq) {
        const channelData = audioBuffer.getChannelData(0);
        const alpha = Math.exp(-2 * Math.PI * cutoffFreq / this.sampleRate);
        let prevSample = 0;
        
        for (let i = 0; i < channelData.length; i++) {
            channelData[i] = alpha * prevSample + (1 - alpha) * channelData[i];
            prevSample = channelData[i];
        }
        return audioBuffer;
    }

    jsApplyPitchShift(audioBuffer, shiftFactor) {
        const channelData = audioBuffer.getChannelData(0);
        const newLength = Math.floor(channelData.length / shiftFactor);
        const newBuffer = new AudioContext().createBuffer(1, newLength, this.sampleRate);
        const newChannelData = newBuffer.getChannelData(0);
        
        for (let i = 0; i < newLength; i++) {
            const srcIndex = Math.floor(i * shiftFactor);
            if (srcIndex < channelData.length) {
                newChannelData[i] = channelData[srcIndex];
            }
        }
        return newBuffer;
    }

    jsApplyCompression(audioBuffer, threshold, ratio) {
        const channelData = audioBuffer.getChannelData(0);
        for (let i = 0; i < channelData.length; i++) {
            const abs = Math.abs(channelData[i]);
            if (abs > threshold) {
                const excess = abs - threshold;
                const compressed = threshold + excess / ratio;
                channelData[i] = Math.sign(channelData[i]) * compressed;
            }
        }
        return audioBuffer;
    }

    jsTrimSilence(audioBuffer, silenceThreshold) {
        const channelData = audioBuffer.getChannelData(0);
        let start = 0;
        let end = channelData.length;
        
        for (let i = 0; i < channelData.length; i++) {
            if (Math.abs(channelData[i]) > silenceThreshold) {
                start = i;
                break;
            }
        }
        
        for (let i = channelData.length - 1; i >= 0; i--) {
            if (Math.abs(channelData[i]) > silenceThreshold) {
                end = i + 1;
                break;
            }
        }
        
        if (start < end) {
            const newBuffer = new AudioContext().createBuffer(1, end - start, this.sampleRate);
            const newChannelData = newBuffer.getChannelData(0);
            for (let i = 0; i < end - start; i++) {
                newChannelData[i] = channelData[start + i];
            }
            return newBuffer;
        }
        return audioBuffer;
    }

    jsCalculateRMS(audioBuffer) {
        const channelData = audioBuffer.getChannelData(0);
        let sumSquares = 0;
        for (let i = 0; i < channelData.length; i++) {
            sumSquares += channelData[i] * channelData[i];
        }
        return Math.sqrt(sumSquares / channelData.length);
    }
}

// Export for use in popup.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AudioProcessorWASM, loadAudioProcessor };
}
