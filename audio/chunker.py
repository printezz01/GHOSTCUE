"""
audio/chunker.py -- GhostCue Audio Chunker

Main audio loop. Every 5 seconds:
1. Captures system audio via capture.py
2. Transcribes with Whisper via transcribe.py  
3. Sends transcript chunk JSON to ws://localhost:3000/agent via WebSocket

This is the bridge between the audio world and the agent loop.
Run this in a separate terminal alongside the agent daemon.

Usage:
    python audio/chunker.py              # auto-detect audio device
    python audio/chunker.py --device 3   # use specific device ID
    python audio/chunker.py --list       # list available devices
    python audio/chunker.py --simulate   # simulate with fake transcript (no mic needed)
"""

import sys
import json
import time
import signal
import argparse
import asyncio
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from audio.capture import AudioCapture, list_devices, SAMPLE_RATE
from audio.transcribe import transcribe_with_diarization, get_model

try:
    import websockets
except ImportError:
    print("[CHUNKER] ERROR: websockets not installed. Run: pip install websockets")
    sys.exit(1)

# Agent WebSocket endpoint
AGENT_WS_URL = "ws://localhost:3000/agent"

# Simulate mode: fake transcript chunks for testing without mic
SIMULATE_CHUNKS = [
    {"text": "So tell me about your experience with Python and distributed systems.", "speaker": "interviewer"},
    {"text": "I think I have been working with Python for maybe like sort of 3 years I guess.", "speaker": "candidate"},
    {"text": "Can you tell me about a specific project?", "speaker": "interviewer"},
    {"text": "The team built a recommendation engine. We used Python and some machine learning stuff.", "speaker": "candidate"},
    {"text": "What was your specific role in that project?", "speaker": "interviewer"},
    {"text": "I was involved in the backend development and some of the data pipeline work.", "speaker": "candidate"},
    {"text": "How did you handle scaling the system?", "speaker": "interviewer"},
    {"text": "I have 2 years of experience with databases and I designed the sharding strategy for PostgreSQL.", "speaker": "candidate"},
    {"text": "Earlier you mentioned 3 years of Python experience. Your resume says 6 years. Can you clarify?", "speaker": "interviewer"},
    {"text": "Oh right, I meant 3 years at my current company. Total experience is longer.", "speaker": "candidate"},
    {"text": "Tell me about a time you faced a difficult technical challenge.", "speaker": "interviewer"},
    {"text": "We had a production incident where the recommendation engine went down. I led the debugging effort and found a memory leak in our Redis connection pool.", "speaker": "candidate"},
    {"text": "", "speaker": ""},  # silence
    {"text": "", "speaker": ""},  # silence
    {"text": "", "speaker": ""},  # continued silence
]

