"""
resume/question-gen.py — GhostCue Interview Question Generator

Takes parsed resume data from Cognitive RAM and generates custom
interview questions using Groq (groq.com) with llama-3.3-70b-versatile.
Questions are weighted by experience level and tailored to the candidate's
specific tech stack and projects.

Usage:
    python resume/question-gen.py <candidate_id>

Called automatically after parser.py by HEARTBEAT Trigger 1.
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
    print("[QGEN] ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"

# Prompt template for question generation
QUESTION_PROMPT = """You are an expert technical interviewer. Generate custom interview questions
for a candidate based on their resume data below.

Generate questions in these categories:
1. Technical Depth (3-4 questions): Deep-dive into their claimed skills and tech stack.
   Test whether they truly understand the technologies or just listed them.
2. System Design (2-3 questions): Based on their projects, ask them to design or scale
   something similar. Gauge architectural thinking.
3. Behavioral (2-3 questions): STAR-format questions tied to their specific experience.
   Focus on leadership, conflict, failure, and growth.
4. Role-Specific (1-2 questions): Questions that directly probe their most impressive
   resume claims. These are the "prove it" questions.

Rules:
- Questions should be impossible to answer with generic textbook knowledge
- Each question should reference something specific from THEIR resume
- Include one "trap" question per category that tests if they truly did the work
- Difficulty should match their experience level ({years} years)
- Return ONLY valid JSON, no markdown

Return format:
{{
  "technical": ["question1", "question2", ...],
  "system_design": ["question1", ...],
  "behavioral": ["question1", ...],
  "role_specific": ["question1", ...]
}}

Candidate Resume Data:
Name: {name}
Years of Experience: {years}
Skills: {skills}
Projects: {projects}
Education: {education}
Certifications: {certifications}
Summary: {summary}
"""


def load_candidate(candidate_id):
    """Load candidate data from Cognitive RAM."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    
    if not yaml_path.exists():
        print(f"[QGEN] ERROR: Candidate not found: {candidate_id}")
        return None
    
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_questions_groq(candidate):
    """Generate custom questions using Groq (groq.com) with llama-3.3-70b-versatile."""
    api_key = os.getenv("GROQ_API_KEY", "")

    # Groq keys start with gsk_ — reject empty or placeholder values
    if not api_key or api_key.startswith("your_") or api_key == "":
        print("[QGEN] WARNING: No valid GROQ_API_KEY - using template questions")
        return generate_fallback_questions(candidate)

    claims = candidate.get("resume_claims", {})

    prompt = QUESTION_PROMPT.format(
        name=candidate.get("name", "Unknown"),
        years=claims.get("years_experience", 0),
        skills=", ".join(claims.get("skills", [])),
        projects=json.dumps(claims.get("projects", []), indent=2),
        education=json.dumps(claims.get("education", []), indent=2),
        certifications=", ".join(claims.get("certifications", [])),
        summary=claims.get("summary", "No summary available")
    )

    try:
        # Groq is OpenAI-compatible — same SDK, different base_url and key
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert interviewer. Generate probing, specific questions."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,  # some creativity for diverse questions
            max_tokens=2000
        )

        raw = response.choices[0].message.content.strip()

        # Handle markdown-wrapped JSON
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0]

        questions = json.loads(raw)

        total = sum(len(v) for v in questions.values())
        print(f"[QGEN] ✅ Generated {total} questions for {candidate.get('name', 'Unknown')}")
        return questions

    except Exception as e:
        print(f"[QGEN] ERROR calling Groq: {e}")
        return generate_fallback_questions(candidate)


