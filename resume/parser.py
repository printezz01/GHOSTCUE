"""
resume/parser.py — GhostCue Resume Parser

Extracts structured data from candidate PDF resumes using PyPDF2 for text
extraction and GPT-4 for intelligent parsing. Writes parsed data as YAML
to /memory/candidates/ (Cognitive RAM).

Usage:
    python resume/parser.py                     # parse all new PDFs in /input/resumes/
    python resume/parser.py path/to/resume.pdf  # parse a specific PDF

This script is called by HEARTBEAT Trigger 1 (resume drop) and can also
be invoked directly from the CLI or messaging bots.
"""

import os
import sys
import json
import uuid
import yaml
from datetime import datetime
from pathlib import Path

# Add project root to path so imports work from any directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from PyPDF2 import PdfReader
except ImportError:
    print("[PARSER] ERROR: PyPDF2 not installed. Run: pip install pypdf2")
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("[PARSER] ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

# Directories
INPUT_DIR = PROJECT_ROOT / "input" / "resumes"
MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# GPT-4 prompt for structured resume extraction
EXTRACTION_PROMPT = """You are a resume parsing engine. Extract structured data from the following resume text.

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{
  "name": "Full Name",
  "email": "email@example.com or empty string",
  "phone": "phone number or empty string",
  "skills": ["skill1", "skill2"],
  "years_experience": 0,
  "education": [
    {"degree": "B.Tech CS", "institution": "University Name", "year": 2020}
  ],
  "projects": [
    {"name": "Project Name", "tech_stack": ["Tech1", "Tech2"], "role": "Role Description"}
  ],
  "certifications": ["Cert1", "Cert2"],
  "summary": "One paragraph professional summary based on the resume content"
}

Rules:
- Extract ALL skills mentioned anywhere in the resume
- If years of experience is not explicit, estimate from work history dates
- Include ALL projects, even academic ones
- If a field cannot be determined, use empty string or empty array
- Never fabricate information - only extract what's actually in the resume

Resume text:
"""


def extract_text_from_pdf(pdf_path):
    """
    Extract raw text from a PDF file using PyPDF2.
    Returns the full text content as a single string.
    Falls back gracefully if pages are image-based (returns what it can).
    """
    try:
        reader = PdfReader(str(pdf_path))
        text_parts = []

        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text.strip())

        full_text = "\n\n".join(text_parts)

        if not full_text.strip():
            print(f"[PARSER] WARNING: No text extracted from {pdf_path.name} - may be image-based PDF")
            return ""

        print(f"[PARSER] Extracted {len(full_text)} chars from {pdf_path.name} ({len(reader.pages)} pages)")
        return full_text

    except Exception as e:
        print(f"[PARSER] ERROR reading PDF {pdf_path.name}: {e}")
        return ""


