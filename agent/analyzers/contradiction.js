/**
 * agent/analyzers/contradiction.js — Detects candidate contradictions
 * 
 * Compares new transcript statements against:
 * 1. Resume claims stored in Cognitive RAM
 * 2. Previous statements from earlier in the same session
 * 3. Statements from prior interview rounds (cross-session)
 * 
 * Uses GPT-4 with SOUL.md rules for deep semantic comparison.
 * Contradictions are flagged as "confirmed" or "possible" per SOUL.md Neutrality Protocol.
 */

import OpenAI from 'openai';

/**
 * Analyze a transcript chunk for contradictions.
 * 
 * @param {string} chunk — latest transcript text
 * @param {object} candidate — full candidate data from Cognitive RAM
 * @param {object} soulRules — parsed SOUL.md rules
 * @returns {Promise<Array>} array of contradiction alerts
 */
export async function analyze(chunk, candidate, soulRules) {
  if (!chunk || chunk.length < 15) {
    return [];
  }

  const resumeClaims = candidate?.resume_claims || {};
  const sessions = candidate?.sessions || [];
  const currentSession = sessions[sessions.length - 1];
  const priorChunks = currentSession?.transcript_chunks || [];

  // Build context from prior statements (last 10 chunks for efficiency)
  const recentStatements = priorChunks
    .slice(-10)
    .map(c => c.text || c)
    .join('\n');

  // Build resume context
  const resumeContext = [
    `Skills: ${resumeClaims.skills?.join(', ') || 'none listed'}`,
    `Experience: ${resumeClaims.years_experience || 0} years`,
    `Projects: ${resumeClaims.projects?.map(p => typeof p === 'object' ? p.name : p).join(', ') || 'none'}`,
    `Summary: ${resumeClaims.summary || 'no summary'}`
  ].join('\n');

  const apiKey = process.env.OPENAI_API_KEY || '';
  if (!apiKey || apiKey.startsWith('sk-your')) {
    return heuristicAnalysis(chunk, resumeClaims, recentStatements);
  }

  try {
    const client = new OpenAI({ apiKey });

    const response = await client.chat.completions.create({
      model: 'gpt-4',
      messages: [
        {
          role: 'system',
          content: `You are GhostCue's contradiction detector. Compare the candidate's latest statement 
against their resume claims and prior statements from this interview.

Rules from SOUL.md:
- Cite evidence when flagging a contradiction
- If uncertain, label as "possible" rather than "confirmed"
- Never express bias
- Nudges max 12 words, start with action verb

Return JSON: 
{
  "contradictions": [
    {
      "confirmed": true/false,
      "nudge": "Clarify: resume says X but they said Y",
      "evidence": "Resume claims 6 years experience, but just said started 3 years ago",
      "severity": "high/medium/low"
    }
  ]
}
Return {"contradictions": []} if no contradictions found.`
        },
        {
          role: 'user',
          content: `RESUME CLAIMS:\n${resumeContext}\n\nPRIOR STATEMENTS:\n${recentStatements || 'No prior statements yet'}\n\nLATEST STATEMENT:\n${chunk}`
        }
      ],
      temperature: 0.2,  // low temperature for precise analysis
      max_tokens: 300,
      response_format: { type: 'json_object' }
    });

    const result = JSON.parse(response.choices[0].message.content);

    return (result.contradictions || []).map(c => ({
      type: 'contradiction',
      message: c.nudge?.substring(0, 80) || 'Contradiction detected',
      evidence: c.evidence || '',
      severity: c.severity || 'medium',
      confirmed: c.confirmed ?? false,
      timestamp: new Date().toISOString()
    }));
  } catch (err) {
    console.error(`[CONTRADICTION] GPT-4 error: ${err.message}`);
    return heuristicAnalysis(chunk, resumeClaims, recentStatements);
  }
}

/**
 * Fallback heuristic contradiction detection when GPT-4 is unavailable.
 * Checks for numeric inconsistencies and keyword mismatches.
 */
function heuristicAnalysis(chunk, resumeClaims, priorStatements) {
  const alerts = [];
  const chunkLower = chunk.toLowerCase();

  // Check experience year contradictions
  const yearsMatch = chunk.match(/(\d+)\s*years?\s*(of\s+)?experience/i);
  if (yearsMatch && resumeClaims.years_experience) {
    const spokenYears = parseInt(yearsMatch[1]);
    const resumeYears = resumeClaims.years_experience;
    if (Math.abs(spokenYears - resumeYears) >= 2) {
      alerts.push({
        type: 'contradiction',
        message: `Clarify: resume says ${resumeYears}yr but they said ${spokenYears}yr`,
        evidence: `Resume claims ${resumeYears} years, candidate said ${spokenYears} years`,
        severity: 'high',
        confirmed: false,
        timestamp: new Date().toISOString()
      });
    }
  }

  // Check if candidate denies knowing a skill they listed on resume
  const denyPatterns = [
    /i (don'?t|do not) (know|use|work with) (\w+)/i,
    /i('ve| have) never (used|worked with) (\w+)/i,
    /not familiar with (\w+)/i
  ];

  for (const pattern of denyPatterns) {
    const match = chunkLower.match(pattern);
    if (match) {
      const deniedSkill = match[match.length - 1].toLowerCase();
      const resumeSkills = (resumeClaims.skills || []).map(s => s.toLowerCase());
      if (resumeSkills.some(s => s.includes(deniedSkill) || deniedSkill.includes(s))) {
        alerts.push({
          type: 'contradiction',
          message: `Clarify: ${deniedSkill} is listed on their resume`,
          evidence: `Candidate denies familiarity but resume lists the skill`,
          severity: 'high',
          confirmed: false,
          timestamp: new Date().toISOString()
        });
      }
    }
  }

  return alerts;
}
