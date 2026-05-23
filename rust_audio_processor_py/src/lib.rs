use numpy::PyArray1;
use pyo3::prelude::*;

#[pyclass]
pub struct AudioProcessorPy {
    sample_rate: f32,
}

#[pymethods]
impl AudioProcessorPy {
    #[new]
    pub fn new(sample_rate: f32) -> Self {
        AudioProcessorPy { sample_rate }
    }

    /// Apply noise gate to audio buffer
    pub fn apply_noise_gate(&self, audio: &PyArray1<f32>, threshold: f32) -> PyResult<Vec<f32>> {
        let audio_slice = unsafe { audio.as_slice()? };
        let mut result = audio_slice.to_vec();

        for sample in result.iter_mut() {
            if sample.abs() < threshold {
                *sample = 0.0;
            }
        }

        Ok(result)
    }

    /// Normalize audio volume
    pub fn normalize_audio(&self, audio: &PyArray1<f32>, target_level: f32) -> PyResult<Vec<f32>> {
        let audio_slice = unsafe { audio.as_slice()? };
        let mut result = audio_slice.to_vec();

        let max_sample = result.iter().map(|s| s.abs()).fold(0.0f32, f32::max);
        if max_sample > 0.0 {
            let scale = target_level / max_sample;
            for sample in result.iter_mut() {
                *sample *= scale;
            }
        }

        Ok(result)
    }

    /// Apply low-pass filter for noise reduction
    pub fn apply_low_pass_filter(
        &self,
        audio: &PyArray1<f32>,
        cutoff_freq: f32,
    ) -> PyResult<Vec<f32>> {
        let audio_slice = unsafe { audio.as_slice()? };
        let mut result = audio_slice.to_vec();

        let alpha = (2.0 * std::f32::consts::PI * cutoff_freq / self.sample_rate).exp();
        let mut prev_sample = 0.0;

        for sample in result.iter_mut() {
            *sample = alpha * prev_sample + (1.0 - alpha) * *sample;
            prev_sample = *sample;
        }

        Ok(result)
    }

    /// Resample audio to new sample rate
    pub fn resample(&self, audio: &PyArray1<f32>, new_sample_rate: f32) -> PyResult<Vec<f32>> {
        let audio_slice = unsafe { audio.as_slice()? };
        let ratio = new_sample_rate / self.sample_rate;
        let new_length = (audio_slice.len() as f32 * ratio) as usize;
        let mut result = vec![0.0; new_length];

        for i in 0..new_length {
            let src_index = (i as f32 / ratio) as usize;
            if src_index < audio_slice.len() {
                result[i] = audio_slice[src_index];
            }
        }

        Ok(result)
    }

    /// Trim silence from beginning and end
    pub fn trim_silence(
        &self,
        audio: &PyArray1<f32>,
        silence_threshold: f32,
    ) -> PyResult<Vec<f32>> {
        let audio_slice = unsafe { audio.as_slice()? };
        let mut start = 0;
        let mut end = audio_slice.len();

        for (i, &sample) in audio_slice.iter().enumerate() {
            if sample.abs() > silence_threshold {
                start = i;
                break;
            }
        }

        for (i, &sample) in audio_slice.iter().enumerate().rev() {
            if sample.abs() > silence_threshold {
                end = i + 1;
                break;
            }
        }

        if start < end {
            Ok(audio_slice[start..end].to_vec())
        } else {
            Ok(audio_slice.to_vec())
        }
    }

    /// Calculate audio statistics
    pub fn get_audio_stats(&self, audio: &PyArray1<f32>) -> PyResult<(f32, f32, f32)> {
        let audio_slice = unsafe { audio.as_slice()? };

        let rms =
            (audio_slice.iter().map(|s| s * s).sum::<f32>() / audio_slice.len() as f32).sqrt();
        let peak = audio_slice.iter().map(|s| s.abs()).fold(0.0f32, f32::max);
        let avg = audio_slice.iter().sum::<f32>() / audio_slice.len() as f32;

        Ok((rms, peak, avg))
    }
}

#[pymodule]
fn audio_processor_py(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<AudioProcessorPy>()?;
    Ok(())
}
