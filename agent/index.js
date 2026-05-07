/**
 * agent/index.js — GhostCue Agent Daemon Entry Point
 * 
 * Starts the persistent OpenClaw agent as a background daemon:
 * - WebSocket server on ws://localhost:3000/agent (receives transcript chunks)
 * - REST API on http://localhost:3000/api (status, candidates, sessions)
 * - Loads SOUL.md and HEARTBEAT.md on boot (hard fails if missing)
 * - Starts the 5-second agent loop
 * - Starts all three heartbeat triggers
 * 
 * This is the OpenClaw load-bearing daemon. It must be running for
 * GhostCue to function. Without it, the system is dead.
 */

import { WebSocketServer } from 'ws';
import express from 'express';
import { createServer } from 'http';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import multer from 'multer';

// Agent modules
import { healthCheck as soulHealthCheck } from './soul-loader.js';
import { healthCheck as ramHealthCheck, readCandidate, listCandidates, appendSession, createCandidate } from './ram-reader.js';
import { setWebSocketServer, broadcastEvent } from './alert-dispatcher.js';
import { start as startLoop, setActiveCandidate, getActiveCandidate, pushChunk, resetSession } from './loop.js';
import { startAll as startHeartbeat, registerCallbacks, forceSessionEnd, shutdown as shutdownHeartbeat } from './heartbeat-watcher.js';
import chokidar from 'chokidar';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

// Load environment variables
dotenv.config({ path: path.join(PROJECT_ROOT, '.env') });

const PORT = process.env.PORT || 3000;

// ────────────────────────────────────────────
// Pre-flight checks: SOUL.md + Cognitive RAM
// Agent MUST NOT start without these
// ────────────────────────────────────────────

console.log('');
console.log('  ╔══════════════════════════════════════╗');
console.log('  ║     GhostCue Agent Daemon v1.0       ║');
console.log('  ║     OpenClaw Hackathon Build          ║');
console.log('  ╚══════════════════════════════════════╝');
console.log('');

console.log('[BOOT] Running pre-flight checks...');

if (!soulHealthCheck()) {
  console.error('[BOOT] FATAL: SOUL.md health check failed. Cannot start.');
  console.error('[BOOT] Ensure SOUL.md exists at the repo root with Identity and Primary Directive sections.');
  process.exit(1);
}
console.log('[BOOT] SOUL.md .............. OK');

if (!ramHealthCheck()) {
  console.error('[BOOT] FATAL: Cognitive RAM health check failed. Cannot start.');
  console.error('[BOOT] Ensure /memory/candidates/ directory is writable.');
  process.exit(1);
}
console.log('[BOOT] Cognitive RAM ........ OK');

// ────────────────────────────────────────────
// Express + HTTP Server
// ────────────────────────────────────────────

const app = express();
app.use(express.json());

// CORS for development — allows overlay and other local clients to reach the daemon
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE');
  next();
});

// ────────────────────────────────────────────
// Multer config — handles multipart PDF uploads for the overlay interface.
// Saves directly into input/resumes/ so the existing chokidar watcher (Trigger 1)
// automatically picks it up. No new parsing logic needed.
// ────────────────────────────────────────────
const RESUMES_DIR = path.join(PROJECT_ROOT, 'input', 'resumes');

// Ensure resumes directory exists on boot
if (!fs.existsSync(RESUMES_DIR)) {
  fs.mkdirSync(RESUMES_DIR, { recursive: true });
}

const upload = multer({
  // Store files on disk (not in memory) to handle large PDFs without RAM pressure
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, RESUMES_DIR),
    filename: (req, file, cb) => {
      // Sanitize original filename — remove path separators and null bytes
      const safeName = file.originalname.replace(/[\\/:*?"<>|\0]/g, '_');
      cb(null, safeName);
    }
  }),
  limits: {
    fileSize: 10 * 1024 * 1024  // 10 MB hard limit per spec
  },
  fileFilter: (req, file, cb) => {
    // First-pass check: reject obviously non-PDF MIME types
    if (file.mimetype !== 'application/pdf') {
      return cb(new Error('Only PDF files are accepted'));
    }
    cb(null, true);
  }
});

