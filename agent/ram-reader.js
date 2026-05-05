/**
 * ram-reader.js — Cognitive RAM interface for GhostCue
 * 
 * Reads and writes per-candidate YAML files in /memory/candidates/.
 * This is the durable memory layer that persists across sessions.
 * The agent loop calls these functions on every 5-second cycle.
 * 
 * If Cognitive RAM is unavailable, the agent loop MUST stop.
 * Stateless operation is never allowed (SOUL.md compliance).
 */

import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import { v4 as uuidv4 } from 'uuid';
import { fileURLToPath } from 'url';

// Resolve paths relative to project root (not this file)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const CANDIDATES_DIR = path.join(PROJECT_ROOT, 'memory', 'candidates');
const SCHEMA_PATH = path.join(CANDIDATES_DIR, '_SCHEMA.yaml');

/**
 * Ensure the candidates directory exists.
 * Throws if it can't be created — no silent failures.
 */
function ensureDir() {
  if (!fs.existsSync(CANDIDATES_DIR)) {
    fs.mkdirSync(CANDIDATES_DIR, { recursive: true });
  }
}

/**
 * Build the file path for a candidate's YAML file.
 * @param {string} candidateId — UUID of the candidate
 * @returns {string} absolute path to the YAML file
 */
function candidatePath(candidateId) {
  return path.join(CANDIDATES_DIR, `${candidateId}.yaml`);
}

/**
 * Read a candidate's full YAML data from Cognitive RAM.
 * Returns null if the candidate doesn't exist (not an error — just means new candidate).
 * Throws on malformed YAML — data corruption should never be silent.
 * 
 * @param {string} candidateId — UUID of the candidate
 * @returns {object|null} parsed candidate data or null
 */
export function readCandidate(candidateId) {
  const filePath = candidatePath(candidateId);

  if (!fs.existsSync(filePath)) {
    return null;
  }

  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const data = yaml.load(raw);
    return data;
  } catch (err) {
    throw new Error(`[RAM] Corrupt YAML for candidate ${candidateId}: ${err.message}`);
  }
}

/**
 * Write a candidate's full data to Cognitive RAM.
 * Overwrites the entire file — use appendSession() for incremental updates.
 * 
 * @param {string} candidateId — UUID of the candidate
 * @param {object} data — full candidate object matching _SCHEMA.yaml
 */
export function writeCandidate(candidateId, data) {
  ensureDir();
  const filePath = candidatePath(candidateId);

  try {
    const yamlStr = yaml.dump(data, {
      indent: 2,
      lineWidth: 120,
      noRefs: true,       // avoid YAML anchors — keep files human-readable
      sortKeys: false      // preserve insertion order for readability
    });
    fs.writeFileSync(filePath, yamlStr, 'utf-8');
  } catch (err) {
    throw new Error(`[RAM] Failed to write candidate ${candidateId}: ${err.message}`);
  }
}

/**
 * Create a brand-new candidate record from parsed resume data.
 * Generates a UUID, timestamps it, and writes the initial YAML.
 * 
 * @param {object} resumeData — parsed resume fields (name, skills, projects, etc.)
 * @returns {string} the new candidate's UUID
 */
export function createCandidate(resumeData) {
  const candidateId = uuidv4();
  const now = new Date().toISOString();

  const candidate = {
    candidate_id: candidateId,
    name: resumeData.name || 'Unknown',
    email: resumeData.email || '',
    phone: resumeData.phone || '',
    created_at: now,
    resume_claims: {
      skills: resumeData.skills || [],
      years_experience: resumeData.years_experience || 0,
      education: resumeData.education || [],
      projects: resumeData.projects || [],
      certifications: resumeData.certifications || [],
      summary: resumeData.summary || ''
    },
    generated_questions: {
      technical: resumeData.questions?.technical || [],
      system_design: resumeData.questions?.system_design || [],
      behavioral: resumeData.questions?.behavioral || [],
      role_specific: resumeData.questions?.role_specific || []
    },
    sessions: [],
    cross_session_summary: '',
    cross_session_flags: []
  };

  writeCandidate(candidateId, candidate);
  return candidateId;
}

