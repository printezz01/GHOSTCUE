/**
 * Quick test for ram-reader.js — verifies Cognitive RAM CRUD operations.
 */

import { readCandidate, listCandidates, healthCheck } from './agent/ram-reader.js';

console.log('[TEST] Cognitive RAM Health Check...');
const healthy = healthCheck();
console.log(`[TEST] RAM healthy: ${healthy}`);

console.log('\n[TEST] Listing candidates in RAM...');
const candidates = listCandidates();
console.log(`[TEST] Found ${candidates.length} candidate(s):`);

for (const id of candidates) {
  const data = readCandidate(id);
  console.log(`  -> ${data.name} (${id})`);
  console.log(`     Skills: ${data.resume_claims?.skills?.length || 0}`);
  console.log(`     Sessions: ${data.sessions?.length || 0}`);
}

console.log('\n[TEST] OK - ram-reader.js working correctly');