// ── REST API Routes ──

// ── Resume Upload (Phase 1 — Overlay Interface) ──
// Accepts a multipart PDF upload, validates magic bytes, saves to input/resumes/.
// The chokidar watcher (HEARTBEAT Trigger 1) auto-fires resume parsing.
app.post('/api/upload-resume', (req, res, next) => {
  // Use multer single-file upload — field name is 'resume'
  upload.single('resume')(req, res, (err) => {
    // Handle multer-specific errors (file too large, wrong type, etc.)
    if (err instanceof multer.MulterError) {
      if (err.code === 'LIMIT_FILE_SIZE') {
        return res.status(413).json({
          error: 'File too large',
          message: 'Maximum file size is 10 MB',
          code: 'FILE_TOO_LARGE'
        });
      }
      return res.status(400).json({ error: err.message, code: err.code });
    }
    if (err) {
      return res.status(400).json({ error: err.message, code: 'INVALID_FILE' });
    }

    // Ensure a file was actually provided
    if (!req.file) {
      return res.status(400).json({
        error: 'No file uploaded',
        message: 'Attach a PDF file with field name "resume"',
        code: 'NO_FILE'
      });
    }

    // ── Magic byte validation ──
    // PDF files always start with "%PDF" (hex: 25 50 44 46).
    // This catches renamed .exe/.zip files that have a .pdf extension.
    try {
      const fd = fs.openSync(req.file.path, 'r');
      const magicBuf = Buffer.alloc(4);
      fs.readSync(fd, magicBuf, 0, 4, 0);
      fs.closeSync(fd);

      const magic = magicBuf.toString('ascii');
      if (magic !== '%PDF') {
        // Not a real PDF — delete the uploaded file and reject
        fs.unlinkSync(req.file.path);
        return res.status(400).json({
          error: 'Invalid PDF',
          message: 'File does not have valid PDF magic bytes (%PDF header missing)',
          code: 'INVALID_PDF'
        });
      }
    } catch (readErr) {
      // If we can't even read the file, something went very wrong
      return res.status(500).json({
        error: 'Failed to validate file',
        message: readErr.message,
        code: 'VALIDATION_ERROR'
      });
    }

    // Success — file is saved, chokidar will pick it up automatically
    console.log(`[API] Resume uploaded: ${req.file.originalname} (${(req.file.size / 1024).toFixed(1)} KB)`);

    // Broadcast upload event to all WS clients so the overlay can show progress
    broadcastEvent('resume_uploaded', {
      filename: req.file.filename,
      originalName: req.file.originalname,
      size: req.file.size
    });

    res.json({
      status: 'ok',
      filename: req.file.filename,
      message: 'Resume queued for parsing'
    });
  });
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'running',
    soul: soulHealthCheck(),
    ram: ramHealthCheck(),
    activeCandidate: getActiveCandidate(),
    timestamp: new Date().toISOString()
  });
});

// List all candidates
app.get('/api/candidates', (req, res) => {
  const ids = listCandidates();
  const candidates = ids.map(id => {
    const data = readCandidate(id);
    return {
      id: data.candidate_id,
      name: data.name,
      skills_count: data.resume_claims?.skills?.length || 0,
      sessions_count: data.sessions?.length || 0,
      created_at: data.created_at
    };
  });
  res.json({ candidates });
});

// Get specific candidate
app.get('/api/candidates/:id', (req, res) => {
  const data = readCandidate(req.params.id);
  if (!data) {
    return res.status(404).json({ error: 'Candidate not found' });
  }
  res.json(data);
});

