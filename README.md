# GhostCue — Silent AI Co-Interviewer

> **PRISM OpenClaw Hackathon Submission**
> Team: Solo | Builder: Prince

GhostCue is an autonomous AI agent that silently coaches interviewers during live job interviews. The candidate never sees it. Only the interviewer does.

## The Problem (5 Broken Things in Interviews)

| # | Problem | Impact |
|---|---------|--------|
| 1 | **Unprepared interviewers** | Skim resumes 5 min before, ask generic questions |
| 2 | **Uneven topic coverage** | Spend 35 min on one topic, miss system design entirely |
| 3 | **Dropped follow-ups** | Shallow answers accepted, no probing on scope/impact |
| 4 | **Biased post-call notes** | Reports from memory 10-30 min later, detail loss |
| 5 | **Contradiction blindness** | "Led a team of 12" vs resume says "team of 4" — missed |

## How GhostCue Solves This

```
                    ┌─────────────────┐
                    │   Resume PDF    │
                    │   (input/)      │
                    └────────┬────────┘
                             │ Trigger 1: Resume Drop
                             ▼
                    ┌─────────────────┐
                    │  Resume Parser  │──► Cognitive RAM
                    │  (resume/)      │    (memory/candidates/)
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Question Gen    │──► Personalized questions
                    └─────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   ┌──────────┐      ┌──────────────┐     ┌───────────┐
   │ Terminal  │      │  Telegram    │     │ WhatsApp  │
   │ CLI       │      │  Bot         │     │ Bot       │
   └─────┬────┘      └──────┬───────┘     └─────┬─────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                     WebSocket (ws://localhost:3000/agent)
                             │
                    ┌────────┴────────┐
                    │   AGENT LOOP    │ ◄── SOUL.md (behavioral rules)
                    │   (5-sec cycle) │ ◄── HEARTBEAT.md (triggers)
                    │   Node.js       │ ◄── Cognitive RAM (state)
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌───────────┐ ┌───────────┐ ┌───────────┐
        │ Pressure  │ │Contradict.│ │ Coverage  │
        │ Point     │ │ Detector  │ │ Gap       │
        │ Analyzer  │ │           │ │ Tracker   │
        └───────────┘ └───────────┘ └───────────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────┴────────┐
                    │ Alert Dispatcher│──► Real-time nudges
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │ Scoring Engine  │
                    │ (post-session)  │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │ PDF Report      │──► output/reports/
                    │ + Radar Chart   │
                    └─────────────────┘
```

## OpenClaw Compliance

GhostCue is built as a **load-bearing agent** — the Node.js agent loop is the irreplaceable brain:

| Requirement | Implementation |
|-------------|---------------|
| Agent loop is load-bearing | `loop.js` reads SOUL.md + RAM before every GPT call. Remove either → crash. |
| SOUL.md drives behavior | `soul-loader.js` parses rules every cycle. Agent refuses to start without it. |
| HEARTBEAT.md drives triggers | `heartbeat-watcher.js` verifies on boot. All 3 triggers must initialize. |
| Cognitive RAM is durable | `ram-reader.js` persists state as YAML. Agent crashes on corruption. |
| Cannot replace with raw GPT | Loop integrates 3 analyzers + RAM + SOUL context. Direct API call = broken. |

## Quick Start

### Prerequisites
- **Node.js 22+** and **Python 3.10+**
- Windows 10/11 (WASAPI audio) or macOS (BlackHole)

### Setup

```bash
# Clone
git clone https://github.com/printezz01/GHOSTCUE.git
cd GHOSTCUE

# Install dependencies
npm install
pip install -r requirements.txt

# Configure (copy and edit with your API keys)
cp .env.example .env
```

### Run

**Terminal 1 — Agent Daemon (must be running first):**
```bash
node agent/index.js
```

**Terminal 2 — Audio Pipeline (live or simulate):**
```bash
# Live audio capture (requires microphone)
python audio/chunker.py

# OR simulate mode (no mic needed — great for demo)
python audio/chunker.py --simulate
```

**Terminal 3 — WhatsApp Bot (optional):**
```bash
python interfaces/whatsapp/bot.py
# Then expose via: ngrok http 5002
```

### Generate Report
```bash
python scoring/pdf-report.py <candidate_id>
```

## Project Structure

```
GHOSTCUE/
├── SOUL.md                    # Agent behavioral rulebook
├── HEARTBEAT.md               # Autonomous trigger definitions
├── AI_USAGE_LOG.md            # LLM usage disclosure
├── agent/
│   ├── index.js               # Daemon entry — WS + REST server
│   ├── loop.js                # 5-second processing cycle
│   ├── soul-loader.js         # SOUL.md parser (hot-reload)
│   ├── heartbeat-watcher.js   # 3 autonomous triggers
│   ├── alert-dispatcher.js    # WebSocket alert broadcast
│   ├── ram-reader.js          # Cognitive RAM CRUD
│   └── analyzers/
│       ├── pressure-point.js  # Shallow answer detection
│       ├── contradiction.js   # Resume vs statement checker
│       └── coverage-gap.js    # Competency tracking
├── audio/
│   ├── capture.py             # System audio (WASAPI/BlackHole)
│   ├── transcribe.py          # Whisper STT + diarization
│   └── chunker.py             # 5-sec loop → WebSocket
├── resume/
│   ├── parser.py              # PDF → GPT-4 → YAML
│   └── question-gen.py        # Claims → interview questions
├── scoring/
│   ├── gap-engine.py          # Claims vs transcript evidence
│   ├── integrity-score.py     # Weighted 0-100 score
│   ├── radar-chart.py         # 4-axis polar plot
│   └── pdf-report.py          # Full PDF report generator
├── interfaces/
│   └── whatsapp/
│       └── bot.py             # Twilio WhatsApp webhook
├── memory/
│   └── candidates/            # Cognitive RAM (YAML files)
│       └── _SCHEMA.yaml       # YAML structure template
├── input/
│   └── resumes/               # Drop PDFs here
├── output/
│   └── reports/               # Generated PDF reports
├── package.json               # Node.js config
└── requirements.txt           # Python dependencies
```

## Key Technologies

| Layer | Technology |
|-------|-----------|
| Agent Loop | Node.js 22, WebSocket (ws), Express |
| Audio | sounddevice, faster-whisper (tiny.en) |
| LLM | OpenAI GPT-4 (analysis, parsing) |
| Storage | YAML files (js-yaml + PyYAML) |
| Reporting | matplotlib, reportlab |
| WhatsApp | Twilio API, Flask |
| File Watching | chokidar |

## API Reference

### REST API (http://localhost:3000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Agent health check |
| `/api/candidates` | GET | List all candidates |
| `/api/candidates/:id` | GET | Get candidate data |
| `/api/sessions/start` | POST | Start interview session |
| `/api/sessions/end` | POST | End current session |
| `/api/status` | GET | Daemon status |

### WebSocket (ws://localhost:3000/agent)

| Message Type | Direction | Description |
|-------------|-----------|-------------|
| `transcript_chunk` | Client → Server | Send transcript text |
| `set_candidate` | Client → Server | Set active candidate |
| `start_session` | Client → Server | Begin session |
| `alert` | Server → Client | Real-time nudge |
| `session_start` | Server → Client | Session began |
| `session_end` | Server → Client | Session ended |

## License

MIT
