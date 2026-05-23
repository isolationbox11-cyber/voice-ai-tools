#!/usr/bin/env python3
"""
Audio processing wrapper using Rust PyO3 extension
Provides fast audio manipulation for voice training
"""

import numpy as np
from typing import Tuple

try:
    import audio_processor_py

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("Warning: Rust audio processor not available. Using Python fallback.")


class AudioProcessor:
    """Fast audio processing using Rust PyO3 extension"""

    def __init__(self, sample_rate: float = 44100.0):
        self.sample_rate = sample_rate
        if RUST_AVAILABLE:
            self.processor = audio_processor_py.AudioProcessorPy(sample_rate)
        else:
            self.processor = None

    def apply_noise_gate(
        self, audio: np.ndarray, threshold: float = 0.05
    ) -> np.ndarray:
        """Remove background noise below threshold"""
        if RUST_AVAILABLE:
            result = self.processor.apply_noise_gate(audio, threshold)
            return np.array(result)
        else:
            # Python fallback
            audio_copy = audio.copy()
            audio_copy[np.abs(audio_copy) < threshold] = 0.0
            return audio_copy

    def normalize_audio(
        self, audio: np.ndarray, target_level: float = 0.8
    ) -> np.ndarray:
        """Normalize audio to target level"""
        if RUST_AVAILABLE:
            result = self.processor.normalize_audio(audio, target_level)
            return np.array(result)
        else:
            # Python fallback
            audio_copy = audio.copy()
            max_sample = np.max(np.abs(audio_copy))
            if max_sample > 0:
                audio_copy = audio_copy * (target_level / max_sample)
            return audio_copy

    def apply_low_pass_filter(
        self, audio: np.ndarray, cutoff_freq: float = 1000.0
    ) -> np.ndarray:
        """Apply low-pass filter for noise reduction"""
        if RUST_AVAILABLE:
            result = self.processor.apply_low_pass_filter(audio, cutoff_freq)
            return np.array(result)
        else:
            # Python fallback (simple moving average)
            from scipy.signal import butter, filtfilt

            try:
                nyquist = self.sample_rate / 2
                normal_cutoff = cutoff_freq / nyquist
                b, a = butter(4, normal_cutoff, btype="low")
                return filtfilt(b, a, audio)
            except ImportError:
                # Very simple fallback
                audio_copy = audio.copy()
                kernel_size = int(self.sample_rate / cutoff_freq)
                kernel = np.ones(kernel_size) / kernel_size
                return np.convolve(audio_copy, kernel, mode="same")

    def resample(self, audio: np.ndarray, new_sample_rate: float) -> np.ndarray:
        """Resample audio to new sample rate"""
        if RUST_AVAILABLE:
            result = self.processor.resample(audio, new_sample_rate)
            return np.array(result)
        else:
            # Python fallback using scipy
            try:
                from scipy.signal import resample

                return resample(
                    audio, int(len(audio) * new_sample_rate / self.sample_rate)
                )
            except ImportError:
                # Simple linear interpolation
                ratio = new_sample_rate / self.sample_rate
                new_length = int(len(audio) * ratio)
                indices = np.linspace(0, len(audio) - 1, new_length)
                return np.interp(indices, np.arange(len(audio)), audio)

    def trim_silence(
        self, audio: np.ndarray, silence_threshold: float = 0.01
    ) -> np.ndarray:
        """Remove silence from beginning and end"""
        if RUST_AVAILABLE:
            result = self.processor.trim_silence(audio, silence_threshold)
            return np.array(result)
        else:
            # Python fallback
            audio_copy = audio.copy()
            above_threshold = np.abs(audio_copy) > silence_threshold
            if not np.any(above_threshold):
                return audio_copy

            start = np.where(above_threshold)[0][0]
            end = np.where(above_threshold)[0][-1] + 1
            return audio_copy[start:end]

    def get_audio_stats(self, audio: np.ndarray) -> Tuple[float, float, float]:
        """Get audio statistics (RMS, peak, average)"""
        if RUST_AVAILABLE:
            rms, peak, avg = self.processor.get_audio_stats(audio)
            return rms, peak, avg
        else:
            # Python fallback
            rms = np.sqrt(np.mean(audio**2))
            peak = np.max(np.abs(audio))
            avg = np.mean(audio)
            return rms, peak, avg

    def process_voice_sample(self, audio: np.ndarray) -> np.ndarray:
        """
        Process voice sample for training:
        1. Trim silence
        2. Apply noise gate
        3. Normalize
        4. Apply low-pass filter
        """
        processed = audio.copy()

        # Trim silence
        processed = self.trim_silence(processed)

        # Apply noise gate
        processed = self.apply_noise_gate(processed, threshold=0.05)

        # Normalize
        processed = self.normalize_audio(processed, target_level=0.8)

        # Apply low-pass filter for noise reduction
        processed = self.apply_low_pass_filter(processed, cutoff_freq=8000.0)

        return processed


def get_audio_processor(sample_rate: float = 44100.0) -> AudioProcessor:
    """Get audio processor instance"""
    return AudioProcessor(sample_rate)
