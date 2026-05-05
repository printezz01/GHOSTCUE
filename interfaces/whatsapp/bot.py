"""
interfaces/whatsapp/bot.py -- GhostCue WhatsApp Bot (Twilio)

WhatsApp interface for non-technical recruiters and mobile-first users.
Uses Twilio WhatsApp Business API to:
1. Receive PDF resumes via WhatsApp
2. Parse and generate custom interview questions
3. Forward live nudges during active sessions
4. Deliver final PDF report after session ends

Setup:
1. Create a Twilio account and enable WhatsApp Sandbox
2. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER in .env
3. Run: python interfaces/whatsapp/bot.py
4. Use ngrok to expose the local webhook for Twilio:
   ngrok http 5002
5. Set the ngrok URL as the Twilio WhatsApp webhook:
   https://your-ngrok-url.ngrok.io/webhook

Usage:
    python interfaces/whatsapp/bot.py                 # start webhook server
    python interfaces/whatsapp/bot.py --port 5002     # custom port
"""

import os
import sys
import json
import asyncio
import threading
import requests
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Flask for webhook handling
try:
    from flask import Flask, request as flask_request
except ImportError:
    print("[WHATSAPP] ERROR: flask not installed. Run: pip install flask")
    sys.exit(1)

# Twilio client
try:
    from twilio.rest import Client as TwilioClient
    from twilio.twiml.messaging_response import MessagingResponse
except ImportError:
    print("[WHATSAPP] ERROR: twilio not installed. Run: pip install twilio")
    sys.exit(1)

# WebSocket for agent communication
try:
    import websockets
except ImportError:
    print("[WHATSAPP] ERROR: websockets not installed. Run: pip install websockets")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Configuration ──
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
AGENT_WS_URL = "ws://localhost:3000/agent"
AGENT_API_URL = "http://localhost:3000/api"

# Track user sessions: phone_number -> {candidate_id, state}
user_sessions = {}

# Flask app
app = Flask(__name__)


def get_twilio_client():
    """Initialize Twilio client. Returns None if credentials are missing."""
    if not TWILIO_SID or not TWILIO_TOKEN or TWILIO_SID.startswith("your"):
        print("[WHATSAPP] WARNING: Twilio credentials not configured")
        print("[WHATSAPP] Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env")
        return None
    return TwilioClient(TWILIO_SID, TWILIO_TOKEN)


def send_whatsapp_message(to_number, body):
    """
    Send a WhatsApp message via Twilio.
    to_number should be in format: whatsapp:+1234567890
    """
    client = get_twilio_client()
    if not client:
        print(f"[WHATSAPP] MOCK SEND to {to_number}: {body}")
        return None

    try:
        message = client.messages.create(
            from_=TWILIO_NUMBER,
            body=body,
            to=to_number
        )
        print(f"[WHATSAPP] Sent to {to_number}: {body[:50]}...")
        return message.sid
    except Exception as e:
        print(f"[WHATSAPP] Send error: {e}")
        return None


def send_whatsapp_media(to_number, body, media_url):
    """Send a WhatsApp message with media attachment (PDF report)."""
    client = get_twilio_client()
    if not client:
        print(f"[WHATSAPP] MOCK MEDIA to {to_number}: {body} [{media_url}]")
        return None

    try:
        message = client.messages.create(
            from_=TWILIO_NUMBER,
            body=body,
            media_url=[media_url],
            to=to_number
        )
        return message.sid
    except Exception as e:
        print(f"[WHATSAPP] Media send error: {e}")
        return None


