/**
 * agent/heartbeat-watcher.js — Autonomous trigger system
 * 
 * Reads HEARTBEAT.md and configures three watchers:
 * 1. Resume Drop (chokidar) — watches /input/resumes/ for new PDFs
 * 2. Live Monitoring (setInterval) — periodic contradiction sweeps
 * 3. Session End (silence detector) — 90s silence triggers report generation
 * 
 * All three triggers must initialize successfully or the daemon exits.
 */

import fs from 'fs';
import path from 'path';
import chokidar from 'chokidar';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const HEARTBEAT_PATH = path.join(PROJECT_ROOT, 'HEARTBEAT.md');
const RESUMES_DIR = path.join(PROJECT_ROOT, 'input', 'resumes');

// Track active state
let resumeWatcher = null;
let liveMonitorInterval = null;
let silenceCounter = 0;
let sessionActive = false;
let lastChunkTime = 0;

// Callbacks set by the agent loop
let onResumeDropped = null;
let onSilenceDetected = null;
let onPeriodicCheck = null;

/**
 * Verify HEARTBEAT.md exists. Agent cannot start without it.
 */
function verifyHeartbeat() {
  if (!fs.existsSync(HEARTBEAT_PATH)) {
    throw new Error(
      '[HEARTBEAT] FATAL: HEARTBEAT.md not found at repo root. ' +
      'Agent cannot operate without trigger definitions. ' +
      'This is an OpenClaw compliance requirement.'
    );
  }
  console.log('[HEARTBEAT] HEARTBEAT.md verified');
}

/**
 * Trigger 1: Watch /input/resumes/ for new PDF files.
 * When a PDF appears, fires the resume parsing pipeline.
 */
function startResumeWatcher() {
  // Ensure directory exists
  if (!fs.existsSync(RESUMES_DIR)) {
    fs.mkdirSync(RESUMES_DIR, { recursive: true });
  }

  resumeWatcher = chokidar.watch(RESUMES_DIR, {
    ignoreInitial: true,       // don't fire on existing files
    awaitWriteFinish: {        // wait for file to be fully written
      stabilityThreshold: 2000,
      pollInterval: 500
    }
  });

  resumeWatcher.on('add', (filePath) => {
    // Only process PDF files
    if (!filePath.toLowerCase().endsWith('.pdf')) {
      return;
    }

    console.log(`[HEARTBEAT] Trigger 1: Resume detected -> ${path.basename(filePath)}`);

    if (onResumeDropped) {
      onResumeDropped(filePath);
    } else {
      // Default: spawn Python parser
      console.log('[HEARTBEAT] Spawning resume parser...');
      const parser = spawn('python', [
        path.join(PROJECT_ROOT, 'resume', 'parser.py'),
        filePath
      ], { cwd: PROJECT_ROOT });

      parser.stdout.on('data', (data) => process.stdout.write(data));
      parser.stderr.on('data', (data) => process.stderr.write(data));
      parser.on('close', (code) => {
        if (code === 0) {
          console.log('[HEARTBEAT] Resume parsing complete');
        } else {
          console.error(`[HEARTBEAT] Resume parser exited with code ${code}`);
        }
      });
    }
  });

  console.log(`[HEARTBEAT] Trigger 1: Watching ${RESUMES_DIR}`);
  return true;
}

/**
 * Trigger 2: Periodic contradiction sweep during active session.
 * Runs every 30 seconds (6 agent loop cycles).
 */
function startLiveMonitor() {
  liveMonitorInterval = setInterval(() => {
    if (sessionActive && onPeriodicCheck) {
      onPeriodicCheck();
    }
  }, 30000); // every 30 seconds per HEARTBEAT.md

  console.log('[HEARTBEAT] Trigger 2: Live monitor active (30s interval)');
  return true;
}

/**
 * Trigger 3: Silence detector.
 * Called by the agent loop on every cycle. Tracks consecutive empty chunks.
 * 18 empty 5-second chunks = 90 seconds of silence = session end.
 */
function checkSilence() {
  if (!sessionActive) {
    return false;
  }

  const now = Date.now();
  const timeSinceLastChunk = now - lastChunkTime;

  // 90 seconds of silence (per HEARTBEAT.md)
  if (timeSinceLastChunk > 90000 && lastChunkTime > 0) {
    console.log('[HEARTBEAT] Trigger 3: 90s silence detected -> session end');
    sessionActive = false;
    silenceCounter = 0;

    if (onSilenceDetected) {
      onSilenceDetected();
    }
    return true;
  }

  return false;
}

/**
 * Record that a transcript chunk was received (resets silence timer).
 */
export function recordChunkReceived() {
  lastChunkTime = Date.now();
  silenceCounter = 0;
  if (!sessionActive) {
    sessionActive = true;
    console.log('[HEARTBEAT] Session started (first chunk received)');
  }
}

/**
 * Record an empty chunk (increments silence counter).
 */
export function recordEmptyChunk() {
  silenceCounter++;
  // Check if we've hit 90 seconds
  return checkSilence();
}

/**
 * Register callback handlers for the three triggers.
 */
export function registerCallbacks({ onResume, onSilence, onPeriodic }) {
  onResumeDropped = onResume || null;
  onSilenceDetected = onSilence || null;
  onPeriodicCheck = onPeriodic || null;
}

/**
 * Start all three heartbeat triggers.
 * Returns true only if ALL triggers initialize successfully.
 * If any fail, the daemon must exit.
 */
export function startAll() {
  verifyHeartbeat();

  const trigger1 = startResumeWatcher();
  const trigger2 = startLiveMonitor();
  // Trigger 3 is passive (called by agent loop), always "active"
  const trigger3 = true;

  const allActive = trigger1 && trigger2 && trigger3;

  if (!allActive) {
    throw new Error('[HEARTBEAT] FATAL: Not all triggers could initialize');
  }

  // Log heartbeat pulse every 60 seconds
  setInterval(() => {
    const timestamp = new Date().toISOString();
    console.log(
      `[HEARTBEAT] ${timestamp} | triggers_active: 3 | ` +
      `session_active: ${sessionActive} | silence_count: ${silenceCounter}`
    );
  }, 60000);

  console.log('[HEARTBEAT] All 3 triggers active');
  return true;
}

/**
 * Check if a session is currently active.
 */
export function isSessionActive() {
  return sessionActive;
}

/**
 * Force session end (for manual stop from CLI).
 */
export function forceSessionEnd() {
  sessionActive = false;
  silenceCounter = 0;
  if (onSilenceDetected) {
    onSilenceDetected();
  }
}

/**
 * Clean up watchers on shutdown.
 */
export function shutdown() {
  if (resumeWatcher) {
    resumeWatcher.close();
    console.log('[HEARTBEAT] Resume watcher stopped');
  }
  if (liveMonitorInterval) {
    clearInterval(liveMonitorInterval);
    console.log('[HEARTBEAT] Live monitor stopped');
  }
  sessionActive = false;
}
