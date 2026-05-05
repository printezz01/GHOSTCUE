/**
 * agent/analyzers/pressure-point.js — Detects shallow answers
 * 
 * Analyzes transcript chunks to identify when a candidate gives a vague,
 * surface-level, or incomplete answer that needs a follow-up probe.
 * 
 * Uses GPT-4 with SOUL.md rules to generate actionable nudges
 * (max 12 words per SOUL.md Nudge Format Rules).
 */

import OpenAI from 'openai';

// Indicators of shallow answers (used for quick pre-screening before GPT call)
const SHALLOW_SIGNALS = [
  'i think', 'maybe', 'sort of', 'kind of', 'i guess',
  'not sure', 'i believe', 'probably', 'something like',
  'we did', 'the team', 'it was done'  // deflects ownership
];

// Minimum chunk length to analyze (skip very short chunks)
const MIN_CHUNK_LENGTH = 20;

/**
 * Analyze a transcript chunk for shallow or vague answers.
 * Returns an array of alert objects (empty if answer seems sufficient).
 * 
 * @param {string} chunk — the latest transcript text
 * @param {object} soulRules — parsed SOUL.md rules
 * @param {object} context — { candidateName, skills, currentTopic }
 * @returns {Promise<Array>} array of pressure point alerts
 */
export async function analyze(chunk, soulRules, context = {}) {
  // Skip if chunk is too short to be meaningful
  if (!chunk || chunk.length < MIN_CHUNK_LENGTH) {
    return [];
  }

  // Quick pre-screen: check for shallow signal words
  const chunkLower = chunk.toLowerCase();
  const hasShallowSignal = SHALLOW_SIGNALS.some(s => chunkLower.includes(s));

  // If no shallow signals detected and chunk is reasonably detailed, skip GPT call
  if (!hasShallowSignal && chunk.length > 100) {
    return [];
  }

  // Call GPT-4 for deeper analysis
  const apiKey = process.env.OPENAI_API_KEY || '';
  if (!apiKey || apiKey.startsWith('sk-your')) {
    // Fallback: use heuristic analysis when no API key
    return heuristicAnalysis(chunk, context);
  }

  try {
    const client = new OpenAI({ apiKey });

    const response = await client.chat.completions.create({
      model: 'gpt-4',
      messages: [
        {
          role: 'system',
          content: `You are GhostCue's pressure point analyzer. Your job is to detect when 
an interview candidate gives a shallow, vague, or incomplete answer.

Rules from SOUL.md:
- Fire short, action-oriented nudges (max 12 words)
- Nudges start with an action verb: "Ask about...", "Probe...", "Clarify..."
- Stay silent when the interview is flowing well

Return JSON: { "is_shallow": true/false, "nudge": "Ask about..." or null, "reason": "brief explanation" }`
        },
        {
          role: 'user',
          content: `Transcript chunk: "${chunk}"\n\nCandidate skills: ${context.skills?.join(', ') || 'unknown'}`
        }
      ],
      temperature: 0.3,
      max_tokens: 150,
      response_format: { type: 'json_object' }
    });

    const result = JSON.parse(response.choices[0].message.content);

    if (result.is_shallow && result.nudge) {
      return [{
        type: 'pressure_point',
        message: result.nudge.substring(0, 80),  // enforce max length
        evidence: result.reason || '',
        severity: 'medium',
        timestamp: new Date().toISOString()
      }];
    }

    return [];
  } catch (err) {
    console.error(`[PRESSURE] GPT-4 error: ${err.message}`);
    return heuristicAnalysis(chunk, context);
  }
}

/**
 * Fallback heuristic analysis when GPT-4 is unavailable.
 * Checks for common shallow answer patterns.
 */
function heuristicAnalysis(chunk, context = {}) {
  const alerts = [];
  const chunkLower = chunk.toLowerCase();
  const wordCount = chunk.split(/\s+/).length;

  // Very short answer to what seems like a technical question
  if (wordCount < 15 && context.currentTopic) {
    alerts.push({
      type: 'pressure_point',
      message: `Probe deeper on ${context.currentTopic}`,
      evidence: `Answer was only ${wordCount} words`,
      severity: 'medium',
      timestamp: new Date().toISOString()
    });
  }

  // Deflects ownership ("the team did it" instead of "I did")
  if (chunkLower.includes('the team') || chunkLower.includes('we did')) {
    if (!chunkLower.includes('i ') && !chunkLower.includes('my ')) {
      alerts.push({
        type: 'pressure_point',
        message: 'Ask about their specific role and contribution',
        evidence: 'Candidate deflected to team without stating personal role',
        severity: 'medium',
        timestamp: new Date().toISOString()
      });
    }
  }

  // Vague qualifiers without specifics
  const vagueCount = SHALLOW_SIGNALS.filter(s => chunkLower.includes(s)).length;
  if (vagueCount >= 2) {
    alerts.push({
      type: 'pressure_point',
      message: 'Ask for a specific example or metric',
      evidence: `Multiple vague qualifiers detected (${vagueCount})`,
      severity: 'low',
      timestamp: new Date().toISOString()
    });
  }

  return alerts;
}
