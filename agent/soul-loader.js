/**
 * agent/soul-loader.js — Reads and parses SOUL.md
 * 
 * Loads the agent's behavioral rulebook from SOUL.md at the repo root.
 * Extracts structured rules that the agent loop applies before every GPT call.
 * 
 * CRITICAL: If SOUL.md is missing or unreadable, the agent MUST NOT start.
 * This is what makes OpenClaw load-bearing — without SOUL.md, no operation.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SOUL_PATH = path.resolve(__dirname, '..', 'SOUL.md');

// Cached rules — reloaded on every cycle to support hot-reload
let cachedRules = null;
let lastModified = 0;

/**
 * Parse SOUL.md into structured rules the analyzers can consume.
 * Extracts sections by ## headers and converts bullet points into arrays.
 */
function parseSoulFile(content) {
  const sections = {};
  let currentSection = null;

  for (const line of content.split('\n')) {
    const headerMatch = line.match(/^##\s+(.+)/);
    if (headerMatch) {
      currentSection = headerMatch[1].trim().toLowerCase().replace(/\s+/g, '_');
      sections[currentSection] = [];
      continue;
    }

    if (currentSection && line.trim()) {
      // Strip leading "- " or "1. " from bullet points
      const cleaned = line.trim().replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '');
      if (cleaned) {
        sections[currentSection].push(cleaned);
      }
    }
  }

  return sections;
}

/**
 * Load SOUL.md rules. Re-reads from disk if file has changed.
 * Throws a hard error if SOUL.md is missing — agent cannot operate without it.
 * 
 * @returns {object} parsed rules keyed by section name
 */
export function getRules() {
  if (!fs.existsSync(SOUL_PATH)) {
    throw new Error(
      '[SOUL] FATAL: SOUL.md not found at repo root. ' +
      'Agent cannot operate without behavioral rules. ' +
      'This is an OpenClaw compliance requirement.'
    );
  }

  try {
    const stat = fs.statSync(SOUL_PATH);
    const mtime = stat.mtimeMs;

    // Only re-parse if file has changed (hot-reload support)
    if (mtime !== lastModified || !cachedRules) {
      const content = fs.readFileSync(SOUL_PATH, 'utf-8');
      cachedRules = parseSoulFile(content);
      lastModified = mtime;
      console.log(`[SOUL] Rules loaded (${Object.keys(cachedRules).length} sections)`);
    }

    return cachedRules;
  } catch (err) {
    throw new Error(`[SOUL] FATAL: Cannot read SOUL.md: ${err.message}`);
  }
}

/**
 * Get the raw SOUL.md content as a string.
 * Used by analyzers that pass the full soul context to GPT-4.
 */
export function getRawSoul() {
  if (!fs.existsSync(SOUL_PATH)) {
    throw new Error('[SOUL] FATAL: SOUL.md not found');
  }
  return fs.readFileSync(SOUL_PATH, 'utf-8');
}

/**
 * Get specific rules for a section (e.g., "what_i_detect", "nudge_format_rules").
 * Returns an empty array if section doesn't exist.
 */
export function getSection(sectionName) {
  const rules = getRules();
  return rules[sectionName] || [];
}

/**
 * Health check — verifies SOUL.md exists and is parseable.
 * Called on agent boot. Returns false if agent should refuse to start.
 */
export function healthCheck() {
  try {
    const rules = getRules();
    const hasIdentity = rules.identity && rules.identity.length > 0;
    const hasDirective = rules.primary_directive && rules.primary_directive.length > 0;
    return hasIdentity && hasDirective;
  } catch {
    return false;
  }
}
