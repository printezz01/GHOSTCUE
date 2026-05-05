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
import { fileURLToPath } from 'url';

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

// CORS for development
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE');
  next();
});

// ── REST API Routes ──

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
    console.log(`[HEARTBEAT] Resume received: ${filePath}`);
    broadcastEvent('resume_received', { path: filePath });
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
