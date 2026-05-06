"""
scoring/integrity-score.py -- GhostCue Candidate Integrity Score

Calculates a 0-100 integrity score using a weighted formula:
  - Technical Depth (30%) -- confident answers vs vague
  - Resume Honesty (30%) -- contradiction count
  - Communication (20%) -- clarity heuristic (filler words, sentence length)
  - Overall Fit (20%) -- coverage_checklist completion percentage

Usage:
    python scoring/integrity-score.py <candidate_id>
"""

import sys
import yaml
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"

# Weights per the build prompt specification
WEIGHTS = {
    "technical_depth": 0.30,
    "resume_honesty": 0.30,
    "communication": 0.20,
    "overall_fit": 0.20
}

# Filler words that indicate low communication clarity
FILLER_WORDS = [
    "um", "uh", "like", "you know", "sort of", "kind of",
    "i mean", "basically", "actually", "literally", "honestly",
    "right", "so yeah", "i guess", "i think", "maybe"
]


def load_candidate(candidate_id):
    """Load candidate data from Cognitive RAM."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    if not yaml_path.exists():
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def calculate_technical_depth(candidate):
    """
    Score 0-100 based on gap analysis verdicts.
    More confirmed claims = higher score.
    """
    sessions = candidate.get("sessions", [])
    if not sessions:
        return 50  # neutral if no sessions

    latest = sessions[-1]
    gap_results = latest.get("gap_analysis", [])

    if not gap_results:
        # Fall back to pressure points -- fewer = better
        pressure_points = latest.get("pressure_points_fired", [])
        chunks = latest.get("transcript_chunks", [])
        if not chunks:
            return 50
        # Score inversely proportional to pressure points per chunk
        ratio = len(pressure_points) / max(len(chunks), 1)
        return max(10, min(100, int(100 - (ratio * 200))))

    confirmed = sum(1 for r in gap_results if r.get("verdict") == "confirmed")
    vague = sum(1 for r in gap_results if r.get("verdict") == "vague")
    contradicted = sum(1 for r in gap_results if r.get("verdict") == "contradicted")
    total = confirmed + vague + contradicted

    if total == 0:
        return 50

    # Confirmed = full points, vague = half, contradicted = zero
    score = ((confirmed * 1.0) + (vague * 0.4) + (contradicted * 0.0)) / total
    return max(0, min(100, int(score * 100)))


def calculate_resume_honesty(candidate):
    """
    Score 0-100 based on contradiction count.
    Zero contradictions = 100. Each contradiction reduces score.
    """
    sessions = candidate.get("sessions", [])
    if not sessions:
        return 80  # assume honest if no data

    latest = sessions[-1]
    contradictions = latest.get("flagged_contradictions", [])
    gap_results = latest.get("gap_analysis", [])

    # Count contradictions from both sources
    contradiction_count = len(contradictions)
    gap_contradictions = sum(1 for r in gap_results if r.get("verdict") == "contradicted")
    total_contradictions = contradiction_count + gap_contradictions

    # Each contradiction drops 15 points from 100
    score = 100 - (total_contradictions * 15)
    return max(0, min(100, score))


def calculate_communication(candidate):
    """
    Score 0-100 based on communication clarity.
    Checks: filler word frequency, average sentence length, response length.
    """
    sessions = candidate.get("sessions", [])
    if not sessions:
        return 60

    latest = sessions[-1]
    chunks = latest.get("transcript_chunks", [])

    # Collect candidate-only text
    candidate_text = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            speaker = chunk.get("speaker", "").lower()
            text = chunk.get("text", "")
            if speaker in ("candidate", "unknown") and text.strip():
                candidate_text.append(text)
        elif isinstance(chunk, str) and chunk.strip():
            candidate_text.append(chunk)

    if not candidate_text:
        return 60

    full_text = " ".join(candidate_text)
    full_lower = full_text.lower()
    word_count = len(full_text.split())

    if word_count == 0:
        return 30

    # Filler word ratio (lower is better)
    filler_count = sum(full_lower.count(f) for f in FILLER_WORDS)
    filler_ratio = filler_count / max(word_count, 1)
    filler_score = max(0, 100 - int(filler_ratio * 500))

    # Average sentence length (10-25 words is ideal)
    sentences = re.split(r'[.!?]+', full_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    avg_length = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)

    if 10 <= avg_length <= 25:
        length_score = 100
    elif avg_length < 10:
        length_score = max(40, int(avg_length * 10))
    else:
        length_score = max(40, int(100 - (avg_length - 25) * 3))

    # Average response length (more detailed = better, to a point)
    avg_response = word_count / max(len(candidate_text), 1)
    if avg_response >= 20:
        detail_score = 100
    elif avg_response >= 10:
        detail_score = 70
    else:
        detail_score = 40

    # Combined: 40% filler, 30% sentence length, 30% detail
    score = int(filler_score * 0.4 + length_score * 0.3 + detail_score * 0.3)
    return max(0, min(100, score))


def calculate_overall_fit(candidate):
    """
    Score 0-100 based on coverage checklist completion.
    Each covered topic = 25% of score.
    """
    sessions = candidate.get("sessions", [])
    if not sessions:
        return 50

    latest = sessions[-1]
    checklist = latest.get("coverage_checklist", {})

    if not checklist:
        return 50

    covered = sum(1 for v in checklist.values() if v)
    total = len(checklist) if checklist else 4

    return int((covered / total) * 100)


def calculate_integrity_score(candidate_id):
    """
    Master scoring function. Calculates all four subscores and
    the weighted final integrity score.

    Returns dict with all scores.
    """
    candidate = load_candidate(candidate_id)
    if not candidate:
        print(f"[SCORE] ERROR: Candidate {candidate_id} not found")
        return None

    print(f"\n[SCORE] Scoring: {candidate.get('name', 'Unknown')}")
    print(f"[SCORE] {'-' * 50}")

    # Calculate subscores
    tech = calculate_technical_depth(candidate)
    honesty = calculate_resume_honesty(candidate)
    comm = calculate_communication(candidate)
    fit = calculate_overall_fit(candidate)

    # Weighted final score
    final = int(
        tech * WEIGHTS["technical_depth"] +
        honesty * WEIGHTS["resume_honesty"] +
        comm * WEIGHTS["communication"] +
        fit * WEIGHTS["overall_fit"]
    )

    scores = {
        "integrity_score": final,
        "technical_depth_score": tech,
        "resume_honesty_score": honesty,
        "communication_score": comm,
        "overall_fit_score": fit
    }

    print(f"  Technical Depth (30%):  {tech}/100")
    print(f"  Resume Honesty (30%):  {honesty}/100")
    print(f"  Communication  (20%):  {comm}/100")
    print(f"  Overall Fit    (20%):  {fit}/100")
    print(f"  {'=' * 35}")
    print(f"  INTEGRITY SCORE:       {final}/100")

    # Save scores to latest session in RAM
    sessions = candidate.get("sessions", [])
    if sessions:
        sessions[-1]["scoring"] = scores

    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(candidate, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\n[SCORE] Scores saved to Cognitive RAM")
    return scores


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) < 2:
        print("[SCORE] Usage: python scoring/integrity-score.py <candidate_id>")
        for f in MEMORY_DIR.glob("*.yaml"):
            if not f.name.startswith("_"):
                print(f"  -> {f.stem}")
        sys.exit(1)

    calculate_integrity_score(sys.argv[1])
