/**
 * agent/loop.js — The 5-second processing cycle (GhostCue brain)
 * 
 * This is the load-bearing OpenClaw agent loop. Every 5 seconds:
 * 1. Receives the latest transcript chunk
 * 2. Loads SOUL.md rules (must exist or loop crashes)
 * 3. Loads candidate data from Cognitive RAM (must exist or loop crashes)
 * 4. Runs all three analyzers against the chunk
 * 5. Dispatches any generated alerts
 * 6. Updates Cognitive RAM with new data
 * 
 * CRITICAL: This loop reads SOUL.md and Cognitive RAM BEFORE every GPT call.
 * If either is removed, the loop throws and stops. This is what makes
 * OpenClaw load-bearing — it cannot be replaced by a direct GPT API call.
 */

import { getRules, getRawSoul } from './soul-loader.js';
import { readCandidate, writeCandidate, updateCurrentSession } from './ram-reader.js';
import { analyze as analyzePressure } from './analyzers/pressure-point.js';
import { analyze as analyzeContradiction } from './analyzers/contradiction.js';
import { analyze as analyzeCoverage } from './analyzers/coverage-gap.js';
import { dispatch } from './alert-dispatcher.js';
import { recordChunkReceived, recordEmptyChunk, isSessionActive } from './heartbeat-watcher.js';

// Active session state
let activeCandidateId = null;
let chunkBuffer = [];       // incoming chunks from audio pipeline
let chunkIndex = 0;         // total chunks processed this session
let loopInterval = null;
let isProcessing = false;   // prevent overlapping cycles

/**
 * Set the active candidate for the current interview session.
 * Called when a session starts (from index.js via WebSocket).
 */
export function setActiveCandidate(candidateId) {
  activeCandidateId = candidateId;
  chunkIndex = 0;
  console.log(`[LOOP] Active candidate set: ${candidateId}`);
}

/**
 * Get the current active candidate ID.
 */
export function getActiveCandidate() {
  return activeCandidateId;
}

/**
 * Push a new transcript chunk into the processing buffer.
 * Called by the WebSocket handler when audio pipeline sends data.
 */
export function pushChunk(chunk) {
  chunkBuffer.push(chunk);
}

/**
 * The core 5-second cycle.
 * MUST read SOUL.md and Cognitive RAM before any analysis.
 */
