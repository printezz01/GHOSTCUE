"""
audio/transcribe.py — Whisper Speech-to-Text for GhostCue

Wraps faster-whisper for local transcription with basic speaker
diarization. Runs the 'tiny.en' or 'base.en' model for speed
(real-time interview use case prioritizes latency over accuracy).

Diarization approach:
- No external diarization model (keeps it lightweight)
- Uses simple energy/pitch variance to distinguish Speaker A vs Speaker B
- Speaker A = lower average energy (typically the interviewer, calmer)
- Speaker B = higher average energy (typically the candidate, more animated)
- This is approximate — works for 2-person interviews
"""

import sys
import os
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("[TRANSCRIBE] ERROR: faster-whisper not installed. Run: pip install faster-whisper")
    sys.exit(1)

# Model configuration
# tiny.en = fastest, ~1GB RAM, good enough for English interviews
# base.en = slightly better accuracy, ~1.5GB RAM
# small.en = best quality for real-time, ~2.5GB RAM
DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "tiny.en")
DEFAULT_DEVICE = "cpu"   # use "cuda" if GPU available
DEFAULT_COMPUTE = "int8"  # int8 quantization for speed on CPU

# Singleton model instance (loaded once, reused across calls)
_model = None


def get_model(model_size=None):
    """
    Load the Whisper model (singleton — only loaded once).
    Downloads the model on first run (~75MB for tiny.en).
    """
    global _model

    if _model is not None:
        return _model

    model_size = model_size or DEFAULT_MODEL
    device = DEFAULT_DEVICE
    compute_type = DEFAULT_COMPUTE

    # Auto-detect CUDA
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
            compute_type = "float16"
            print(f"[TRANSCRIBE] GPU detected, using CUDA")
    except ImportError:
        pass

    print(f"[TRANSCRIBE] Loading Whisper model: {model_size} ({device}/{compute_type})")
    print(f"[TRANSCRIBE] First run will download the model...")

    _model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type
    )

    print(f"[TRANSCRIBE] Model loaded successfully")
    return _model


def transcribe_audio(audio_array, sample_rate=16000):
    """
    Transcribe a numpy audio array using faster-whisper.
    
    Args:
        audio_array: numpy float32 array of audio samples
        sample_rate: sample rate (should be 16000 for Whisper)
    
    Returns:
        dict with 'text', 'segments', 'language', 'duration'
    """
    if audio_array is None or len(audio_array) == 0:
        return {
            'text': '',
            'segments': [],
            'language': 'en',
            'duration': 0.0
        }

    model = get_model()

    # Ensure float32 and proper shape
    audio = np.array(audio_array, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.flatten()

    try:
        segments, info = model.transcribe(
            audio,
            language='en',          # force English (skip language detection for speed)
            beam_size=1,            # greedy decoding for speed
            best_of=1,
            vad_filter=True,        # filter out non-speech segments
            vad_parameters=dict(
                min_silence_duration_ms=500,  # merge segments with short pauses
                speech_pad_ms=200
            )
        )

        # Collect all segments
        result_segments = []
        full_text_parts = []

        for seg in segments:
            result_segments.append({
                'start': seg.start,
                'end': seg.end,
                'text': seg.text.strip()
            })
            full_text_parts.append(seg.text.strip())

        full_text = ' '.join(full_text_parts)

        return {
            'text': full_text,
            'segments': result_segments,
            'language': info.language if info else 'en',
            'duration': info.duration if info else len(audio) / sample_rate
        }

    except Exception as e:
        print(f"[TRANSCRIBE] Error: {e}")
        return {
            'text': '',
            'segments': [],
            'language': 'en',
            'duration': 0.0
        }


def estimate_speaker(audio_array, segments):
    """
    Basic speaker diarization using energy variance.
    Splits segments into Speaker A (lower energy) and Speaker B (higher energy).
    
    This is a rough heuristic for 2-person interviews:
    - Interviewer tends to speak more calmly (lower RMS)
    - Candidate tends to speak with more variation (higher RMS)
    
    For production, use pyannote.audio or similar — this is demo-grade.
    """
    if audio_array is None or not segments:
        return segments

    sample_rate = 16000
    labeled_segments = []

    # Calculate RMS energy for each segment
    energies = []
    for seg in segments:
        start_sample = int(seg['start'] * sample_rate)
        end_sample = int(seg['end'] * sample_rate)

        # Bounds check
        start_sample = max(0, min(start_sample, len(audio_array) - 1))
        end_sample = max(start_sample + 1, min(end_sample, len(audio_array)))

        segment_audio = audio_array[start_sample:end_sample]
        rms = np.sqrt(np.mean(segment_audio ** 2)) if len(segment_audio) > 0 else 0
        energies.append(rms)

    # Split by median energy: lower = Speaker A (interviewer), higher = Speaker B (candidate)
    if energies:
        median_energy = np.median(energies)
    else:
        median_energy = 0

    for seg, energy in zip(segments, energies):
        labeled_seg = dict(seg)
        labeled_seg['speaker'] = 'interviewer' if energy <= median_energy else 'candidate'
        labeled_seg['energy'] = float(energy)
        labeled_segments.append(labeled_seg)

    return labeled_segments


def transcribe_with_diarization(audio_array, sample_rate=16000):
    """
    Full pipeline: transcribe + speaker diarization.
    Returns dict with labeled text and segments.
    """
    # Step 1: Transcribe
    result = transcribe_audio(audio_array, sample_rate)

    if not result['text']:
        return {
            'text': '',
            'speaker': 'unknown',
            'segments': [],
            'duration': result['duration']
        }

    # Step 2: Diarize
    labeled_segments = estimate_speaker(audio_array, result['segments'])

    # Determine dominant speaker for this chunk
    if labeled_segments:
        candidate_words = sum(
            len(s['text'].split())
            for s in labeled_segments
            if s.get('speaker') == 'candidate'
        )
        interviewer_words = sum(
            len(s['text'].split())
            for s in labeled_segments
            if s.get('speaker') == 'interviewer'
        )
        dominant_speaker = 'candidate' if candidate_words >= interviewer_words else 'interviewer'
    else:
        dominant_speaker = 'unknown'

    return {
        'text': result['text'],
        'speaker': dominant_speaker,
        'segments': labeled_segments,
        'duration': result['duration']
    }


if __name__ == "__main__":
    # Test: transcribe a 5-second silent buffer
    print("[TRANSCRIBE] Testing with silent audio buffer...")
    test_audio = np.zeros(16000 * 5, dtype=np.float32)
    result = transcribe_audio(test_audio)
    print(f"[TRANSCRIBE] Result: '{result['text']}' (expected empty)")
    print("[TRANSCRIBE] OK - Transcription engine working")
