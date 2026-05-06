"""
scoring/pdf-report.py -- GhostCue PDF Report Generator

Compiles a structured PDF report with:
  - Candidate name + session metadata
  - Integrity Score (big, prominent)
  - 4-axis radar chart image
  - Red flags and contradictions with timestamps
  - Coverage checklist results
  - Gap analysis details
  - Full transcript appendix

Uses reportlab for PDF generation.

Usage:
    python scoring/pdf-report.py <candidate_id>
"""

import sys
import yaml
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm, inch
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image, PageBreak, HRFlowable
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
except ImportError:
    print("[REPORT] ERROR: reportlab not installed. Run: pip install reportlab")
    sys.exit(1)

MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"
OUTPUT_DIR = PROJECT_ROOT / "output" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Color scheme
COLORS = {
    'primary': HexColor('#6C5CE7'),
    'accent': HexColor('#00CEC9'),
    'danger': HexColor('#FF7675'),
    'warning': HexColor('#FDCB6E'),
    'success': HexColor('#00B894'),
    'dark': HexColor('#2D3436'),
    'text': HexColor('#2D3436'),
    'light_text': HexColor('#636E72'),
    'bg': HexColor('#DFE6E9'),
    'white': HexColor('#FFFFFF')
}


def load_candidate(candidate_id):
    """Load candidate data from Cognitive RAM."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    if not yaml_path.exists():
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_score_color(score):
    """Return color based on score value."""
    if score >= 80:
        return COLORS['success']
    elif score >= 60:
        return COLORS['accent']
    elif score >= 40:
        return COLORS['warning']
    else:
        return COLORS['danger']


def build_styles():
    """Create custom paragraph styles for the report."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=COLORS['primary'],
        spaceAfter=6,
        alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=COLORS['primary'],
        spaceBefore=20,
        spaceAfter=10,
        borderWidth=0,
        borderPadding=0,
        borderColor=COLORS['primary']
    ))
    styles.add(ParagraphStyle(
        'SubHeader',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=COLORS['dark'],
        spaceBefore=10,
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        'BodyText2',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=COLORS['text'],
        spaceBefore=2,
        spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        'SmallText',
        parent=styles['BodyText'],
        fontSize=8,
        textColor=COLORS['light_text'],
        spaceBefore=1,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        'BigScore',
        parent=styles['Heading1'],
        fontSize=48,
        alignment=TA_CENTER,
        spaceBefore=10,
        spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        'CenterText',
        parent=styles['BodyText'],
        fontSize=12,
        alignment=TA_CENTER,
        textColor=COLORS['light_text']
    ))
    styles.add(ParagraphStyle(
        'RedFlag',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=COLORS['danger'],
        leftIndent=20,
        spaceBefore=2,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        'TranscriptText',
        parent=styles['BodyText'],
        fontSize=8,
        textColor=COLORS['text'],
        leftIndent=10,
        spaceBefore=1,
        spaceAfter=1,
        fontName='Courier'
    ))

    return styles


