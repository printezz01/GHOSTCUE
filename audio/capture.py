"""
audio/capture.py — System Audio Capture for GhostCue

Captures system audio (mic + speaker) using sounddevice:
- Windows: WASAPI loopback (built-in, no install needed)
- macOS: BlackHole 2ch virtual audio device (must be installed separately)

Records 5-second audio buffers and returns them as numpy arrays.
The chunker.py orchestrates calling this in a loop.
"""

import sys
import platform
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("[CAPTURE] ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)

# Audio settings
SAMPLE_RATE = 16000   # 16kHz — optimal for Whisper
CHANNELS = 1          # mono — Whisper works best with mono
CHUNK_DURATION = 5    # seconds per chunk
DTYPE = 'float32'     # audio data type


def get_system_device():
    """
    Find the correct audio device for system audio capture.
    - Windows: finds WASAPI loopback device
    - macOS: finds BlackHole 2ch device
    Returns (device_id, device_name) or (None, None) if not found.
    """
    os_name = platform.system()
    devices = sd.query_devices()

    if os_name == 'Windows':
        # On Windows, look for WASAPI loopback devices
        # These capture what's playing through the speakers
        for i, dev in enumerate(devices):
            name = dev['name'].lower()
            # Look for loopback or stereo mix devices
            if dev['max_input_channels'] > 0:
                if any(kw in name for kw in ['stereo mix', 'loopback', 'what u hear', 'wave out']):
                    print(f"[CAPTURE] Found loopback device: {dev['name']} (id={i})")
                    return i, dev['name']

        # Fallback: use default input (microphone)
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            dev = devices[default_input]
            print(f"[CAPTURE] Using default mic: {dev['name']} (id={default_input})")
            return default_input, dev['name']

    elif os_name == 'Darwin':
        # On macOS, look for BlackHole 2ch
        for i, dev in enumerate(devices):
            if 'blackhole' in dev['name'].lower() and dev['max_input_channels'] > 0:
                print(f"[CAPTURE] Found BlackHole: {dev['name']} (id={i})")
                return i, dev['name']

        # Fallback: use default input (microphone)
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            dev = devices[default_input]
            print(f"[CAPTURE] Using default mic: {dev['name']} (id={default_input})")
            return default_input, dev['name']

    else:
        # Linux: use default input
        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            dev = devices[default_input]
            print(f"[CAPTURE] Using default input: {dev['name']} (id={default_input})")
            return default_input, dev['name']

    return None, None


def list_devices():
    """Print all available audio devices (useful for debugging)."""
    print("\n[CAPTURE] Available audio devices:")
    print("-" * 60)
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        direction = []
        if dev['max_input_channels'] > 0:
            direction.append(f"IN:{dev['max_input_channels']}ch")
        if dev['max_output_channels'] > 0:
            direction.append(f"OUT:{dev['max_output_channels']}ch")
        marker = " <-- DEFAULT" if i in (sd.default.device[0], sd.default.device[1]) else ""
        print(f"  [{i}] {dev['name']} ({', '.join(direction)}){marker}")
    print("-" * 60)


def record_chunk(device_id=None, duration=CHUNK_DURATION):
    """
    Record a single audio chunk (default 5 seconds).
    Returns a numpy array of float32 audio samples at 16kHz mono.
    Returns None if recording fails.
    """
    try:
        # Record audio
        audio = sd.rec(
            frames=int(SAMPLE_RATE * duration),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=device_id
        )
        sd.wait()  # block until recording is complete

        # Flatten to 1D if needed
        if audio.ndim > 1:
            audio = audio.flatten()

        return audio

    except sd.PortAudioError as e:
        print(f"[CAPTURE] PortAudio error: {e}")
        return None
    except Exception as e:
        print(f"[CAPTURE] Recording error: {e}")
        return None


def is_silence(audio, threshold=0.01):
    """
    Check if an audio chunk is effectively silence.
    Uses RMS energy — if below threshold, it's silence.
    """
    if audio is None or len(audio) == 0:
        return True

    rms = np.sqrt(np.mean(audio ** 2))
    return rms < threshold


class AudioCapture:
    """
    Stateful audio capture manager.
    Handles device selection, continuous recording, and silence detection.
    """

    def __init__(self, device_id=None):
        """Initialize with a specific device or auto-detect."""
        if device_id is not None:
            self.device_id = device_id
            dev = sd.query_devices(device_id)
            self.device_name = dev['name']
        else:
            self.device_id, self.device_name = get_system_device()

        if self.device_id is None:
            print("[CAPTURE] WARNING: No audio device found. Using system default.")
            self.device_id = None
            self.device_name = "System Default"

        self.is_recording = False
        self.consecutive_silence = 0

    def start(self):
        """Mark capture as active."""
        self.is_recording = True
        self.consecutive_silence = 0
        print(f"[CAPTURE] Recording from: {self.device_name}")

    def stop(self):
        """Mark capture as inactive."""
        self.is_recording = False
        print("[CAPTURE] Recording stopped")

    def get_chunk(self, duration=CHUNK_DURATION):
        """
        Record one chunk and return it with metadata.
        Returns dict with audio data and silence status.
        """
        audio = record_chunk(self.device_id, duration)

        if audio is None:
            self.consecutive_silence += 1
            return {
                'audio': None,
                'is_silence': True,
                'consecutive_silence': self.consecutive_silence,
                'duration': duration,
                'sample_rate': SAMPLE_RATE
            }

        silent = is_silence(audio)
        if silent:
            self.consecutive_silence += 1
        else:
            self.consecutive_silence = 0

        return {
            'audio': audio,
            'is_silence': silent,
            'consecutive_silence': self.consecutive_silence,
            'duration': duration,
            'sample_rate': SAMPLE_RATE
        }


if __name__ == "__main__":
    # Debug mode: list devices and record a test chunk
    list_devices()
    print("\n[CAPTURE] Recording 5-second test chunk...")

    device_id, device_name = get_system_device()
    audio = record_chunk(device_id)

    if audio is not None:
        rms = np.sqrt(np.mean(audio ** 2))
        silent = is_silence(audio)
        print(f"[CAPTURE] Recorded {len(audio)} samples")
        print(f"[CAPTURE] RMS energy: {rms:.6f}")
        print(f"[CAPTURE] Is silence: {silent}")
        print("[CAPTURE] OK - Audio capture working")
    else:
        print("[CAPTURE] FAIL - Could not record audio")