def download_media(media_url, save_path):
    """
    Download media (PDF) from Twilio's servers.
    Twilio hosts uploaded media temporarily with auth.
    """
    try:
        response = requests.get(
            media_url,
            auth=(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID else None,
            stream=True
        )
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            print(f"[WHATSAPP] Downloaded media to: {save_path}")
            return True
        else:
            print(f"[WHATSAPP] Media download failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"[WHATSAPP] Download error: {e}")
        return False


def parse_resume_for_user(phone_number, pdf_path):
    """
    Run resume parser and question generator for a WhatsApp user.
    Updates user_sessions with the candidate ID.
    """
    try:
        from resume.parser import parse_resume
        candidate_id, parsed = parse_resume(pdf_path)

        if not candidate_id:
            send_whatsapp_message(phone_number, 
                "Sorry, I could not parse that resume. Please ensure it's a valid PDF with text content.")
            return

        # Generate questions
        try:
            from resume.question_gen import generate_for_candidate
        except ImportError:
            # Handle the hyphenated filename
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "question_gen", 
                str(PROJECT_ROOT / "resume" / "question-gen.py")
            )
            question_gen = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(question_gen)
            generate_for_candidate = question_gen.generate_for_candidate

        questions = generate_for_candidate(candidate_id)

        # Track this user's session
        user_sessions[phone_number] = {
            'candidate_id': candidate_id,
            'candidate_name': parsed.get('name', 'Unknown'),
            'state': 'questions_ready'
        }

        # Build questions message
        msg_parts = [
            f"*Resume Parsed: {parsed.get('name', 'Unknown')}*",
            f"Skills: {', '.join(parsed.get('skills', [])[:8])}",
            "",
            "*Suggested Interview Questions:*",
            ""
        ]

        if questions:
            for category, q_list in questions.items():
                title = category.replace("_", " ").title()
                msg_parts.append(f"_{title}_")
                for i, q in enumerate(q_list[:3], 1):  # max 3 per category for WhatsApp
                    msg_parts.append(f"{i}. {q}")
                msg_parts.append("")

        msg_parts.append("Reply *START* when you begin the interview.")
        msg_parts.append("Reply *REPORT* after the interview to get the candidate report.")

        send_whatsapp_message(phone_number, "\n".join(msg_parts))

    except Exception as e:
        print(f"[WHATSAPP] Parse error: {e}")
        send_whatsapp_message(phone_number, 
            f"Error processing resume: {str(e)[:100]}")


def handle_start_session(phone_number):
    """Start an interview session for this user's candidate."""
    session = user_sessions.get(phone_number)
    if not session or not session.get('candidate_id'):
        send_whatsapp_message(phone_number, 
            "No candidate loaded. Please send a resume PDF first.")
        return

    candidate_id = session['candidate_id']

    try:
        # Call agent API to start session
        response = requests.post(
            f"{AGENT_API_URL}/sessions/start",
            json={
                'candidateId': candidate_id,
                'interviewer': phone_number
            }
        )

        if response.status_code == 200:
            data = response.json()
            session['session_id'] = data.get('sessionId')
            session['state'] = 'interview_active'

            send_whatsapp_message(phone_number, 
                f"Interview session started for *{session['candidate_name']}*.\n\n"
                "GhostCue is now listening. I will send you live nudges during the interview.\n\n"
                "Reply *STOP* to end the session.")

            # Start alert listener in background
            thread = threading.Thread(
                target=start_alert_listener, 
                args=(phone_number,),
                daemon=True
            )
            thread.start()
        else:
            send_whatsapp_message(phone_number, 
                "Could not start session. Is the agent daemon running?")

    except requests.ConnectionError:
        send_whatsapp_message(phone_number, 
            "Cannot connect to GhostCue agent. Please ensure the agent daemon is running:\n"
            "`node agent/index.js`")


def handle_stop_session(phone_number):
    """End the current interview session."""
    session = user_sessions.get(phone_number)
    if not session or session.get('state') != 'interview_active':
        send_whatsapp_message(phone_number, "No active interview session.")
        return

    try:
        response = requests.post(f"{AGENT_API_URL}/sessions/end")
        session['state'] = 'session_ended'

        send_whatsapp_message(phone_number, 
            "Interview session ended.\n\n"
            "Generating candidate report... Reply *REPORT* in a minute to receive it.")
    except Exception as e:
        send_whatsapp_message(phone_number, f"Error ending session: {e}")


def handle_report_request(phone_number):
    """Generate and send the candidate report."""
    session = user_sessions.get(phone_number)
    if not session or not session.get('candidate_id'):
        send_whatsapp_message(phone_number, "No candidate loaded.")
        return

    candidate_id = session['candidate_id']
    candidate_name = session.get('candidate_name', 'Unknown')

    try:
        # Check if report exists
        report_dir = PROJECT_ROOT / "output" / "reports"
        reports = list(report_dir.glob(f"{candidate_id}_*.pdf"))

        if reports:
            # Report already generated
            report_path = reports[-1]  # latest report
            send_whatsapp_message(phone_number, 
                f"*Candidate Report: {candidate_name}*\n"
                f"Report generated at: {report_path.stem.split('_')[-1]}\n\n"
                "Note: PDF will be sent separately if a public URL is available.")
        else:
            # Try to generate report
            send_whatsapp_message(phone_number, 
                f"Report for {candidate_name} is being generated...\n"
                "This may take a moment. I will notify you when it's ready.")

            # Trigger report generation via scoring pipeline
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "pdf_report",
                    str(PROJECT_ROOT / "scoring" / "pdf-report.py")
                )
                pdf_report = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(pdf_report)
                
                if hasattr(pdf_report, 'generate_report'):
                    report_path = pdf_report.generate_report(candidate_id)
                    send_whatsapp_message(phone_number,
                        f"Report ready for {candidate_name}!\n"
                        f"Saved to: {report_path}")
            except Exception as e:
                send_whatsapp_message(phone_number,
                    f"Report generation will be available after Phase 9.\n"
                    f"Candidate data is saved in Cognitive RAM: {candidate_id}")

    except Exception as e:
        send_whatsapp_message(phone_number, f"Error generating report: {e}")