def generate_report(candidate_id):
    """
    Generate the full PDF report for a candidate.
    Orchestrates: gap analysis -> scoring -> radar chart -> PDF compilation.
    Returns path to generated PDF.
    """
    candidate = load_candidate(candidate_id)
    if not candidate:
        print(f"[REPORT] ERROR: Candidate {candidate_id} not found")
        return None

    name = candidate.get("name", "Unknown Candidate")
    print(f"\n[REPORT] Generating report for: {name}")
    print(f"[REPORT] {'-' * 50}")

    # Step 1: Run gap analysis (if not already done)
    sessions = candidate.get("sessions", [])
    latest_session = sessions[-1] if sessions else {}

    if not latest_session.get("gap_analysis"):
        print("[REPORT] Running gap analysis...")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "gap_engine", str(PROJECT_ROOT / "scoring" / "gap-engine.py"))
            gap_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gap_mod)
            gap_mod.run_gap_analysis(candidate_id)
            # Reload candidate after gap analysis
            candidate = load_candidate(candidate_id)
            sessions = candidate.get("sessions", [])
            latest_session = sessions[-1] if sessions else {}
        except Exception as e:
            print(f"[REPORT] Gap analysis error: {e}")

    # Step 2: Calculate integrity score (if not already done)
    if not latest_session.get("scoring", {}).get("integrity_score"):
        print("[REPORT] Calculating integrity score...")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "integrity_score", str(PROJECT_ROOT / "scoring" / "integrity-score.py"))
            score_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(score_mod)
            score_mod.calculate_integrity_score(candidate_id)
            candidate = load_candidate(candidate_id)
            sessions = candidate.get("sessions", [])
            latest_session = sessions[-1] if sessions else {}
        except Exception as e:
            print(f"[REPORT] Scoring error: {e}")

    scores = latest_session.get("scoring", {})

    # Step 3: Generate radar chart
    radar_path = None
    print("[REPORT] Generating radar chart...")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "radar_chart", str(PROJECT_ROOT / "scoring" / "radar-chart.py"))
        radar_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(radar_mod)
        radar_path = radar_mod.generate_radar_chart(candidate_id, scores)
    except Exception as e:
        print(f"[REPORT] Radar chart error: {e}")

    # Step 4: Build PDF
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"{candidate_id}_{timestamp}.pdf"
    pdf_path = OUTPUT_DIR / pdf_filename

    styles = build_styles()
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm
    )

    elements = []

    # ── Title Section ──
    elements.append(Paragraph("GhostCue", styles['ReportTitle']))
    elements.append(Paragraph("Candidate Interview Report", styles['CenterText']))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="80%", thickness=2, color=COLORS['primary']))
    elements.append(Spacer(1, 15))

    # ── Candidate Info ──
    info_data = [
        ["Candidate:", name],
        ["ID:", candidate_id[:8] + "..."],
        ["Report Date:", datetime.now().strftime("%B %d, %Y %H:%M")],
        ["Sessions:", str(len(sessions))],
    ]
    if latest_session.get("interviewer"):
        info_data.append(["Interviewer:", latest_session["interviewer"]])
    if latest_session.get("started_at"):
        info_data.append(["Session Date:", str(latest_session["started_at"])[:19]])

    info_table = Table(info_data, colWidths=[120, 350])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), COLORS['primary']),
        ('TEXTCOLOR', (1, 0), (1, -1), COLORS['text']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 20))

    # ── Integrity Score (BIG) ──
    elements.append(HRFlowable(width="100%", thickness=1, color=COLORS['bg']))
    integrity = scores.get("integrity_score", 50)
    score_color = get_score_color(integrity)
    elements.append(Paragraph(
        f'<font color="{score_color.hexval()}" size="48"><b>{integrity}</b></font>',
        styles['BigScore']
    ))
    elements.append(Paragraph("Candidate Integrity Score (0-100)", styles['CenterText']))
    elements.append(HRFlowable(width="100%", thickness=1, color=COLORS['bg']))
    elements.append(Spacer(1, 10))

    # ── Score Breakdown ──
    score_data = [
        ["Metric", "Score", "Weight"],
        ["Technical Depth", f"{scores.get('technical_depth_score', 50)}/100", "30%"],
        ["Resume Honesty", f"{scores.get('resume_honesty_score', 50)}/100", "30%"],
        ["Communication", f"{scores.get('communication_score', 50)}/100", "20%"],
        ["Overall Fit", f"{scores.get('overall_fit_score', 50)}/100", "20%"],
    ]
    score_table = Table(score_data, colWidths=[200, 150, 100])
    score_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['bg']),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLORS['white'], HexColor('#F5F6FA')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(score_table)
    elements.append(Spacer(1, 15))

    # ── Radar Chart ──
    if radar_path and radar_path.exists():
        elements.append(Paragraph("Performance Radar", styles['SectionHeader']))
        elements.append(Image(str(radar_path), width=350, height=350))
        elements.append(Spacer(1, 10))

    # ── Red Flags & Contradictions ──
    contradictions = latest_session.get("flagged_contradictions", [])
    pressure_points = latest_session.get("pressure_points_fired", [])

    if contradictions or pressure_points:
        elements.append(PageBreak())
        elements.append(Paragraph("Red Flags & Alerts", styles['SectionHeader']))

        if contradictions:
            elements.append(Paragraph("Contradictions Detected", styles['SubHeader']))
            for i, c in enumerate(contradictions, 1):
                msg = c.get("message", c) if isinstance(c, dict) else str(c)
                evidence = c.get("evidence", "") if isinstance(c, dict) else ""
                ts = c.get("timestamp", "") if isinstance(c, dict) else ""
                elements.append(Paragraph(
                    f'<font color="#FF7675"><b>{i}.</b></font> {msg}',
                    styles['BodyText2']
                ))
                if evidence:
                    elements.append(Paragraph(
                        f'<i>Evidence: {evidence}</i>', styles['SmallText']
                    ))

        if pressure_points:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Pressure Points Fired", styles['SubHeader']))
            for i, p in enumerate(pressure_points, 1):
                msg = p.get("message", p) if isinstance(p, dict) else str(p)
                elements.append(Paragraph(
                    f'<font color="#FDCB6E"><b>{i}.</b></font> {msg}',
                    styles['BodyText2']
                ))

    # ── Coverage Checklist ──
    checklist = latest_session.get("coverage_checklist", {})
    if checklist:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("Coverage Checklist", styles['SectionHeader']))
        check_data = [["Topic", "Status"]]
        for topic, covered in checklist.items():
            label = topic.replace("_", " ").title()
            status = "COVERED" if covered else "NOT COVERED"
            check_data.append([label, status])

        check_table = Table(check_data, colWidths=[250, 200])
        check_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['bg']),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(check_table)

    # ── Gap Analysis ──
    gap_results = latest_session.get("gap_analysis", [])
    if gap_results:
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("Resume Claim Analysis", styles['SectionHeader']))
        gap_data = [["Claim", "Verdict", "Evidence"]]
        for r in gap_results:
            verdict = r.get("verdict", "unknown")
            verdict_display = verdict.upper()
            gap_data.append([
                str(r.get("claim", ""))[:40],
                verdict_display,
                str(r.get("evidence", ""))[:50]
            ])
        gap_table = Table(gap_data, colWidths=[160, 80, 210])
        gap_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['bg']),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(gap_table)

    # ── Transcript Appendix ──
    chunks = latest_session.get("transcript_chunks", [])
    if chunks:
        elements.append(PageBreak())
        elements.append(Paragraph("Full Transcript", styles['SectionHeader']))
        elements.append(Paragraph(
            "Raw transcript captured during the interview session.",
            styles['SmallText']
        ))
        elements.append(Spacer(1, 10))

        for chunk in chunks:
            if isinstance(chunk, dict):
                speaker = chunk.get("speaker", "unknown").upper()[:4]
                text = chunk.get("text", "")
                ts = str(chunk.get("timestamp", ""))[:19]
            else:
                speaker = "????"
                text = str(chunk)
                ts = ""
            if text.strip():
                elements.append(Paragraph(
                    f'<b>[{speaker}]</b> {text}',
                    styles['TranscriptText']
                ))

    # ── Footer ──
    elements.append(Spacer(1, 30))
    elements.append(HRFlowable(width="100%", thickness=1, color=COLORS['bg']))
    elements.append(Paragraph(
        f"Generated by GhostCue | {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        "DRAFT - Pending interviewer approval",
        styles['SmallText']
    ))

    # Build PDF
    doc.build(elements)

    # Update candidate RAM with report path
    if sessions:
        sessions[-1]["report_path"] = str(pdf_path)
        sessions[-1]["report_status"] = "draft"
        yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(candidate, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[REPORT] PDF saved: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) < 2:
        print("[REPORT] Usage: python scoring/pdf-report.py <candidate_id>")
        for f in MEMORY_DIR.glob("*.yaml"):
            if not f.name.startswith("_"):
                print(f"  -> {f.stem}")
        sys.exit(1)

    path = generate_report(sys.argv[1])
    if path:
        print(f"\n[REPORT] OK - Report at {path}")
