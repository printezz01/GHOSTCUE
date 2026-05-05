# GhostCue Heartbeat — Autonomous Triggers

The Heartbeat system defines the three autonomous triggers that drive the
GhostCue agent daemon. The heartbeat-watcher reads this file on boot and
configures watchers, intervals, and silence detectors accordingly.

---

## Trigger 1: Resume Drop (Pre-Session)

- **Watch**: `/input/resumes/`
- **Event**: New PDF file appears (detected via chokidar file watcher)
- **Action**:
  1. Parse PDF text using pypdf2
  2. Send extracted text to GPT-4 with structured JSON-output prompt
  3. Extract: skills, tech stack, years of experience, projects, certifications
  4. Generate 8–12 custom interview questions weighted by experience level
  5. Build competency checklist with four axes:
     - Technical Depth
     - System Design
     - Behavioral
     - Culture Fit
  6. Write candidate YAML to `/memory/candidates/{candidate_id}.yaml`
  7. Broadcast question set to all connected clients via WebSocket
- **SLA**: Complete within 30 seconds of PDF drop
- **Failure**: If parsing fails, broadcast error alert and write empty YAML scaffold

---

## Trigger 2: Live Monitoring (During Session)

- **Frequency**: Every 5 seconds during an active session
- **Activation**: First transcript chunk received via WebSocket marks session start
- **Action per cycle**:
  1. Receive latest transcript chunk from audio pipeline
  2. Append chunk to session transcript buffer
  3. Run Pressure Point analyzer:
     - Detect shallow, vague, or incomplete answers
     - Generate follow-up probe suggestion (max 12 words)
  4. Run Contradiction analyzer:
     - Compare new statements against resume claims in Cognitive RAM
     - Compare against all prior transcript statements in this session
     - Flag confirmed or possible contradictions with evidence
  5. Run Coverage Gap analyzer:
     - Check competency checklist items still marked `false`
     - If session has passed 50% estimated time, nudge on uncovered topics
     - If session has passed 80% estimated time, escalate urgency
  6. Dispatch any generated alerts to connected clients
  7. Update session data in Cognitive RAM
- **Silence handling**: If 5 consecutive chunks are empty (25 seconds), reduce
  analysis frequency to every 15 seconds to conserve resources
- **Failure**: If GPT-4 call fails, skip that analyzer for this cycle, retry next

---

## Trigger 3: Session End (Post-Session)

- **Detection**: 90 consecutive seconds of silence in the audio stream
  (18 consecutive empty 5-second chunks)
- **Action sequence**:
  1. Mark session as `ended` in Cognitive RAM
  2. Stop accepting new transcript chunks
  3. Run Gap Engine over the full session transcript:
     - For each resume claim, find supporting/contradicting evidence in transcript
     - Score each claim as `confirmed`, `vague`, or `contradicted`
  4. Calculate Candidate Integrity Score (0–100):
     - Technical Depth: 30% weight
     - Resume Honesty: 30% weight
     - Communication: 20% weight
     - Overall Fit: 20% weight
  5. Generate 4-axis radar chart (matplotlib polar plot, saved as PNG)
  6. Compile PDF report with:
     - Candidate name and session metadata
     - Integrity Score (prominent display)
     - Radar chart image
     - Red flags and contradictions with timestamps
     - Coverage checklist results
     - Full transcript appendix
  7. Save report to `/output/reports/{candidate_id}_{timestamp}.pdf`
  8. Update `/memory/candidates/{candidate_id}.yaml` with session results
  9. Broadcast report-ready notification to all connected clients
- **Human Gate**: Report is marked as `draft` until interviewer explicitly approves.
  No downstream action (logging, comparison, sharing) occurs until approval.
- **Cross-session**: If this candidate has prior sessions, include a
  "Cross-Round Consistency" section comparing claims across rounds.
- **Failure**: If report generation fails, save raw transcript and partial data.
  Alert interviewer that manual review is needed.

---

## Heartbeat Health Check

The daemon logs a heartbeat pulse every 60 seconds to stdout:
```
[HEARTBEAT] 2024-01-15T10:30:00Z | triggers_active: 3 | sessions_active: 1 | ram_ok: true
```

If any trigger fails to initialize on boot, the daemon logs an error and exits
with code 1. Partial operation is not allowed — all three triggers must be live.
