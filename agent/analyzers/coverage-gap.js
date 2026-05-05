/**
 * agent/analyzers/coverage-gap.js — Tracks uncovered competencies
 * 
 * Pure logic analyzer — NO LLM calls. Checks which items on the
 * competency checklist have not been covered yet and fires nudges
 * based on session time elapsed.
 * 
 * Coverage categories (from _SCHEMA.yaml):
 * - technical_depth
 * - system_design
 * - behavioral
 * - culture_fit
 */

// Keywords that indicate a topic is being covered
const TOPIC_KEYWORDS = {
  technical_depth: [
    'algorithm', 'data structure', 'complexity', 'optimization', 'debug',
    'performance', 'architecture', 'implementation', 'code', 'programming',
    'database', 'api', 'framework', 'library', 'testing', 'deploy',
    'build', 'compile', 'runtime', 'memory', 'latency', 'throughput',
    'scale', 'distributed', 'microservice', 'cache', 'queue'
  ],
  system_design: [
    'design', 'architect', 'scale', 'load balancer', 'database design',
    'sharding', 'replication', 'consistency', 'availability', 'partition',
    'caching strategy', 'message queue', 'event driven', 'monolith',
    'microservice', 'api gateway', 'rate limit', 'cdn', 'failover',
    'disaster recovery', 'high availability', 'throughput', 'bottleneck'
  ],
  behavioral: [
    'team', 'conflict', 'challenge', 'mistake', 'failure', 'learned',
    'leadership', 'mentor', 'disagree', 'feedback', 'collaborate',
    'communicate', 'deadline', 'pressure', 'priority', 'decision',
    'difficult', 'growth', 'adapt', 'initiative', 'ownership'
  ],
  culture_fit: [
    'culture', 'values', 'mission', 'motivation', 'passion', 'why',
    'interest', 'career', 'goal', 'environment', 'work style',
    'remote', 'collaboration', 'diversity', 'inclusion', 'balance',
    'excited', 'inspire', 'vision', 'contribute'
  ]
};

// Time thresholds for escalation (as fraction of estimated session)
const NUDGE_THRESHOLD = 0.5;    // start nudging at 50% time elapsed
const ESCALATE_THRESHOLD = 0.8; // escalate urgency at 80% time elapsed

// Default session duration estimate (30 minutes = 360 chunks of 5 seconds)
const DEFAULT_SESSION_CHUNKS = 360;

/**
 * Analyze coverage gaps based on transcript history.
 * No LLM call — pure keyword matching and checklist tracking.
 * 
 * @param {string} chunk — latest transcript text
 * @param {object} candidate — full candidate data from Cognitive RAM
 * @param {number} chunkIndex — current chunk number in the session
 * @returns {Array} array of coverage gap alerts
 */
export function analyze(chunk, candidate, chunkIndex = 0) {
  const alerts = [];
  const currentSession = candidate?.sessions?.[candidate.sessions.length - 1];

  if (!currentSession) {
    return alerts;
  }

  const checklist = currentSession.coverage_checklist || {
    technical_depth: false,
    system_design: false,
    behavioral: false,
    culture_fit: false
  };

  const chunkLower = (chunk || '').toLowerCase();

  // Update checklist: mark topics as covered based on keyword detection
  const updatedChecklist = { ...checklist };

  for (const [topic, keywords] of Object.entries(TOPIC_KEYWORDS)) {
    if (!updatedChecklist[topic]) {
      const keywordHits = keywords.filter(k => chunkLower.includes(k)).length;
      // Require at least 2 keyword hits to mark as covered
      // (avoids false positives from single casual mentions)
      if (keywordHits >= 2) {
        updatedChecklist[topic] = true;
        console.log(`[COVERAGE] Topic covered: ${topic} (${keywordHits} keywords matched)`);
      }
    }
  }

  // Calculate time progress
  const timeProgress = chunkIndex / DEFAULT_SESSION_CHUNKS;

  // Find uncovered topics
  const uncoveredTopics = Object.entries(updatedChecklist)
    .filter(([_, covered]) => !covered)
    .map(([topic]) => topic);

  // Fire nudges based on time thresholds
  if (uncoveredTopics.length > 0 && timeProgress >= NUDGE_THRESHOLD) {
    const isEscalated = timeProgress >= ESCALATE_THRESHOLD;
    const timeLeft = Math.round((1 - timeProgress) * 30); // estimated minutes left

    for (const topic of uncoveredTopics) {
      const topicLabel = topic.replace(/_/g, ' ');

      if (isEscalated) {
        alerts.push({
          type: 'coverage_gap',
          message: `${topicLabel} not covered yet, ~${timeLeft}min left`,
          evidence: `Topic has 0 keyword matches after ${Math.round(timeProgress * 100)}% of session`,
          severity: 'high',
          timestamp: new Date().toISOString()
        });
      } else {
        alerts.push({
          type: 'coverage_gap',
          message: `Consider covering ${topicLabel} soon`,
          evidence: `Session is ${Math.round(timeProgress * 100)}% through, topic not touched`,
          severity: 'low',
          timestamp: new Date().toISOString()
        });
      }
    }
  }

  // Return the updated checklist along with alerts
  // The loop.js will write this back to Cognitive RAM
  return {
    alerts,
    updatedChecklist
  };
}

/**
 * Get a summary of coverage status for reporting.
 * 
 * @param {object} checklist — the coverage checklist object
 * @returns {object} { covered: [...], uncovered: [...], percentage: number }
 */
export function getCoverageSummary(checklist) {
  const entries = Object.entries(checklist || {});
  const covered = entries.filter(([_, v]) => v).map(([k]) => k.replace(/_/g, ' '));
  const uncovered = entries.filter(([_, v]) => !v).map(([k]) => k.replace(/_/g, ' '));
  const percentage = entries.length > 0
    ? Math.round((covered.length / entries.length) * 100)
    : 0;

  return { covered, uncovered, percentage };
}