def start_alert_listener(phone_number):
    """
    Background thread: listens for agent alerts via WebSocket
    and forwards them to the user's WhatsApp.
    """
    async def listen():
        try:
            async with websockets.connect(AGENT_WS_URL) as ws:
                # Read welcome
                await ws.recv()

                while user_sessions.get(phone_number, {}).get('state') == 'interview_active':
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(raw)

                        if data.get('event') == 'alert':
                            alert = data['data']
                            alert_type = {
                                'pressure_point': 'PROBE',
                                'contradiction': 'CONFLICT',
                                'coverage_gap': 'GAP'
                            }.get(alert.get('type'), 'ALERT')

                            msg = f"[{alert_type}] {alert.get('message', '')}"
                            if alert.get('evidence'):
                                msg += f"\n_Evidence: {alert['evidence']}_"

                            send_whatsapp_message(phone_number, msg)

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"[WHATSAPP] Alert listener error: {e}")
                        break

        except Exception as e:
            print(f"[WHATSAPP] WS connection error: {e}")

    asyncio.run(listen())


# ── Flask Webhook Routes ──

@app.route('/webhook', methods=['POST'])
def whatsapp_webhook():
    """
    Twilio WhatsApp webhook handler.
    Receives all incoming messages and media from WhatsApp.
    """
    # Extract message data from Twilio's POST
    from_number = flask_request.form.get('From', '')      # whatsapp:+1234567890
    body = flask_request.form.get('Body', '').strip()
    num_media = int(flask_request.form.get('NumMedia', 0))
    
    print(f"[WHATSAPP] Message from {from_number}: {body[:50]} (media: {num_media})")

    # Handle media (PDF resume)
    if num_media > 0:
        for i in range(num_media):
            media_url = flask_request.form.get(f'MediaUrl{i}', '')
            media_type = flask_request.form.get(f'MediaContentType{i}', '')

            if 'pdf' in media_type.lower():
                # Save PDF to input/resumes/
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"whatsapp_{timestamp}.pdf"
                save_path = PROJECT_ROOT / "input" / "resumes" / filename

                if download_media(media_url, str(save_path)):
                    # Acknowledge receipt
                    resp = MessagingResponse()
                    resp.message("Resume received! Parsing now... I will send you interview questions shortly.")
                    
                    # Parse in background thread
                    thread = threading.Thread(
                        target=parse_resume_for_user,
                        args=(from_number, save_path),
                        daemon=True
                    )
                    thread.start()
                    return str(resp)
                else:
                    resp = MessagingResponse()
                    resp.message("Could not download the PDF. Please try sending it again.")
                    return str(resp)
            else:
                resp = MessagingResponse()
                resp.message(f"I only accept PDF files. You sent: {media_type}")
                return str(resp)

    # Handle text commands
    body_upper = body.upper()

    if body_upper in ('HI', 'HELLO', 'HEY', 'START'):
        if body_upper == 'START' and from_number in user_sessions:
            handle_start_session(from_number)
            return str(MessagingResponse())

        resp = MessagingResponse()
        resp.message(
            "Welcome to *GhostCue* - Your Silent AI Co-Interviewer\n\n"
            "Send me a candidate's resume (PDF) and I will:\n"
            "1. Parse it and extract key skills\n"
            "2. Generate custom interview questions\n"
            "3. Coach you in real-time during the interview\n"
            "4. Generate a structured candidate report\n\n"
            "Start by sending a PDF resume!"
        )
        return str(resp)

    elif body_upper == 'STOP':
        handle_stop_session(from_number)
        return str(MessagingResponse())

    elif body_upper == 'REPORT':
        handle_report_request(from_number)
        return str(MessagingResponse())

    elif body_upper == 'STATUS':
        session = user_sessions.get(from_number, {})
        state = session.get('state', 'no session')
        candidate = session.get('candidate_name', 'none')

        resp = MessagingResponse()
        resp.message(
            f"*Session Status*\n"
            f"Candidate: {candidate}\n"
            f"State: {state}\n"
            f"Session ID: {session.get('session_id', 'N/A')}"
        )
        return str(resp)

    elif body_upper == 'HELP':
        resp = MessagingResponse()
        resp.message(
            "*GhostCue Commands:*\n\n"
            "Send PDF - Upload a candidate resume\n"
            "*START* - Begin interview session\n"
            "*STOP* - End interview session\n"
            "*REPORT* - Get candidate report\n"
            "*STATUS* - Check current session\n"
            "*HELP* - Show this message"
        )
        return str(resp)

    else:
        resp = MessagingResponse()
        resp.message(
            "I didn't understand that. Reply *HELP* for available commands, "
            "or send a PDF resume to get started."
        )
        return str(resp)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return {
        'service': 'ghostcue-whatsapp',
        'status': 'running',
        'active_sessions': len(user_sessions),
        'twilio_configured': bool(TWILIO_SID and not TWILIO_SID.startswith('your'))
    }


# ── Entry Point ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="GhostCue WhatsApp Bot")
    parser.add_argument("--port", type=int, default=5002, help="Webhook port (default: 5002)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print("")
    print("  GhostCue WhatsApp Bot")
    print("  " + "-" * 35)
    print(f"  Webhook:  http://localhost:{args.port}/webhook")
    print(f"  Health:   http://localhost:{args.port}/health")
    print(f"  Twilio:   {'Configured' if TWILIO_SID and not TWILIO_SID.startswith('your') else 'NOT configured (mock mode)'}")
    print("")
    print("  To connect with Twilio:")
    print(f"  1. Run: ngrok http {args.port}")
    print("  2. Set ngrok URL as Twilio WhatsApp webhook")
    print("  3. Send 'join <sandbox-word>' to your Twilio WhatsApp number")
    print("")

    app.run(host='0.0.0.0', port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