def generate_fallback_questions(candidate):
    """
    Generate template-based questions when Groq is unavailable.
    Still personalized — uses candidate's actual skills and projects.
    """
    claims = candidate.get("resume_claims", {})
    skills = claims.get("skills", [])
    projects = claims.get("projects", [])
    name = candidate.get("name", "the candidate")
    
    # Build skill-specific technical questions
    technical = []
    for skill in skills[:4]:
        technical.append(
            f"You listed {skill} on your resume. Can you walk me through a complex "
            f"problem you solved using {skill}? What was the specific challenge and "
            f"what trade-offs did you consider?"
        )
    if not technical:
        technical = ["Tell me about the most technically challenging project you've worked on."]
    
    # Build project-specific system design questions
    system_design = []
    for proj in projects[:2]:
        proj_name = proj.get("name", "your project") if isinstance(proj, dict) else str(proj)
        system_design.append(
            f"You worked on {proj_name}. If you had to redesign it to handle 100x "
            f"the current load, what would you change first? Walk me through your approach."
        )
    if not system_design:
        system_design = [
            "Design a real-time notification system for a platform with 1M daily active users. "
            "What components would you use and why?"
        ]
    
    # Behavioral questions (always relevant)
    behavioral = [
        f"Tell me about a time at a previous role where you disagreed with a technical "
        f"decision made by your team. What did you do?",
        f"Describe a project that failed or didn't meet expectations. What was your role "
        f"and what did you learn?",
        f"Give me an example of when you had to learn a new technology under a tight deadline. "
        f"How did you approach it?"
    ]
    
    # Role-specific probing questions
    role_specific = []
    if claims.get("years_experience", 0) > 5:
        role_specific.append(
            "You have significant experience. Tell me about a time you mentored a junior "
            "developer. What was the outcome?"
        )
    if claims.get("certifications"):
        cert = claims["certifications"][0]
        role_specific.append(
            f"You hold a {cert} certification. How has it changed the way you approach "
            f"problems in practice, beyond passing the exam?"
        )
    if not role_specific:
        role_specific = [
            "What's the most impactful contribution you've made to a team or product? "
            "How do you measure that impact?"
        ]
    
    print(f"[QGEN] ✅ Generated {len(technical) + len(system_design) + len(behavioral) + len(role_specific)} "
          f"fallback questions for {name}")
    
    return {
        "technical": technical,
        "system_design": system_design,
        "behavioral": behavioral,
        "role_specific": role_specific
    }


def save_questions(candidate_id, questions):
    """Update the candidate's YAML with generated questions."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    
    with open(yaml_path, "r", encoding="utf-8") as f:
        candidate = yaml.safe_load(f)
    
    candidate["generated_questions"] = questions
    
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(candidate, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print(f"[QGEN] Questions saved to {yaml_path.name}")


def generate_for_candidate(candidate_id):
    """Full pipeline: load candidate → generate questions → save to RAM."""
    candidate = load_candidate(candidate_id)
    if not candidate:
        return None

    print(f"\n[QGEN] Generating questions for: {candidate.get('name', 'Unknown')}")
    print(f"[QGEN] {'─' * 50}")

    questions = generate_questions_groq(candidate)
    save_questions(candidate_id, questions)

    return questions


def display_questions(questions):
    """Pretty-print questions to terminal."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        
        console = Console()
        
        for category, q_list in questions.items():
            title = category.replace("_", " ").title()
            console.print(f"\n[bold cyan]📋 {title}[/bold cyan]")
            for i, q in enumerate(q_list, 1):
                console.print(f"  [yellow]{i}.[/yellow] {q}")
    except ImportError:
        # Fallback if rich is not available
        for category, q_list in questions.items():
            title = category.replace("_", " ").title()
            print(f"\n📋 {title}")
            for i, q in enumerate(q_list, 1):
                print(f"  {i}. {q}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    
    if len(sys.argv) < 2:
        print("[QGEN] Usage: python resume/question-gen.py <candidate_id>")
        print("[QGEN] Available candidates:")
        for f in MEMORY_DIR.glob("*.yaml"):
            if not f.name.startswith("_"):
                print(f"  → {f.stem}")
        sys.exit(1)
    
    candidate_id = sys.argv[1]
    questions = generate_for_candidate(candidate_id)
    
    if questions:
        display_questions(questions)