# Track running state for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global running
    print("\n[CHUNKER] Shutting down...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


async def run_live_chunker(device_id=None):
    """
    Main loop: capture audio -> transcribe -> send to agent.
    Runs until Ctrl+C or session ends.
    """
    global running

    print("[CHUNKER] Initializing audio capture...")
    capture = AudioCapture(device_id)

    print("[CHUNKER] Pre-loading Whisper model...")
    get_model()  # load model once before loop starts

    print(f"[CHUNKER] Connecting to agent at {AGENT_WS_URL}...")

    try:
        async with websockets.connect(AGENT_WS_URL) as ws:
            # Read welcome message
            welcome = await ws.recv()
            welcome_data = json.loads(welcome)
            print(f"[CHUNKER] Connected to agent (candidates: {welcome_data.get('candidateCount', 0)})")

            capture.start()
            chunk_count = 0

            print("[CHUNKER] Live audio chunking started (Ctrl+C to stop)")
            print("[CHUNKER] " + "-" * 50)

            while running:
                loop_start = time.time()

                # Step 1: Record 5-second chunk
                chunk_data = capture.get_chunk(duration=5)

                if chunk_data['is_silence']:
                    # Send empty chunk (agent loop tracks silence for session end)
                    await ws.send(json.dumps({
                        "type": "transcript_chunk",
                        "text": "",
                        "speaker": "unknown",
                        "timestamp": datetime.now().isoformat()
                    }))

                    if chunk_data['consecutive_silence'] % 6 == 0:  # log every 30 seconds
                        secs = chunk_data['consecutive_silence'] * 5
                        print(f"[CHUNKER] Silence: {secs}s consecutive")
                    continue

                # Step 2: Transcribe with diarization
                result = transcribe_with_diarization(
                    chunk_data['audio'],
                    sample_rate=SAMPLE_RATE
                )

                if not result['text'].strip():
                    continue

                chunk_count += 1

                # Step 3: Send to agent via WebSocket
                message = {
                    "type": "transcript_chunk",
                    "text": result['text'],
                    "speaker": result['speaker'],
                    "timestamp": datetime.now().isoformat(),
                    "chunk_index": chunk_count,
                    "duration": result['duration']
                }

                await ws.send(json.dumps(message))

                # Display what was transcribed
                speaker_label = result['speaker'].upper()[:4]
                text_preview = result['text'][:70]
                elapsed = time.time() - loop_start
                print(f"  [{speaker_label}] {text_preview}{'...' if len(result['text']) > 70 else ''} ({elapsed:.1f}s)")

                # Listen for alerts from agent
                try:
                    while True:
                        alert_raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
                        alert = json.loads(alert_raw)
                        if alert.get('event') == 'alert':
                            data = alert['data']
                            icon = {'pressure_point': 'PROBE', 'contradiction': 'CONFLICT', 'coverage_gap': 'GAP'}.get(data.get('type'), 'ALERT')
                            print(f"  >> [{icon}] {data.get('message', '')}")
                except asyncio.TimeoutError:
                    pass

            capture.stop()
            print("\n[CHUNKER] Audio chunking stopped")
            print(f"[CHUNKER] Total chunks processed: {chunk_count}")

    except websockets.exceptions.ConnectionRefusedError:
        print(f"[CHUNKER] ERROR: Cannot connect to agent at {AGENT_WS_URL}")
        print("[CHUNKER] Make sure the agent daemon is running: node agent/index.js")
    except Exception as e:
        print(f"[CHUNKER] ERROR: {e}")


async def run_simulate_mode():
    """
    Simulate mode: send fake transcript chunks to the agent.
    No microphone needed -- useful for demo and testing.
    """
    global running

    print("[CHUNKER] SIMULATE MODE - sending fake transcript chunks")
    print(f"[CHUNKER] Connecting to agent at {AGENT_WS_URL}...")

    try:
        async with websockets.connect(AGENT_WS_URL) as ws:
            welcome = await ws.recv()
            welcome_data = json.loads(welcome)
            print(f"[CHUNKER] Connected (candidates: {welcome_data.get('candidateCount', 0)})")
            print("[CHUNKER] " + "-" * 50)

            for i, chunk in enumerate(SIMULATE_CHUNKS):
                if not running:
                    break

                message = {
                    "type": "transcript_chunk",
                    "text": chunk["text"],
                    "speaker": chunk["speaker"],
                    "timestamp": datetime.now().isoformat(),
                    "chunk_index": i + 1,
                    "simulated": True
                }

                await ws.send(json.dumps(message))

                if chunk["text"]:
                    speaker = chunk["speaker"].upper()[:4]
                    print(f"  [{speaker}] {chunk['text'][:70]}")
                else:
                    print(f"  [....] (silence)")

                # Listen for alerts
                try:
                    while True:
                        alert_raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        alert = json.loads(alert_raw)
                        if alert.get('event') == 'alert':
                            data = alert['data']
                            icon = {'pressure_point': 'PROBE', 'contradiction': 'CONFLICT', 'coverage_gap': 'GAP'}.get(data.get('type'), 'ALERT')
                            print(f"  >> [{icon}] {data.get('message', '')}")
                except asyncio.TimeoutError:
                    pass

                # Wait 5 seconds between chunks (simulating real-time)
                await asyncio.sleep(5)

            print("\n[CHUNKER] Simulation complete")

    except websockets.exceptions.ConnectionRefusedError:
        print(f"[CHUNKER] ERROR: Cannot connect to agent at {AGENT_WS_URL}")
        print("[CHUNKER] Make sure the agent daemon is running: node agent/index.js")
    except Exception as e:
        print(f"[CHUNKER] ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description="GhostCue Audio Chunker")
    parser.add_argument("--device", type=int, default=None,
                        help="Audio device ID (run --list to see available)")
    parser.add_argument("--list", action="store_true",
                        help="List available audio devices and exit")
    parser.add_argument("--simulate", action="store_true",
                        help="Simulate mode with fake transcript (no mic needed)")

    args = parser.parse_args()

    if args.list:
        list_devices()
        return

    if args.simulate:
        asyncio.run(run_simulate_mode())
    else:
        asyncio.run(run_live_chunker(args.device))


if __name__ == "__main__":
    main()