def parse_with_gpt4(resume_text):
    """
    Send extracted resume text to GPT-4 for structured parsing.
    Returns a dict matching the JSON schema defined in EXTRACTION_PROMPT.
    Falls back to a minimal scaffold if GPT-4 is unavailable.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key or api_key.startswith("sk-your"):
        print("[PARSER] WARNING: No valid OPENAI_API_KEY - using fallback extraction")
        return fallback_extraction(resume_text)

    try:
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise resume parsing engine. Return only valid JSON."
                },
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT + resume_text
                }
            ],
            temperature=0.1,  # low temperature for consistent extraction
            max_tokens=2000
        )

        raw_response = response.choices[0].message.content.strip()

        # Handle markdown-wrapped JSON (GPT sometimes wraps in ```json blocks)
        if raw_response.startswith("```"):
            raw_response = raw_response.split("\n", 1)[1]  # remove first line
            raw_response = raw_response.rsplit("```", 1)[0]  # remove last ```

        parsed = json.loads(raw_response)
        print(f"[PARSER] GPT-4 extracted: {parsed.get('name', 'Unknown')} | "
              f"{len(parsed.get('skills', []))} skills | "
              f"{len(parsed.get('projects', []))} projects")
        return parsed

    except json.JSONDecodeError as e:
        print(f"[PARSER] ERROR: GPT-4 returned invalid JSON: {e}")
        return fallback_extraction(resume_text)
    except Exception as e:
        print(f"[PARSER] ERROR calling GPT-4: {e}")
        return fallback_extraction(resume_text)


def fallback_extraction(text):
    """
    Basic regex/heuristic extraction when GPT-4 is unavailable.
    Extracts what it can from raw text - better than nothing.
    """
    import re

    # Try to find name (usually first non-empty line)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    name = lines[0] if lines else "Unknown Candidate"

    # Try to find email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
    email = email_match.group(0) if email_match else ""

    # Try to find phone
    phone_match = re.search(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}', text)
    phone = phone_match.group(0) if phone_match else ""

    # Extract potential skills (common tech keywords)
    known_skills = [
        "python", "javascript", "java", "c++", "c#", "go", "rust", "ruby",
        "react", "angular", "vue", "node.js", "express", "django", "flask",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "postgresql", "mongodb", "mysql", "redis", "elasticsearch",
        "git", "linux", "sql", "html", "css", "typescript", "graphql",
        "machine learning", "deep learning", "nlp", "computer vision"
    ]
    text_lower = text.lower()
    found_skills = [s.title() for s in known_skills if s in text_lower]

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "skills": found_skills,
        "years_experience": 0,
        "education": [],
        "projects": [],
        "certifications": [],
        "summary": f"Resume parsed in fallback mode. {len(found_skills)} skills detected."
    }


def write_candidate_yaml(parsed_data, source_pdf):
    """
    Write parsed resume data to Cognitive RAM as a YAML file.
    Returns the candidate_id (UUID).
    """
    candidate_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    candidate = {
        "candidate_id": candidate_id,
        "name": parsed_data.get("name", "Unknown"),
        "email": parsed_data.get("email", ""),
        "phone": parsed_data.get("phone", ""),
        "created_at": now,
        "source_resume": str(source_pdf.name),
        "resume_claims": {
            "skills": parsed_data.get("skills", []),
            "years_experience": parsed_data.get("years_experience", 0),
            "education": parsed_data.get("education", []),
            "projects": parsed_data.get("projects", []),
            "certifications": parsed_data.get("certifications", []),
            "summary": parsed_data.get("summary", "")
        },
        "generated_questions": {
            "technical": [],
            "system_design": [],
            "behavioral": [],
            "role_specific": []
        },
        "sessions": [],
        "cross_session_summary": "",
        "cross_session_flags": []
    }

    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(candidate, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[PARSER] OK - Candidate saved: {yaml_path.name}")
    print(f"         Name: {candidate['name']}")
    print(f"         ID:   {candidate_id}")
    return candidate_id


def parse_resume(pdf_path):
    """
    Full pipeline: PDF -> text -> GPT-4 -> YAML.
    Returns (candidate_id, parsed_data) tuple.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        print(f"[PARSER] ERROR: File not found: {pdf_path}")
        return None, None

    if not pdf_path.suffix.lower() == ".pdf":
        print(f"[PARSER] ERROR: Not a PDF: {pdf_path}")
        return None, None

    print(f"\n[PARSER] Processing: {pdf_path.name}")
    print(f"[PARSER] {'-' * 50}")

    # Step 1: Extract text
    text = extract_text_from_pdf(pdf_path)
    if not text:
        print("[PARSER] Skipping - no text could be extracted")
        return None, None

    # Step 2: Parse with GPT-4 (or fallback)
    parsed = parse_with_gpt4(text)

    # Step 3: Write to Cognitive RAM
    candidate_id = write_candidate_yaml(parsed, pdf_path)

    return candidate_id, parsed


def parse_all_new():
    """
    Scan /input/resumes/ for PDFs that haven't been parsed yet.
    A PDF is "new" if no YAML in /memory/candidates/ references it.
    """
    if not INPUT_DIR.exists():
        print(f"[PARSER] Input directory not found: {INPUT_DIR}")
        return []

    # Find already-parsed resume filenames
    parsed_resumes = set()
    for yaml_file in MEMORY_DIR.glob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "source_resume" in data:
                    parsed_resumes.add(data["source_resume"])
        except Exception:
            continue

    # Parse new PDFs
    results = []
    for pdf_file in INPUT_DIR.glob("*.pdf"):
        if pdf_file.name in parsed_resumes:
            print(f"[PARSER] Skipping (already parsed): {pdf_file.name}")
            continue
        candidate_id, parsed = parse_resume(pdf_file)
        if candidate_id:
            results.append((candidate_id, parsed))

    if not results:
        print("[PARSER] No new resumes to parse")

    return results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) > 1:
        # Parse a specific PDF
        parse_resume(sys.argv[1])
    else:
        # Parse all new PDFs in /input/resumes/
        parse_all_new()
