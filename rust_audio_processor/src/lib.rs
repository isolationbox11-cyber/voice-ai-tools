use std::f32::consts::PI;
use wasm_bindgen::prelude::*;

mod fft;

pub use fft::FFTProcessor;

#[wasm_bindgen]
pub struct AudioProcessor {
    sample_rate: f32,
}

#[wasm_bindgen]
impl AudioProcessor {
    #[wasm_bindgen(constructor)]
    pub fn new(sample_rate: f32) -> AudioProcessor {
        AudioProcessor { sample_rate }
    }

    /// Apply noise gate to audio buffer
    #[wasm_bindgen]
    pub fn apply_noise_gate(&self, audio_buffer: &mut [f32], threshold: f32) {
        for sample in audio_buffer.iter_mut() {
            if sample.abs() < threshold {
                *sample = 0.0;
            }
        }
    }

    /// Normalize audio volume
    #[wasm_bindgen]
    pub fn normalize_audio(&self, audio_buffer: &mut [f32], target_level: f32) {
        let max_sample = audio_buffer.iter().map(|s| s.abs()).fold(0.0, f32::max);
        if max_sample > 0.0 {
            let scale = target_level / max_sample;
            for sample in audio_buffer.iter_mut() {
                *sample *= scale;
            }
        }
    }

    /// Apply simple low-pass filter for noise reduction
    #[wasm_bindgen]
    pub fn apply_low_pass_filter(&self, audio_buffer: &mut [f32], cutoff_freq: f32) {
        let alpha = (2.0 * std::f32::consts::PI * cutoff_freq / self.sample_rate).exp();
        let mut prev_sample = 0.0;

        for sample in audio_buffer.iter_mut() {
            *sample = alpha * prev_sample + (1.0 - alpha) * *sample;
            prev_sample = *sample;
        }
    }

    /// Apply simple high-pass filter
    #[wasm_bindgen]
    pub fn apply_high_pass_filter(&self, audio_buffer: &mut [f32], cutoff_freq: f32) {
        let alpha = (2.0 * std::f32::consts::PI * cutoff_freq / self.sample_rate).exp();
        let mut prev_sample = 0.0;
        let mut prev_output = 0.0;

        for sample in audio_buffer.iter_mut() {
            let output = alpha * prev_output + (1.0 - alpha) * (*sample - prev_sample);
            prev_sample = *sample;
            prev_output = output;
            *sample = output;
        }
    }

    /// Apply pitch shift using simple time-domain method
    #[wasm_bindgen]
    pub fn apply_pitch_shift(&self, audio_buffer: &[f32], shift_factor: f32) -> Vec<f32> {
        if shift_factor == 1.0 {
            return audio_buffer.to_vec();
        }

        let new_length = (audio_buffer.len() as f32 / shift_factor) as usize;
        let mut result = vec![0.0; new_length];

        for i in 0..new_length {
            let src_index = (i as f32 * shift_factor) as usize;
            if src_index < audio_buffer.len() {
                result[i] = audio_buffer[src_index];
            }
        }

        result
    }

    /// Apply compression to reduce dynamic range
    #[wasm_bindgen]
    pub fn apply_compression(&self, audio_buffer: &mut [f32], threshold: f32, ratio: f32) {
        for sample in audio_buffer.iter_mut() {
            let abs_sample = sample.abs();
            if abs_sample > threshold {
                let excess = abs_sample - threshold;
                let compressed = threshold + excess / ratio;
                *sample = sample.signum() * compressed;
            }
        }
    }

    /// Calculate RMS (Root Mean Square) for audio level
    #[wasm_bindgen]
    pub fn calculate_rms(&self, audio_buffer: &[f32]) -> f32 {
        let sum_squares: f32 = audio_buffer.iter().map(|s| s * s).sum();
        (sum_squares / audio_buffer.len() as f32).sqrt()
    }

