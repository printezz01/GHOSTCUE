# AI Usage Log — GhostCue

> **PRISM OpenClaw Hackathon Disclosure**
> This document logs all AI model usage in GhostCue per hackathon requirements.

## Models Used

### 1. Groq — `llama-3.3-70b-versatile`

| Component | Purpose | Temperature | Max Tokens | Required? |
|-----------|---------|-------------|------------|-----------|
| `resume/parser.py` | Extract structured data from resume text | 0.1 | 2000 | No — regex fallback exists |
| `resume/question-gen.py` | Generate personalized interview questions | 0.7 | 2000 | No — template fallback exists |
| `agent/analyzers/pressure-point.js` | Detect shallow/vague candidate answers | 0.3 | 150 | No — heuristic fallback exists |
| `agent/analyzers/contradiction.js` | Compare statements vs resume claims | 0.2 | 300 | No — heuristic fallback exists |
| `scoring/gap-engine.py` | Map resume claims to transcript evidence | 0.2 | 2000 | No — keyword matching fallback |

**Provider:** Groq (groq.com) — LPU inference engine, not xAI  
**API endpoint:** `https://api.groq.com/openai/v1` (OpenAI-compatible SDK)  
**Environment variable:** `GROQ_API_KEY` (keys begin with `gsk_`)  
**Free tier:** Yes — Groq has a generous free tier. Get a key at https://console.groq.com/keys  
**Fallback model:** `llama-3.1-8b-instant` (if 70b is rate-limited)

### 2. OpenAI Whisper (`tiny.en` via faster-whisper)

| Component | Purpose | Model Size | Device | Required? |
|-----------|---------|-----------|--------|-----------|
| `audio/transcribe.py` | Real-time speech-to-text transcription | tiny.en (~75MB) | CPU (int8) or CUDA (float16) | Yes — core functionality |

**Note:** Whisper runs **100% locally** — no API key needed, no data leaves the machine.

## Fallback Architecture

Every Groq integration has a **graceful fallback** that runs when no API key is configured:

| Component | Groq Mode | Fallback Mode |
|-----------|-----------|--------------|
| Resume Parser | Structured JSON extraction via Llama 3.3 70B | Regex + keyword matching |
| Question Generator | Contextual questions via Llama 3.3 70B | Template-based generic questions |
| Pressure Point | Semantic shallow-answer detection | Filler word counting + word count |
| Contradiction | Cross-reference semantic comparison | Year mismatch + skill denial patterns |
| Gap Engine | Evidence-based claim mapping | Keyword frequency in transcript |

This means GhostCue works **without any API key** — just with reduced intelligence.

## AI-Generated Code Disclosure

The following was built with AI assistance (Google Antigravity / Gemini):

- All source files were pair-programmed with AI coding assistance
- Architecture decisions were guided by the master build prompt
- No pre-trained custom models were used
- No fine-tuning was performed
- All prompts to Groq are visible in source code (search for `messages:`)

## Data Privacy

- **No candidate data leaves the local machine** except through explicit Groq API calls
- Transcripts are stored locally in YAML files under `/memory/candidates/`
- PDF reports are generated locally under `/output/reports/`
- Whisper runs **locally** — audio is never sent to cloud services
- The only network calls are to Groq's API (when configured)

## Token Usage Estimate (Per Interview)

| Component | Calls per 30-min session | Tokens per call | Total tokens |
|-----------|------------------------|----------------|-------------|
| Resume Parser | 1 | ~3000 | ~3,000 |
| Question Gen | 1 | ~2000 | ~2,000 |
| Pressure Point | ~30 (not all trigger Groq) | ~200 | ~2,000 |
| Contradiction | ~30 (not all trigger Groq) | ~400 | ~4,000 |
| Gap Engine | 1 | ~4000 | ~4,000 |
| **Total** | | | **~15,000** |

Groq's free tier covers this easily for development and demo purposes.
