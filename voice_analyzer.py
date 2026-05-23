#!/usr/bin/env python3
"""
Voice Analysis Module for Voice AI Tools
Provides real-time voice quality analysis, pronunciation feedback, and adaptive training.
"""

import numpy as np
import librosa
import time
from typing import Dict, List, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class VoiceQualityMetrics:
    """Voice quality analysis results."""

    overall_score: float  # 0-100
    clarity: float  # Speech clarity score
    volume: float  # Volume consistency score
    noise_level: float  # Background noise level (lower is better)
    pronunciation: float  # Pronunciation accuracy score
    fluency: float  # Speech fluency score
    frequency_profile: Dict[str, float]  # Frequency distribution
    recommendations: List[str]  # Improvement suggestions
    analysis_time: float  # Time taken for analysis


@dataclass
class PronunciationFeedback:
    """Pronunciation feedback for specific words."""

    word: str
    expected_phonemes: List[str]
    actual_phonemes: List[str]
    accuracy: float  # 0-100
    suggestions: List[str]


class VoiceAnalyzer:
    """Advanced voice analysis with quality metrics."""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self.reference_texts = {
            "basic": "The quick brown fox jumps over the lazy dog",
            "numbers": "One two three four five six seven eight nine ten",
            "vowels": "A E I O U you are the vowels of English",
            "consonants": "Peter Piper picked a peck of pickled peppers",
        }

        # Quality thresholds
        self.thresholds = {"excellent": 85, "good": 70, "fair": 50, "poor": 30}

    def analyze_audio_file(self, audio_path: str) -> VoiceQualityMetrics:
        """Analyze audio file for voice quality metrics."""
        try:
            # Load audio file
            y, sr = librosa.load(audio_path, sr=self.sample_rate)

            start_time = time.time()

            # Extract features
            clarity = self._analyze_clarity(y, sr)
            volume_score = self._analyze_volume_consistency(y)
            noise_level = self._analyze_noise_level(y, sr)
            pronunciation = self._analyze_pronunciation(y, sr)
            fluency = self._analyze_fluency(y, sr)
            frequency_profile = self._analyze_frequency_profile(y, sr)

            # Calculate overall score
            overall_score = self._calculate_overall_score(
                clarity, volume_score, noise_level, pronunciation, fluency
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(
                clarity, volume_score, noise_level, pronunciation, fluency
            )

            analysis_time = time.time() - start_time

            return VoiceQualityMetrics(
                overall_score=overall_score,
                clarity=clarity,
                volume=volume_score,
                noise_level=noise_level,
                pronunciation=pronunciation,
                fluency=fluency,
                frequency_profile=frequency_profile,
                recommendations=recommendations,
                analysis_time=analysis_time,
            )

        except Exception as e:
            logger.error(f"Error analyzing audio file {audio_path}: {e}")
            return VoiceQualityMetrics(
                overall_score=0,
                clarity=0,
                volume=0,
                noise_level=100,
                pronunciation=0,
                fluency=0,
                frequency_profile={},
                recommendations=["Analysis failed - please check audio file"],
                analysis_time=0,
            )

    def _analyze_clarity(self, y: np.ndarray, sr: int) -> float:
        """Analyze speech clarity using spectral analysis."""
        # Compute spectral centroid
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

        # Higher spectral centroids generally indicate clearer speech
        # Normalize to 0-100 scale
        clarity_score = np.clip(
            (np.mean(spectral_centroids) - 1000) / 3000 * 100, 0, 100
        )

        return float(clarity_score)

    def _analyze_volume_consistency(self, y: np.ndarray) -> float:
        """Analyze volume consistency throughout the audio."""
        # Compute RMS energy
        rms = librosa.feature.rms(y=y)[0]

        # Calculate coefficient of variation (lower is more consistent)
        cv = np.std(rms) / (np.mean(rms) + 1e-8)

        # Convert to 0-100 scale (lower cv = higher score)
        volume_score = np.clip((1 - cv) * 100, 0, 100)

        return float(volume_score)

    def _analyze_noise_level(self, y: np.ndarray, sr: int) -> float:
        """Analyze background noise level."""
        # Use spectral flatness to detect noise
        spectral_flatness = librosa.feature.spectral_flatness(y=y)[0]

        # Higher flatness indicates more noise-like content
        noise_level = np.mean(spectral_flatness) * 100

        return float(np.clip(noise_level, 0, 100))

    def _analyze_pronunciation(self, y: np.ndarray, sr: int) -> float:
        """Analyze pronunciation accuracy using phoneme matching."""
        # This is a simplified version - in practice, you'd use
        # a phoneme recognition system or speech-to-text API

        # For now, use MFCC similarity to expected patterns
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)

        # Calculate temporal consistency (proxy for pronunciation)
        mfcc_delta = np.diff(mfcc, axis=1)
        consistency = 1 - np.mean(np.abs(mfcc_delta))

        pronunciation_score = consistency * 100

        return float(np.clip(pronunciation_score, 0, 100))

    def _analyze_fluency(self, y: np.ndarray, sr: int) -> float:
        """Analyze speech fluency using pause detection."""
        # Detect speech segments
        intervals = librosa.effects.split(y, top_db=20)

        if len(intervals) == 0:
            return 0.0

        # Calculate speaking rate and pause patterns
        speech_durations = [end - start for start, end in intervals]
        total_speech_time = sum(speech_durations)
        total_duration = len(y) / sr

        # Fluency score based on speech ratio and consistency
        speech_ratio = total_speech_time / total_duration
        duration_consistency = 1 - (
            np.std(speech_durations) / (np.mean(speech_durations) + 1e-8)
        )

        fluency_score = (speech_ratio * 0.7 + duration_consistency * 0.3) * 100

        return float(np.clip(fluency_score, 0, 100))

    def _analyze_frequency_profile(self, y: np.ndarray, sr: int) -> Dict[str, float]:
        """Analyze frequency distribution of voice."""
        # Compute power spectrum
        fft = np.fft.fft(y)
        freqs = np.fft.fftfreq(len(y), 1 / sr)
        power = np.abs(fft) ** 2

        # Define frequency bands
        bands = {
            "bass": (20, 250),
            "low_mid": (250, 500),
            "mid": (500, 2000),
            "high_mid": (2000, 4000),
            "treble": (4000, 20000),
        }

        profile = {}
        total_power = np.sum(power)

        for band_name, (low, high) in bands.items():
            mask = (np.abs(freqs) >= low) & (np.abs(freqs) < high)
            band_power = np.sum(power[mask])
            profile[band_name] = (
                (band_power / total_power * 100) if total_power > 0 else 0
            )

        return profile

    def _calculate_overall_score(
        self,
        clarity: float,
        volume: float,
        noise_level: float,
        pronunciation: float,
        fluency: float,
    ) -> float:
        """Calculate overall voice quality score."""
        # Weight different metrics
        weights = {
            "clarity": 0.25,
            "volume": 0.15,
            "noise": 0.20,  # Inverted (lower noise = higher score)
            "pronunciation": 0.25,
            "fluency": 0.15,
        }

        # Invert noise level (lower noise = higher score)
        noise_score = 100 - noise_level

        overall = (
            clarity * weights["clarity"]
            + volume * weights["volume"]
            + noise_score * weights["noise"]
            + pronunciation * weights["pronunciation"]
            + fluency * weights["fluency"]
        )

        return float(np.clip(overall, 0, 100))

    def _generate_recommendations(
        self,
        clarity: float,
        volume: float,
        noise_level: float,
        pronunciation: float,
        fluency: float,
    ) -> List[str]:
        """Generate improvement recommendations based on analysis."""
        recommendations = []

        if clarity < self.thresholds["good"]:
            recommendations.append(
                "Speak more clearly and enunciate words properly. "
                "Consider recording in a quieter environment."
            )

        if volume < self.thresholds["good"]:
            recommendations.append(
                "Maintain consistent volume throughout recording. "
                "Move closer to or further from microphone as needed."
            )

        if noise_level > self.thresholds["fair"]:
            recommendations.append(
                "Reduce background noise. Record in a quieter environment "
                "or use noise cancellation features."
            )

        if pronunciation < self.thresholds["good"]:
            recommendations.append(
                "Practice pronunciation of difficult words. "
                "Speak at a moderate pace for better clarity."
            )

        if fluency < self.thresholds["good"]:
            recommendations.append(
                "Reduce unnecessary pauses. Practice speaking more smoothly "
                "and naturally."
            )

        if not recommendations:
            recommendations.append("Excellent voice quality! Keep up the good work.")

        return recommendations

    def analyze_training_progress(
        self, analysis_history: List[VoiceQualityMetrics]
    ) -> Dict[str, Any]:
        """Analyze training progress over multiple recordings."""
        if len(analysis_history) < 2:
            return {
                "status": "insufficient_data",
                "message": "Need at least 2 recordings",
            }

        # Calculate trends
        recent_scores = [m.overall_score for m in analysis_history[-5:]]
        early_scores = [m.overall_score for m in analysis_history[:5]]

        recent_avg = np.mean(recent_scores)
        early_avg = np.mean(early_scores)
        improvement = recent_avg - early_avg

        # Identify areas of improvement
        metric_trends = {}
        for metric in ["clarity", "volume", "pronunciation", "fluency"]:
            recent_values = [getattr(m, metric) for m in analysis_history[-5:]]
            early_values = [getattr(m, metric) for m in analysis_history[:5]]

            trend = np.mean(recent_values) - np.mean(early_values)
            metric_trends[metric] = {
                "trend": "improving" if trend > 0 else "declining",
                "change": float(trend),
            }

        return {
            "status": "analyzed",
            "overall_improvement": float(improvement),
            "recent_average": float(recent_avg),
            "early_average": float(early_avg),
            "metric_trends": metric_trends,
            "recommendations": self._generate_training_recommendations(
                improvement, metric_trends
            ),
        }

    def _generate_training_recommendations(
        self, overall_improvement: float, metric_trends: Dict[str, Dict]
    ) -> List[str]:
        """Generate training recommendations based on progress analysis."""
        recommendations = []

        if overall_improvement < 5:
            recommendations.append(
                "Progress is slow. Consider recording more frequently "
                "or focusing on specific areas for improvement."
            )
        elif overall_improvement > 20:
            recommendations.append(
                "Excellent progress! You're improving rapidly. "
                "Continue with your current training approach."
            )

        # Find areas needing most work
        worst_metric = min(metric_trends.items(), key=lambda x: x[1]["change"])
        if worst_metric[1]["change"] < 0:
            recommendations.append(
                f"Focus on improving {worst_metric[0]} - "
                "this area shows the most room for improvement."
            )

        return recommendations


# Global analyzer instance
voice_analyzer = VoiceAnalyzer()
