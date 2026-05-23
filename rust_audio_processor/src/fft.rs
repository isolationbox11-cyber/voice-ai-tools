use wasm_bindgen::prelude::*;
use std::f32::consts::PI;

#[wasm_bindgen]
pub struct FFTProcessor {
    size: usize,
}

#[wasm_bindgen]
impl FFTProcessor {
    #[wasm_bindgen(constructor)]
    pub fn new(size: usize) -> FFTProcessor {
        FFTProcessor { size }
    }

    /// Compute FFT using Cooley-Tukey algorithm
    #[wasm_bindgen]
    pub fn compute_fft(&self, real: &[f32], imag: &[f32]) -> Vec<f32> {
        let n = real.len();
        if n != imag.len() || !n.is_power_of_two() {
            return vec![0.0; n];
        }

        let mut real_copy = real.to_vec();
        let mut imag_copy = imag.to_vec();
        
        self.fft_recursive(&mut real_copy, &mut imag_copy, n, 1);
        
        // Compute magnitudes
        let mut magnitudes = Vec::with_capacity(n / 2);
        for i in 0..n / 2 {
            let mag = (real_copy[i] * real_copy[i] + imag_copy[i] * imag_copy[i]).sqrt();
            magnitudes.push(mag);
        }
        
        magnitudes
    }

    fn fft_recursive(&self, real: &mut [f32], imag: &mut [f32], n: usize, s: usize) {
        if n == 1 {
            return;
        }

        let half = n / 2;
        self.fft_recursive(real, imag, half, 2 * s);
        self.fft_recursive(real, imag, half, 2 * s);

        for k in 0..half {
            let t = 2.0 * PI * k as f32 / n as f32;
            let cos_t = t.cos();
            let sin_t = t.sin();
            
            let idx1 = k * s;
            let idx2 = (k + half) * s;
            
            let t_real = real[idx2] * cos_t - imag[idx2] * sin_t;
            let t_imag = real[idx2] * sin_t + imag[idx2] * cos_t;
            
            real[idx2] = real[idx1] - t_real;
            imag[idx2] = imag[idx1] - t_imag;
            real[idx1] = real[idx1] + t_real;
            imag[idx1] = imag[idx1] + t_imag;
        }
    }

    /// Compute frequency bands for visualization
    #[wasm_bindgen]
    pub fn compute_frequency_bands(&self, magnitudes: &[f32], num_bands: usize) -> Vec<f32> {
        if magnitudes.is_empty() {
            return vec![0.0; num_bands];
        }

        let mut bands = vec![0.0; num_bands];
        let samples_per_band = magnitudes.len() / num_bands;
        
        for (i, band) in bands.iter_mut().enumerate() {
            let start = i * samples_per_band;
            let end = ((i + 1) * samples_per_band).min(magnitudes.len());
            
            if start < magnitudes.len() {
                let sum: f32 = magnitudes[start..end].iter().sum();
                *band = sum / (end - start) as f32;
            }
        }
        
        bands
    }

    /// Apply smoothing to frequency data
    #[wasm_bindgen]
    pub fn smooth_frequencies(&self, data: &mut [f32], smoothing_factor: f32) {
        if data.len() < 2 {
            return;
        }
        
        let mut prev = data[0];
        for i in 1..data.len() {
            let smoothed = prev * smoothing_factor + data[i] * (1.0 - smoothing_factor);
            prev = data[i];
            data[i] = smoothed;
        }
    }

    /// Detect peaks in frequency spectrum
    #[wasm_bindgen]
    pub fn detect_peaks(&self, data: &[f32], threshold: f32) -> Vec<usize> {
        let mut peaks = Vec::new();
        
        if data.len() < 3 {
            return peaks;
        }
        
        for i in 1..data.len() - 1 {
            if data[i] > threshold && data[i] > data[i - 1] && data[i] > data[i + 1] {
                peaks.push(i);
            }
        }
        
        peaks
    }

    /// Calculate spectral centroid (brightness of sound)
    #[wasm_bindgen]
    pub fn spectral_centroid(&self, magnitudes: &[f32], sample_rate: f32) -> f32 {
        if magnitudes.is_empty() {
            return 0.0;
        }

        let mut weighted_sum = 0.0;
        let mut sum = 0.0;
        
        for (i, &mag) in magnitudes.iter().enumerate() {
            let freq = i as f32 * sample_rate / (2.0 * magnitudes.len() as f32);
            weighted_sum += freq * mag;
            sum += mag;
        }
        
        if sum > 0.0 {
            weighted_sum / sum
        } else {
            0.0
        }
    }

    /// Calculate spectral rolloff (frequency below which 85% of energy is contained)
    #[wasm_bindgen]
    pub fn spectral_rolloff(&self, magnitudes: &[f32], sample_rate: f32, rolloff_percent: f32) -> f32 {
        if magnitudes.is_empty() {
            return 0.0;
        }

        let total_energy: f32 = magnitudes.iter().map(|m| m * m).sum();
        let target_energy = total_energy * rolloff_percent;
        
        let mut cumulative_energy = 0.0;
        for (i, &mag) in magnitudes.iter().enumerate() {
            cumulative_energy += mag * mag;
            if cumulative_energy >= target_energy {
                return i as f32 * sample_rate / (2.0 * magnitudes.len() as f32);
            }
        }
        
        sample_rate / 2.0
    }
}

#[wasm_bindgen]
pub fn create_fft_processor(size: usize) -> FFTProcessor {
    FFTProcessor::new(size)
}