    /// Remove silence from beginning and end of audio
    #[wasm_bindgen]
    pub fn trim_silence(&self, audio_buffer: &[f32], silence_threshold: f32) -> Vec<f32> {
        let mut start = 0;
        let mut end = audio_buffer.len();

        // Find start
        for (i, &sample) in audio_buffer.iter().enumerate() {
            if sample.abs() > silence_threshold {
                start = i;
                break;
            }
        }

        // Find end
        for (i, &sample) in audio_buffer.iter().enumerate().rev() {
            if sample.abs() > silence_threshold {
                end = i + 1;
                break;
            }
        }

        if start < end {
            audio_buffer[start..end].to_vec()
        } else {
            audio_buffer.to_vec()
        }
    }

    /// Apply fade in at beginning
    #[wasm_bindgen]
    pub fn apply_fade_in(&self, audio_buffer: &mut [f32], duration_samples: usize) {
        let fade_len = duration_samples.min(audio_buffer.len());
        for i in 0..fade_len {
            audio_buffer[i] *= (i as f32 / fade_len as f32);
        }
    }

    /// Apply fade out at end
    #[wasm_bindgen]
    pub fn apply_fade_out(&self, audio_buffer: &mut [f32], duration_samples: usize) {
        let fade_len = duration_samples.min(audio_buffer.len());
        let start = audio_buffer.len() - fade_len;
        for i in 0..fade_len {
            audio_buffer[start + i] *= (1.0 - i as f32 / fade_len as f32);
        }
    }

    /// Apply reverb effect
    #[wasm_bindgen]
    pub fn apply_reverb(&self, audio_buffer: &mut [f32], decay: f32, delay_samples: usize) {
        let delay = delay_samples.min(audio_buffer.len());
        let mut delayed = vec![0.0; audio_buffer.len()];

        for i in delay..audio_buffer.len() {
            delayed[i] = audio_buffer[i - delay] * decay;
        }

        for i in 0..audio_buffer.len() {
            audio_buffer[i] += delayed[i];
        }
    }

    /// Apply chorus effect
    #[wasm_bindgen]
    pub fn apply_chorus(
        &self,
        audio_buffer: &mut [f32],
        depth: f32,
        rate: f32,
        delay_samples: usize,
    ) {
        let delay = delay_samples.min(audio_buffer.len());
        let mut chorus = vec![0.0; audio_buffer.len()];

        for i in delay..audio_buffer.len() {
            chorus[i] = audio_buffer[i - delay] * depth;
        }

        for i in 0..audio_buffer.len() {
            audio_buffer[i] = audio_buffer[i] * (1.0 - depth) + chorus[i];
        }
    }

    /// Apply flanger effect
    #[wasm_bindgen]
    pub fn apply_flanger(&self, audio_buffer: &mut [f32], depth: f32, delay_samples: usize) {
        let delay = delay_samples.min(audio_buffer.len());
        let mut flanger = vec![0.0; audio_buffer.len()];

        for i in delay..audio_buffer.len() {
            flanger[i] = audio_buffer[i - delay] * depth;
        }

        for i in 0..audio_buffer.len() {
            audio_buffer[i] += flanger[i];
        }
    }

    /// Apply tremolo effect (amplitude modulation)
    #[wasm_bindgen]
    pub fn apply_tremolo(&self, audio_buffer: &mut [f32], rate: f32, depth: f32) {
        for (i, sample) in audio_buffer.iter_mut().enumerate() {
            let modulation = (2.0 * PI * rate * i as f32 / self.sample_rate).sin();
            *sample *= 1.0 + depth * modulation;
        }
    }

    /// Apply vibrato effect (frequency modulation)
    #[wasm_bindgen]
    pub fn apply_vibrato(&self, audio_buffer: &[f32], rate: f32, depth: f32) -> Vec<f32> {
        let mut result = vec![0.0; audio_buffer.len()];

        for (i, &sample) in audio_buffer.iter().enumerate() {
            let modulation = (2.0 * PI * rate * i as f32 / self.sample_rate).sin();
            let pitch_shift = 1.0 + depth * modulation;
            let src_index = (i as f32 / pitch_shift) as usize;

            if src_index < audio_buffer.len() {
                result[i] = audio_buffer[src_index];
            }
        }

        result
    }