// Start a new interview session
app.post('/api/sessions/start', (req, res) => {
  const { candidateId, interviewer } = req.body;

  if (!candidateId) {
    return res.status(400).json({ error: 'candidateId is required' });
  }

  const candidate = readCandidate(candidateId);
  if (!candidate) {
    return res.status(404).json({ error: 'Candidate not found in Cognitive RAM' });
  }

  try {
    const sessionId = appendSession(candidateId, { interviewer: interviewer || '' });
    setActiveCandidate(candidateId);

    broadcastEvent('session_start', {
      candidateId,
      sessionId,
      candidateName: candidate.name
    });

    console.log(`[API] Session started for ${candidate.name} (${sessionId})`);
    res.json({ sessionId, candidateId, candidateName: candidate.name });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// End current session
app.post('/api/sessions/end', (req, res) => {
  const candidateId = getActiveCandidate();
  if (!candidateId) {
    return res.status(400).json({ error: 'No active session' });
  }

  forceSessionEnd();
  broadcastEvent('session_end', { candidateId });
  resetSession();

  console.log('[API] Session ended manually');
  res.json({ status: 'ended', candidateId });
});

// Get agent status
app.get('/api/status', (req, res) => {
  res.json({
    daemon: 'running',
    port: PORT,
    activeCandidate: getActiveCandidate(),
    candidateCount: listCandidates().length,
    uptime: process.uptime(),
    memory: process.memoryUsage()
  });
});

// ── Phase 4 — Manual broadcast recovery endpoint ──
// Reads a candidate YAML and re-broadcasts questions_ready to all WS clients.
// Useful when the auto-broadcast was missed (overlay was closed/refreshing).
app.post('/api/candidates/:id/broadcast', (req, res) => {
  const candidate = readCandidate(req.params.id);
  if (!candidate) {
    return res.status(404).json({ error: 'Candidate not found' });
  }

  const allQuestions = buildQuestionsPayload(candidate);
  if (!allQuestions) {
    return res.status(400).json({ error: 'Candidate has no generated questions yet' });
  }

  broadcastEvent('questions_ready', {
    candidate_id: candidate.candidate_id,
    candidate_name: candidate.name,
    questions: allQuestions,
    competencies: ['Technical Depth', 'System Design', 'Behavioral', 'Role Specific']
  });

  // Count connected clients
  let clientCount = 0;
  wss.clients.forEach(c => { if (c.readyState === 1) clientCount++; });

  console.log(`[API] Manual broadcast for ${candidate.name} → ${clientCount} client(s)`);
  res.json({ status: 'ok', broadcast_to: clientCount });
});

const httpServer = createServer(app);

// ────────────────────────────────────────────
// WebSocket Server
// ────────────────────────────────────────────

const wss = new WebSocketServer({ server: httpServer, path: '/agent' });
setWebSocketServer(wss);

wss.on('connection', (ws, req) => {
  const clientAddr = req.socket.remoteAddress;
  console.log(`[WS] Client connected: ${clientAddr}`);

  ws.on('message', (data) => {
    try {
      const message = JSON.parse(data.toString());

      switch (message.type) {
        case 'transcript_chunk':
          // Incoming audio transcript from chunker.py
          pushChunk({
            text: message.text || '',
            speaker: message.speaker || 'unknown',
            timestamp: message.timestamp || new Date().toISOString()
          });
          break;

        case 'set_candidate':
          // Set active candidate for the session
          setActiveCandidate(message.candidateId);
          ws.send(JSON.stringify({ event: 'candidate_set', candidateId: message.candidateId }));
          break;

        case 'start_session':
          // Start a new session
          if (message.candidateId) {
            const sessionId = appendSession(message.candidateId, {
              interviewer: message.interviewer || ''
            });
            setActiveCandidate(message.candidateId);
            ws.send(JSON.stringify({ event: 'session_started', sessionId }));
          }
          break;

        case 'end_session':
          forceSessionEnd();
          resetSession();
          ws.send(JSON.stringify({ event: 'session_ended' }));
          break;

        case 'ping':
          ws.send(JSON.stringify({ event: 'pong', timestamp: new Date().toISOString() }));
          break;

        default:
          console.log(`[WS] Unknown message type: ${message.type}`);
      }
    } catch (err) {
      console.error(`[WS] Invalid message: ${err.message}`);
    }
  });

  ws.on('close', () => {
    console.log(`[WS] Client disconnected: ${clientAddr}`);
  });

  // Send welcome message with agent status
  ws.send(JSON.stringify({
    event: 'connected',
    agent: 'ghostcue',
    activeCandidate: getActiveCandidate(),
    candidateCount: listCandidates().length
  }));

  // ── Phase 3 — Send latest parsed candidate to newly connected client ──
  // Overlay refresh should never require re-uploading a resume.
  // Find the most recently created candidate that has questions and send immediately.
  try {
    const latestCandidate = getMostRecentCandidate();
    if (latestCandidate) {
      const questions = buildQuestionsPayload(latestCandidate);
      if (questions && questions.length > 0) {
        ws.send(JSON.stringify({
          event: 'questions_ready',
          data: {
            candidate_id: latestCandidate.candidate_id,
            candidate_name: latestCandidate.name,
            questions,
            competencies: ['Technical Depth', 'System Design', 'Behavioral', 'Role Specific'],
            timestamp: new Date().toISOString()
          }
        }));
        console.log(`[WS] Sent latest candidate to new client: ${latestCandidate.candidate_id}`);
      }
    }
  } catch (err) {
    // Non-fatal — new clients still connect even if we can't send history
    console.error(`[WS] Failed to send latest candidate on connect: ${err.message}`);
  }
});

// ────────────────────────────────────────────
// Start everything
// ────────────────────────────────────────────

// ────────────────────────────────────────────
// Shared helpers — used by broadcast, connect handler, and YAML watcher
// ────────────────────────────────────────────

/**
 * Flatten a candidate's generated_questions into the array format the overlay expects.
 * Returns null if the candidate has no questions yet.
 */
function buildQuestionsPayload(candidate) {
  const gq = candidate?.generated_questions;
  if (!gq) return null;

  const all = [
    ...(gq.technical || []).map(q => ({ text: q, competency: 'Technical Depth' })),
    ...(gq.system_design || []).map(q => ({ text: q, competency: 'System Design' })),
    ...(gq.behavioral || []).map(q => ({ text: q, competency: 'Behavioral' })),
    ...(gq.role_specific || []).map(q => ({ text: q, competency: 'Role Specific' }))
  ];

  return all.length > 0 ? all : null;
}

/**
 * Return the most recently created candidate that has questions.
 * Scans all YAMLs, sorts by created_at descending.
 */
function getMostRecentCandidate() {
  const ids = listCandidates();
  const candidates = ids
    .map(id => { try { return readCandidate(id); } catch { return null; } })
    .filter(Boolean)
    .filter(c => buildQuestionsPayload(c) !== null)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  return candidates[0] || null;
}

// ────────────────────────────────────────────
// Phase 1+2 — YAML watcher on memory/candidates/
//
// Instead of polling after a resume drop, we watch the output directory
// for new/changed YAML files. When question-gen.py finishes writing, this
// fires immediately — no timeout, no blocking, no missed broadcasts.
//
// 120s timeout — Groq parsing can take 30–60s on slow networks
// (The watcher itself has no timeout — it just listens forever)
// ────────────────────────────────────────────

const CANDIDATES_DIR = path.join(PROJECT_ROOT, 'memory', 'candidates');

// Track which candidate IDs we've already broadcast so we don't double-fire
// on a chokidar 'change' event that is unrelated to question generation.
const broadcastedCandidates = new Set();

// Persist the time a resume was last dropped so we can filter YAML events
// to only those created after the most recent upload.
let lastResumeDropTime = 0;

const yamlWatcher = chokidar.watch(CANDIDATES_DIR, {
  ignored: /(^|[\/\\])[\.#_]|_SCHEMA\.yaml|_health_check\.tmp/,  // skip schema, temp files
  ignoreInitial: true,          // don't fire for YAMLs that already existed at startup
  awaitWriteFinish: {
    stabilityThreshold: 1500,   // wait 1.5s after last write before firing (parser writes incrementally)
    pollInterval: 200
  }
});

yamlWatcher.on('add', (filePath) => handleYamlEvent(filePath, 'add'));
yamlWatcher.on('change', (filePath) => handleYamlEvent(filePath, 'change'));

/**
 * Called when a YAML file in memory/candidates/ is created or updated.
 * Reads the file, checks for questions, and broadcasts if ready.
 */
function handleYamlEvent(filePath, eventType) {
  // Only care about candidate YAML files (not schema or temp files)
  if (!filePath.endsWith('.yaml')) return;
  const baseName = path.basename(filePath);
  if (baseName.startsWith('_')) return;

  // Extract candidate ID from filename (e.g. abc-123.yaml → abc-123)
  const candidateId = baseName.replace('.yaml', '');

  // Debounce: skip if we already broadcast for this candidate in this session
  // (question-gen.py may trigger multiple 'change' events as it writes)
  if (broadcastedCandidates.has(candidateId)) return;

  try {
    const candidate = readCandidate(candidateId);
    if (!candidate) return;

    const questions = buildQuestionsPayload(candidate);
    if (!questions) return; // questions not written yet — another change event will come

    // Only broadcast for candidates created after the last resume drop
    // (prevents re-broadcasting old candidates on unrelated YAML edits)
    const createdAt = new Date(candidate.created_at).getTime();
    if (createdAt < lastResumeDropTime - 5000) {
      return; // this YAML predates the current upload session
    }

    // Mark as broadcast so we don't fire again on subsequent change events
    broadcastedCandidates.add(candidateId);

    broadcastEvent('questions_ready', {
      candidate_id: candidateId,
      candidate_name: candidate.name,
      questions,
      competencies: ['Technical Depth', 'System Design', 'Behavioral', 'Role Specific']
    });

    let clientCount = 0;
    wss.clients.forEach(c => { if (c.readyState === 1) clientCount++; });
    console.log(`[WS] Broadcast questions_ready to ${clientCount} client(s) — ${candidate.name} (${questions.length} questions)`);

  } catch (err) {
    console.error(`[HEARTBEAT] Failed to broadcast from YAML watcher: ${err.message}`);
  }
}

// Register heartbeat callbacks
registerCallbacks({
  onResume: (filePath) => {
    // Trigger 1 fired — resume detected by chokidar on input/resumes/.
    // Record the drop time so the YAML watcher can filter correctly.
    lastResumeDropTime = Date.now();
    console.log(`[HEARTBEAT] Resume received: ${filePath}`);
    broadcastEvent('resume_received', { path: filePath });

    // Phase 1+2: Parser runs as a non-blocking background subprocess (spawned by
    // heartbeat-watcher.js). We do NOT poll or wait here.
    // The yamlWatcher above on memory/candidates/ will fire questions_ready
    // automatically when question-gen.py finishes writing — no timeout needed.
    console.log('[HEARTBEAT] Parser running in background — will broadcast on completion');
  },
  onSilence: () => {
    console.log('[HEARTBEAT] Session ended (silence detected)');
    broadcastEvent('session_end', { reason: 'silence', candidateId: getActiveCandidate() });
    resetSession();
  },
  onPeriodic: () => {
    // Periodic checks are handled by the main loop
  }
});

// Start heartbeat triggers
try {
  startHeartbeat();
  console.log('[BOOT] Heartbeat ........... OK');
} catch (err) {
  console.error(`[BOOT] FATAL: ${err.message}`);
  process.exit(1);
}

// Start the agent loop
try {
  startLoop();
  console.log('[BOOT] Agent Loop .......... OK');
} catch (err) {
  console.error(`[BOOT] FATAL: ${err.message}`);
  process.exit(1);
}

// Start HTTP + WebSocket server
httpServer.listen(PORT, () => {
  console.log('');
  console.log(`[BOOT] GhostCue daemon is live!`);
  console.log(`  REST API:   http://localhost:${PORT}/api`);
  console.log(`  WebSocket:  ws://localhost:${PORT}/agent`);
  console.log(`  Health:     http://localhost:${PORT}/api/health`);
  console.log('');
  console.log('[BOOT] Waiting for interviews...');
  console.log('');
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n[SHUTDOWN] Shutting down GhostCue...');
  shutdownHeartbeat();
  httpServer.close();
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n[SHUTDOWN] SIGTERM received, shutting down...');
  shutdownHeartbeat();
  httpServer.close();
  process.exit(0);
});
