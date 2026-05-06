"""
scoring/radar-chart.py -- GhostCue 4-Axis Radar Chart

Generates a matplotlib polar plot with 4 axes:
  - Technical Depth
  - Resume Honesty
  - Communication
  - Overall Fit

Saves as PNG for embedding in the PDF report.

Usage:
    python scoring/radar-chart.py <candidate_id>
    # or import and call: generate_radar_chart(candidate_id)
"""

import sys
import yaml
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend for server/headless
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
except ImportError:
    print("[RADAR] ERROR: matplotlib not installed. Run: pip install matplotlib")
    sys.exit(1)

MEMORY_DIR = PROJECT_ROOT / "memory" / "candidates"
OUTPUT_DIR = PROJECT_ROOT / "output" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Chart styling
CHART_COLORS = {
    'fill': '#6C5CE7',      # purple fill
    'line': '#A29BFE',       # lighter purple line
    'bg': '#2D3436',         # dark background
    'text': '#DFE6E9',       # light text
    'grid': '#636E72',       # subtle grid lines
    'accent': '#00CEC9'      # teal accent
}


def load_candidate(candidate_id):
    """Load candidate data from Cognitive RAM."""
    yaml_path = MEMORY_DIR / f"{candidate_id}.yaml"
    if not yaml_path.exists():
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_radar_chart(candidate_id, scores=None):
    """
    Generate a 4-axis radar chart for a candidate.
    
    Args:
        candidate_id: UUID of the candidate
        scores: optional dict with scores (auto-loaded from RAM if None)
    
    Returns:
        Path to saved PNG file, or None on error
    """
    candidate = load_candidate(candidate_id)
    if not candidate:
        print(f"[RADAR] ERROR: Candidate {candidate_id} not found")
        return None

    # Get scores from latest session if not provided
    if scores is None:
        sessions = candidate.get("sessions", [])
        if sessions:
            scores = sessions[-1].get("scoring", {})

    # Default scores if none available
    if not scores:
        scores = {
            "technical_depth_score": 50,
            "resume_honesty_score": 50,
            "communication_score": 50,
            "overall_fit_score": 50,
            "integrity_score": 50
        }

    # Chart data
    categories = ['Technical\nDepth', 'Resume\nHonesty', 'Communication', 'Overall\nFit']
    values = [
        scores.get("technical_depth_score", 50),
        scores.get("resume_honesty_score", 50),
        scores.get("communication_score", 50),
        scores.get("overall_fit_score", 50)
    ]
    integrity = scores.get("integrity_score", 50)

    # Close the polygon by repeating the first value
    values_closed = values + [values[0]]
    num_vars = len(categories)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    angles_closed = angles + [angles[0]]

    # Create figure with dark theme
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(CHART_COLORS['bg'])
    ax.set_facecolor(CHART_COLORS['bg'])

    # Draw grid circles
    for i in range(20, 101, 20):
        circle = plt.Circle((0, 0), i, transform=ax.transData, fill=False,
                           color=CHART_COLORS['grid'], linewidth=0.5, alpha=0.3)
        ax.add_patch(circle)

    # Plot the radar area
    ax.plot(angles_closed, values_closed, 'o-', linewidth=2.5,
            color=CHART_COLORS['line'], markersize=8, zorder=5)
    ax.fill(angles_closed, values_closed, alpha=0.25, color=CHART_COLORS['fill'])

    # Add value labels on each point
    for angle, value, cat in zip(angles, values, categories):
        ax.annotate(f'{value}',
                   xy=(angle, value),
                   xytext=(0, 15),
                   textcoords='offset points',
                   ha='center', va='bottom',
                   fontsize=14, fontweight='bold',
                   color=CHART_COLORS['accent'])

    # Configure axes
    ax.set_xticks(angles)
    ax.set_xticklabels(categories, fontsize=12, color=CHART_COLORS['text'],
                       fontweight='bold')
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(['20', '40', '60', '80', '100'],
                       fontsize=8, color=CHART_COLORS['grid'])
    ax.spines['polar'].set_color(CHART_COLORS['grid'])
    ax.tick_params(colors=CHART_COLORS['grid'])
    ax.grid(color=CHART_COLORS['grid'], alpha=0.3)

    # Title with integrity score
    candidate_name = candidate.get("name", "Unknown")
    ax.set_title(f'{candidate_name}\nIntegrity Score: {integrity}/100',
                fontsize=16, fontweight='bold', color=CHART_COLORS['text'],
                pad=30)

    # Save
    output_path = OUTPUT_DIR / f"{candidate_id}_radar.png"
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight',
                facecolor=CHART_COLORS['bg'], edgecolor='none')
    plt.close()

    print(f"[RADAR] Chart saved: {output_path.name}")
    return output_path


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) < 2:
        print("[RADAR] Usage: python scoring/radar-chart.py <candidate_id>")
        for f in MEMORY_DIR.glob("*.yaml"):
            if not f.name.startswith("_"):
                print(f"  -> {f.stem}")
        sys.exit(1)

    path = generate_radar_chart(sys.argv[1])
    if path:
        print(f"[RADAR] OK - Chart at {path}")