async function processCycle() {
  // Prevent overlapping cycles (in case analysis takes >5 seconds)
  if (isProcessing) {
    return;
  }
  isProcessing = true;

  try {
    // ────────────────────────────────────────────
    // Step 1: Get the latest transcript chunk
    // ────────────────────────────────────────────
    const chunk = chunkBuffer.shift() || null;

    if (!chunk || !chunk.text || chunk.text.trim() === '') {
      // No new audio — track silence for session end detection
      if (isSessionActive()) {
        recordEmptyChunk();
      }
      return;
    }

    // Valid chunk received — reset silence counter
    recordChunkReceived();

    // ────────────────────────────────────────────
    // Step 2: MANDATORY — Load SOUL.md rules
    // OpenClaw compliance: loop must crash if missing
    // ────────────────────────────────────────────
    const rules = getRules();
    if (!rules) {
      throw new Error('[LOOP] FATAL: SOUL.md returned no rules. Cannot proceed.');
    }

    // ────────────────────────────────────────────
    // Step 3: MANDATORY — Load candidate from Cognitive RAM
    // OpenClaw compliance: loop must crash if missing
    // ────────────────────────────────────────────
    if (!activeCandidateId) {
      console.log('[LOOP] No active candidate — skipping analysis');
      return;
    }

    const candidate = readCandidate(activeCandidateId);
    if (!candidate) {
      throw new Error(
        `[LOOP] FATAL: Candidate ${activeCandidateId} not found in Cognitive RAM. ` +
        'Cannot operate without candidate context.'
      );
    }

    chunkIndex++;
    console.log(`[LOOP] Cycle #${chunkIndex} | ${chunk.text.substring(0, 60)}...`);

    // ────────────────────────────────────────────
    // Step 4: Save chunk to session transcript
    // ────────────────────────────────────────────
    const chunkRecord = {
      index: chunkIndex,
      timestamp: chunk.timestamp || new Date().toISOString(),
      speaker: chunk.speaker || 'unknown',
      text: chunk.text
    };

    updateCurrentSession(activeCandidateId, 'transcript_chunks', chunkRecord);

    // ────────────────────────────────────────────
    // Step 5: Run all three analyzers
    // Each analyzer receives SOUL.md rules + Cognitive RAM context
    // ────────────────────────────────────────────
    const allAlerts = [];

    // Analyzer 1: Pressure Point (shallow answer detection)
    try {
      const pressureAlerts = await analyzePressure(chunk.text, rules, {
        candidateName: candidate.name,
        skills: candidate.resume_claims?.skills || [],
        currentTopic: null // TODO: track current topic
      });
      allAlerts.push(...pressureAlerts);
    } catch (err) {
      console.error(`[LOOP] Pressure analyzer failed: ${err.message}`);
    }

    // Analyzer 2: Contradiction (resume vs statement vs history)
    try {
      const contradictionAlerts = await analyzeContradiction(chunk.text, candidate, rules);
      allAlerts.push(...contradictionAlerts);
    } catch (err) {
      console.error(`[LOOP] Contradiction analyzer failed: ${err.message}`);
    }

    // Analyzer 3: Coverage Gap (pure logic, no LLM)
    try {
      const coverageResult = analyzeCoverage(chunk.text, candidate, chunkIndex);
      allAlerts.push(...coverageResult.alerts);

      // Update checklist in RAM
      if (coverageResult.updatedChecklist) {
        updateCurrentSession(activeCandidateId, 'coverage_checklist', coverageResult.updatedChecklist);
      }
    } catch (err) {
      console.error(`[LOOP] Coverage analyzer failed: ${err.message}`);
    }

    // ────────────────────────────────────────────
    // Step 6: Dispatch alerts
    // ────────────────────────────────────────────
    for (const alert of allAlerts) {
      dispatch(alert);

      // Also persist alerts to Cognitive RAM for the report
      try {
        const field = {
          pressure_point: 'pressure_points_fired',
          contradiction: 'flagged_contradictions',
          coverage_gap: 'coverage_gaps_alerted'
        }[alert.type];

        if (field) {
          updateCurrentSession(activeCandidateId, field, {
            timestamp: alert.timestamp,
            message: alert.message,
            evidence: alert.evidence || '',
            severity: alert.severity || 'medium'
          });
        }
      } catch (err) {
        console.error(`[LOOP] Failed to persist alert: ${err.message}`);
      }
    }

  } catch (err) {
    // FATAL errors (missing SOUL.md or RAM) should crash the loop
    if (err.message.includes('FATAL')) {
      console.error(err.message);
      stop();
      throw err;
    }
    // Non-fatal errors: log and continue
    console.error(`[LOOP] Cycle error: ${err.message}`);
  } finally {
    isProcessing = false;
  }
}

/**
 * Start the 5-second processing loop.
 */
export function start() {
  if (loopInterval) {
    console.log('[LOOP] Already running');
    return;
  }

  // Pre-flight check: verify SOUL.md and RAM are available
  try {
    getRules();
    console.log('[LOOP] SOUL.md verified');
  } catch (err) {
    throw new Error(`[LOOP] Cannot start: ${err.message}`);
  }

  loopInterval = setInterval(processCycle, 5000);
  console.log('[LOOP] Agent loop started (5-second cycle)');
}

/**
 * Stop the processing loop.
 */
export function stop() {
  if (loopInterval) {
    clearInterval(loopInterval);
    loopInterval = null;
    console.log('[LOOP] Agent loop stopped');
  }
}

/**
 * Clear session state (called on session end).
 */
export function resetSession() {
  activeCandidateId = null;
  chunkBuffer = [];
  chunkIndex = 0;
  isProcessing = false;
  console.log('[LOOP] Session state cleared');
}