/**
 * Append a new interview session to an existing candidate.
 * Creates the session scaffold and adds it to the sessions array.
 * 
 * @param {string} candidateId — UUID of the candidate
 * @param {object} sessionData — optional overrides (interviewer, etc.)
 * @returns {string} the new session's UUID
 */
export function appendSession(candidateId, sessionData = {}) {
  const candidate = readCandidate(candidateId);
  if (!candidate) {
    throw new Error(`[RAM] Cannot append session — candidate ${candidateId} not found`);
  }

  const sessionId = uuidv4();
  const roundNumber = (candidate.sessions?.length || 0) + 1;

  const session = {
    session_id: sessionId,
    round_number: roundNumber,
    started_at: new Date().toISOString(),
    ended_at: '',
    interviewer: sessionData.interviewer || '',
    transcript_path: '',
    transcript_chunks: [],
    flagged_contradictions: [],
    pressure_points_fired: [],
    coverage_gaps_alerted: [],
    coverage_checklist: {
      technical_depth: false,
      system_design: false,
      behavioral: false,
      culture_fit: false
    },
    scoring: {
      integrity_score: null,
      technical_depth_score: null,
      resume_honesty_score: null,
      communication_score: null,
      overall_fit_score: null
    },
    report_path: '',
    report_status: 'pending',
    approved_at: ''
  };

  candidate.sessions.push(session);
  writeCandidate(candidateId, candidate);
  return sessionId;
}

/**
 * Update a specific field in the current (latest) session.
 * Used by the agent loop to append transcript chunks, alerts, etc.
 * 
 * @param {string} candidateId — UUID of the candidate
 * @param {string} field — field name within the session object
 * @param {*} value — value to set (or append if field is an array)
 */
export function updateCurrentSession(candidateId, field, value) {
  const candidate = readCandidate(candidateId);
  if (!candidate || !candidate.sessions?.length) {
    throw new Error(`[RAM] No active session for candidate ${candidateId}`);
  }

  // Always update the latest (current) session
  const currentSession = candidate.sessions[candidate.sessions.length - 1];

  // If the field is an array and value is not, append to it
  if (Array.isArray(currentSession[field]) && !Array.isArray(value)) {
    currentSession[field].push(value);
  } else {
    currentSession[field] = value;
  }

  writeCandidate(candidateId, candidate);
}

/**
 * Get the latest session for a candidate.
 * Returns null if no sessions exist.
 * 
 * @param {string} candidateId — UUID of the candidate
 * @returns {object|null} the most recent session object
 */
export function getCurrentSession(candidateId) {
  const candidate = readCandidate(candidateId);
  if (!candidate || !candidate.sessions?.length) {
    return null;
  }
  return candidate.sessions[candidate.sessions.length - 1];
}

/**
 * List all candidate IDs in Cognitive RAM.
 * Skips the schema template and .gitkeep files.
 * 
 * @returns {string[]} array of candidate UUIDs
 */
export function listCandidates() {
  ensureDir();
  return fs.readdirSync(CANDIDATES_DIR)
    .filter(f => f.endsWith('.yaml') && !f.startsWith('_') && f !== '.gitkeep')
    .map(f => f.replace('.yaml', ''));
}

/**
 * Check if Cognitive RAM is healthy and accessible.
 * The agent loop calls this on boot — if false, it must refuse to start.
 * 
 * @returns {boolean} true if RAM directory exists and is writable
 */
export function healthCheck() {
  try {
    ensureDir();
    // Try writing and reading a test file
    const testPath = path.join(CANDIDATES_DIR, '_health_check.tmp');
    fs.writeFileSync(testPath, 'ok', 'utf-8');
    const result = fs.readFileSync(testPath, 'utf-8');
    fs.unlinkSync(testPath); // clean up
    return result === 'ok';
  } catch {
    return false;
  }
}
