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
});

// ────────────────────────────────────────────
// Start everything
// ────────────────────────────────────────────

// Register heartbeat callbacks
registerCallbacks({
  onResume: (filePath) => {
    // Trigger 1 fired — resume detected by chokidar.
    // Log and broadcast to all connected clients (overlay, terminal, etc.)
    console.log(`[HEARTBEAT] Resume received: ${filePath}`);
    broadcastEvent('resume_received', { path: filePath });

    // Phase 3: After the resume parser completes and writes to Cognitive RAM,
    // we broadcast questions_ready so the overlay can populate its questions panel.
    // We poll for the candidate YAML to appear (parser runs as a child process).
    const baseName = path.basename(filePath, '.pdf');
    let pollCount = 0;
    const pollInterval = setInterval(() => {
      pollCount++;
      // Check if any new candidate was created in the last 30 seconds
      const candidates = listCandidates();
      for (const cid of candidates) {
        const candidate = readCandidate(cid);
        if (candidate && candidate.generated_questions) {
          const hasQuestions =
            (candidate.generated_questions.technical?.length > 0) ||
            (candidate.generated_questions.system_design?.length > 0) ||
            (candidate.generated_questions.behavioral?.length > 0) ||
            (candidate.generated_questions.role_specific?.length > 0);

          // Check if this candidate was created recently (within last 60s)
          const createdAt = new Date(candidate.created_at).getTime();
          const now = Date.now();
          if (hasQuestions && (now - createdAt) < 60000) {
            // Flatten all question categories into a single array for the overlay
            const allQuestions = [
              ...(candidate.generated_questions.technical || []).map(q => ({ text: q, competency: 'Technical Depth' })),
              ...(candidate.generated_questions.system_design || []).map(q => ({ text: q, competency: 'System Design' })),
              ...(candidate.generated_questions.behavioral || []).map(q => ({ text: q, competency: 'Behavioral' })),
              ...(candidate.generated_questions.role_specific || []).map(q => ({ text: q, competency: 'Role Specific' }))
            ];

            const competencies = ['Technical Depth', 'System Design', 'Behavioral', 'Role Specific'];

            // Broadcast questions_ready to all connected clients
            broadcastEvent('questions_ready', {
              candidate_id: cid,
              candidate_name: candidate.name,
              questions: allQuestions,
              competencies
            });

            console.log(`[HEARTBEAT] Questions ready for ${candidate.name} (${allQuestions.length} questions)`);
            clearInterval(pollInterval);
            return;
          }
        }
      }

      // Give up after 30 seconds (60 polls × 500ms)
      if (pollCount >= 60) {
        console.log('[HEARTBEAT] Timed out waiting for questions — parser may still be running');
        clearInterval(pollInterval);
      }
    }, 500);
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