    /// Apply distortion effect
    #[wasm_bindgen]
    pub fn apply_distortion(&self, audio_buffer: &mut [f32], amount: f32) {
        for sample in audio_buffer.iter_mut() {
            let abs_sample = sample.abs();
            if abs_sample > 0.0 {
                let sign = sample.signum();
                let distorted = abs_sample.powf(1.0 + amount);
                *sample = sign * distorted;
            }
        }
    }

    /// Apply wah-wah effect
    #[wasm_bindgen]
    pub fn apply_wah_wah(&self, audio_buffer: &mut [f32], rate: f32, min_freq: f32, max_freq: f32) {
        for (i, sample) in audio_buffer.iter_mut().enumerate() {
            let lfo = (2.0 * PI * rate * i as f32 / self.sample_rate).sin();
            let cutoff_freq = min_freq + (max_freq - min_freq) * (lfo + 1.0) / 2.0;
            let alpha = (2.0 * PI * cutoff_freq / self.sample_rate).exp();

            static mut prev_sample: f32 = 0.0;
            let current = *sample;
            *sample = alpha * unsafe { prev_sample } + (1.0 - alpha) * current;
            unsafe { prev_sample = current };
        }
    }

    /// Apply echo effect
    #[wasm_bindgen]
    pub fn apply_echo(&self, audio_buffer: &mut [f32], delay_samples: usize, decay: f32) {
        let delay = delay_samples.min(audio_buffer.len());
        let mut echo = vec![0.0; audio_buffer.len()];

        for i in delay..audio_buffer.len() {
            echo[i] = audio_buffer[i - delay] * decay;
        }

        for i in 0..audio_buffer.len() {
            audio_buffer[i] += echo[i];
        }
    }

    /// Apply voice formant filtering
    #[wasm_bindgen]
    pub fn apply_formant_filter(&self, audio_buffer: &mut [f32], f1: f32, f2: f32, f3: f32) {
        // Simple formant simulation using band-pass filters
        let formants = [f1, f2, f3];

        for &formant_freq in &formants {
            let alpha = (2.0 * PI * formant_freq / self.sample_rate).exp();
            let mut prev_sample = 0.0;

            for sample in audio_buffer.iter_mut() {
                let filtered = alpha * prev_sample + (1.0 - alpha) * *sample;
                prev_sample = *sample;
                *sample = filtered;
            }
        }
    }

    /// Apply telephone effect (band-pass filter 300-3400Hz)
    #[wasm_bindgen]
    pub fn apply_telephone_effect(&self, audio_buffer: &mut [f32]) {
        // Apply low-pass at 3400Hz
        let low_alpha = (2.0 * PI * 3400.0 / self.sample_rate).exp();
        let mut low_prev = 0.0;

        for sample in audio_buffer.iter_mut() {
            let filtered = low_alpha * low_prev + (1.0 - low_alpha) * *sample;
            low_prev = *sample;
            *sample = filtered;
        }

        // Apply high-pass at 300Hz
        let high_alpha = (2.0 * PI * 300.0 / self.sample_rate).exp();
        let mut high_prev = 0.0;
        let mut high_output = 0.0;

        for sample in audio_buffer.iter_mut() {
            let filtered = high_alpha * high_output + (1.0 - high_alpha) * (*sample - high_prev);
            high_prev = *sample;
            high_output = filtered;
            *sample = filtered;
        }
    }
}

#[wasm_bindgen]
pub fn process_audio(audio_buffer: &mut [f32], sample_rate: f32) -> AudioProcessor {
    AudioProcessor::new(sample_rate)
}

#[wasm_bindgen]
pub fn get_version() -> String {
    "0.1.0".to_string()
}
