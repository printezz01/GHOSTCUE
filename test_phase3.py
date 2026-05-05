"""
Quick test: Create a sample PDF resume and run the parser on it.
Verifies the full Cognitive RAM pipeline: PDF → text → parse → YAML.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Step 1: Create a sample PDF using fpdf2
from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
pdf.set_font("Helvetica", "B", 16)
pdf.cell(0, 10, "Arjun Mehta", new_x="LMARGIN", new_y="NEXT", align="C")

pdf.set_font("Helvetica", "", 10)
pdf.cell(0, 6, "arjun.mehta@email.com | +91-9876543210 | Bangalore, India", 
         new_x="LMARGIN", new_y="NEXT", align="C")
pdf.ln(5)

pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Professional Summary", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, 
    "Senior Software Engineer with 6 years of experience building scalable "
    "distributed systems. Expertise in Python, Go, and cloud-native architectures. "
    "Led a team of 4 engineers at Flipkart building real-time recommendation pipelines "
    "processing 50M events/day.")

pdf.ln(3)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Skills", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, 
    "Python, Go, JavaScript, React, Node.js, PostgreSQL, MongoDB, Redis, "
    "Apache Kafka, Docker, Kubernetes, AWS (EC2, S3, Lambda, ECS), "
    "Terraform, CI/CD, GraphQL, Machine Learning, TensorFlow")

pdf.ln(3)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Experience", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, 
    "Senior Software Engineer - Flipkart (2021-Present)\n"
    "- Led real-time recommendation engine processing 50M events/day\n"
    "- Reduced API latency by 40% through Redis caching layer\n"
    "- Mentored 3 junior engineers through the oncall rotation\n\n"
    "Software Engineer - Zoho (2018-2021)\n"
    "- Built microservices architecture serving 10K RPM\n"
    "- Migrated monolith to Kubernetes, reducing deployment time by 70%\n"
    "- Designed event-driven pipeline using Apache Kafka")

pdf.ln(3)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Projects", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, 
    "EventFlow - Real-time event processing framework (Go, Kafka, PostgreSQL)\n"
    "SmartCache - Intelligent caching layer with ML-based eviction (Python, Redis, TensorFlow)\n"
    "DevDash - Developer productivity dashboard (React, Node.js, GraphQL)")

pdf.ln(3)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Education", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, "B.Tech Computer Science - NIT Trichy (2018)")

pdf.ln(3)
pdf.set_font("Helvetica", "B", 12)
pdf.cell(0, 8, "Certifications", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 5, "AWS Solutions Architect Associate\nCertified Kubernetes Administrator (CKA)")

# Save to input/resumes/
output_path = PROJECT_ROOT / "input" / "resumes" / "arjun_mehta_resume.pdf"
pdf.output(str(output_path))
print(f"[TEST] OK - Sample PDF created: {output_path}")

# Step 2: Run the parser on it
print(f"\n{'='*60}")
print("Running resume parser...")
print(f"{'='*60}\n")

from resume.parser import parse_resume
candidate_id, parsed = parse_resume(output_path)

if candidate_id:
    print(f"\n{'='*60}")
    print("Checking Cognitive RAM...")
    print(f"{'='*60}\n")
    
    import yaml
    yaml_path = PROJECT_ROOT / "memory" / "candidates" / f"{candidate_id}.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    print(f"  Candidate ID:   {data['candidate_id']}")
    print(f"  Name:           {data['name']}")
    print(f"  Skills:         {data['resume_claims']['skills']}")
    print(f"  Experience:     {data['resume_claims']['years_experience']} years")
    print(f"  Projects:       {len(data['resume_claims']['projects'])} projects")
    print(f"  Certifications: {data['resume_claims']['certifications']}")
    print(f"\n[TEST] OK - Cognitive RAM verified - YAML file exists and is valid")
else:
    print("\n[TEST] FAIL - Parser failed")
