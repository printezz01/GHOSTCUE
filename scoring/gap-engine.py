"""
scoring/gap-engine.py -- GhostCue Gap Engine

Compares resume claims against full session transcript evidence.
For each resume claim, finds transcript moments that confirm, contradict,
or leave it vague. Produces a per-claim evidence map used by the
integrity score calculator.

Usage:
    python scoring/gap-engine.py <candidate_id>
"""

import os
import sys
import json
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from openai import OpenAI
except ImportError:
    print("[GAP] ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"


def load_candidate(candidate_id):
    """Load candidate data from Cognitive RAM."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    if not yaml_path.exists():
        print(f"[GAP] ERROR: Candidate not found: {candidate_id}")
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_full_transcript(candidate):
    """Extract all transcript text from all sessions."""
    sessions = candidate.get("sessions", [])
    all_text = []
    for session in sessions:
        chunks = session.get("transcript_chunks", [])
        for chunk in chunks:
            text = chunk.get("text", chunk) if isinstance(chunk, dict) else str(chunk)
            speaker = chunk.get("speaker", "unknown") if isinstance(chunk, dict) else "unknown"
            if text.strip():
                all_text.append(f"[{speaker}] {text}")
    return "\n".join(all_text)


def analyze_with_groq(resume_claims, transcript):
    """
    Use Groq (groq.com) with llama-3.3-70b-versatile to map resume claims to transcript evidence.
    Returns a list of claim assessments.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    # Groq keys start with gsk_ — reject empty or placeholder values
    if not api_key or api_key.startswith("your_") or api_key == "":
        print("[GAP] WARNING: No valid GROQ_API_KEY - using heuristic analysis")
        return heuristic_analysis(resume_claims, transcript)

    # Build claims summary
    claims_text = []
    for skill in resume_claims.get("skills", []):
        claims_text.append(f"- Skill: {skill}")
    claims_text.append(f"- Years of experience: {resume_claims.get('years_experience', 0)}")
    for proj in resume_claims.get("projects", []):
        name = proj.get("name", proj) if isinstance(proj, dict) else str(proj)
        claims_text.append(f"- Project: {name}")
    for cert in resume_claims.get("certifications", []):
        claims_text.append(f"- Certification: {cert}")

    prompt = f"""Analyze this interview transcript against the candidate's resume claims.
For each claim, determine if the transcript CONFIRMS, CONTRADICTS, or leaves it VAGUE.

RESUME CLAIMS:
{chr(10).join(claims_text)}

TRANSCRIPT:
{transcript[:4000]}

Return JSON array:
[
  {{
    "claim": "the resume claim",
    "verdict": "confirmed" | "vague" | "contradicted",
    "evidence": "brief quote or summary from transcript",
    "confidence": 0.0 to 1.0
  }}
]
Return ONLY valid JSON, no markdown."""

    try:
        # Groq is OpenAI-compatible — same SDK, different base_url and key
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an evidence-based interview analyst. Return only JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2000
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as e:
        print(f"[GAP] Groq error: {e}")
        return heuristic_analysis(resume_claims, transcript)


def heuristic_analysis(resume_claims, transcript):
    """
    Fallback gap analysis using keyword matching when Groq is unavailable.
    Checks if resume skills/projects are mentioned in the transcript.
    """
    transcript_lower = transcript.lower()
    results = []

    # Check each skill
    for skill in resume_claims.get("skills", []):
        skill_lower = skill.lower()
        if skill_lower in transcript_lower:
            # Count how many times mentioned
            count = transcript_lower.count(skill_lower)
            if count >= 3:
                verdict = "confirmed"
                confidence = 0.8
            elif count >= 1:
                verdict = "vague"
                confidence = 0.5
            else:
                verdict = "vague"
                confidence = 0.3
        else:
            verdict = "vague"
            confidence = 0.2

        results.append({
            "claim": f"Skill: {skill}",
            "verdict": verdict,
            "evidence": f"Mentioned {count} time(s) in transcript" if skill_lower in transcript_lower else "Not mentioned in transcript",
            "confidence": confidence
        })

    # Check projects
    for proj in resume_claims.get("projects", []):
        name = proj.get("name", proj) if isinstance(proj, dict) else str(proj)
        name_lower = name.lower()
        if name_lower in transcript_lower:
            results.append({
                "claim": f"Project: {name}",
                "verdict": "confirmed",
                "evidence": "Project discussed in interview",
                "confidence": 0.7
            })
        else:
            results.append({
                "claim": f"Project: {name}",
                "verdict": "vague",
                "evidence": "Project not discussed",
                "confidence": 0.3
            })

    # Check experience years
    years = resume_claims.get("years_experience", 0)
    if years > 0:
        import re
        year_mentions = re.findall(r'(\d+)\s*years?', transcript_lower)
        if year_mentions:
            spoken = [int(y) for y in year_mentions]
            if any(abs(y - years) <= 1 for y in spoken):
                results.append({
                    "claim": f"Experience: {years} years",
                    "verdict": "confirmed",
                    "evidence": f"Candidate mentioned {spoken} years",
                    "confidence": 0.8
                })
            else:
                results.append({
                    "claim": f"Experience: {years} years",
                    "verdict": "contradicted",
                    "evidence": f"Resume says {years}yr but candidate said {spoken}yr",
                    "confidence": 0.7
                })
        else:
            results.append({
                "claim": f"Experience: {years} years",
                "verdict": "vague",
                "evidence": "Experience years not discussed",
                "confidence": 0.3
            })

    return results


def run_gap_analysis(candidate_id):
    """Full pipeline: load candidate -> extract transcript -> analyze gaps."""
    candidate = load_candidate(candidate_id)
    if not candidate:
        return None

    print(f"\n[GAP] Analyzing: {candidate.get('name', 'Unknown')}")
    print(f"[GAP] {'-' * 50}")

    transcript = extract_full_transcript(candidate)
    if not transcript:
        print("[GAP] WARNING: No transcript data found - using resume claims only")
        transcript = "(no transcript available)"

    resume_claims = candidate.get("resume_claims", {})
    results = analyze_with_groq(resume_claims, transcript)

    # Count verdicts
    confirmed = sum(1 for r in results if r["verdict"] == "confirmed")
    vague = sum(1 for r in results if r["verdict"] == "vague")
    contradicted = sum(1 for r in results if r["verdict"] == "contradicted")

    print(f"[GAP] Results: {confirmed} confirmed, {vague} vague, {contradicted} contradicted")

    # Save results back to candidate
    sessions = candidate.get("sessions", [])
    if sessions:
        sessions[-1]["gap_analysis"] = results

    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(candidate, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) < 2:
        print("[GAP] Usage: python scoring/gap-engine.py <candidate_id>")
        for f in MEMORY_DIR.glob("*.yaml"):
            if not f.name.startswith("_"):
                print(f"  -> {f.stem}")
        sys.exit(1)

    run_gap_analysis(sys.argv[1])
