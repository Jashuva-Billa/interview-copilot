import os
import smtplib
import time
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import config

def send_transcript_email(candidate_name: str, timestamp: str):
    """Reads interview_transcript.md and latency_report.md from the root directory and sends them as an email."""
    if not config.EMAIL_RECEIVER:
        print("[Email Service] No EMAIL_RECEIVER configured. Skipping email.")
        return

    safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    # Reports are kept in one local, Git-ignored directory.
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    transcript_path = report_dir / f"interview_transcript_{safe_name}_{timestamp}.md"
    latency_path = report_dir / f"latency_report_{safe_name}_{timestamp}.md"
    token_path = report_dir / f"token_report_{safe_name}_{timestamp}.md"
 
    # Verify if files exist or if we have content
    has_transcript = transcript_path.is_file()
    has_latency = latency_path.is_file()
    has_token = token_path.is_file()
 
    if not has_transcript and not has_latency and not has_token:
        print("[Email Service] No transcript, latency, or token report files found to send. Skipping.")
        return

    print(f"[Email Service] Preparing to send transcript email to {config.EMAIL_RECEIVER}...")

    # Formulate subject and body
    readable_time = time.strftime('%Y-%m-%d %H:%M:%S')
    subject = f"Interview Transcript & Report - {candidate_name} - {config.JOB_ROLE} - {readable_time}"

    body_parts = []
    body_parts.append(f"Hello,\n\nPlease find attached the interview transcript, latency report, and token/cost summary report for candidate '{candidate_name}' for the role of '{config.JOB_ROLE}' generated on {readable_time}.\n\n")

    if has_token:
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                content = f.read()
                totals_sec = ""
                if "## Totals" in content:
                    totals_sec = "## Totals" + content.split("## Totals")[-1].split("## Conversation")[0]
                body_parts.append("### Session Token & Cost Totals:\n")
                body_parts.append(totals_sec.strip() + "\n\n")
                body_parts.append("-" * 40 + "\n\n")
        except Exception as e:
            body_parts.append(f"Could not read token report content: {e}\n\n")

    if has_transcript:
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                content = f.read()
                body_parts.append("### Interview Transcript Overview:\n")
                body_parts.append(content[:2000] + ("\n... [Truncated in email body, see attachment] ..." if len(content) > 2000 else ""))
                body_parts.append("\n\n" + "-" * 40 + "\n\n")
        except Exception as e:
            body_parts.append(f"Could not read interview transcript content: {e}\n\n")

    if has_latency:
        try:
            with open(latency_path, "r", encoding="utf-8") as f:
                content = f.read()
                body_parts.append("### Latency Analysis Overview:\n")
                body_parts.append(content[:2000] + ("\n... [Truncated in email body, see attachment] ..." if len(content) > 2000 else ""))
        except Exception as e:
            body_parts.append(f"Could not read latency report content: {e}\n\n")

    body_text = "".join(body_parts)

    # Build MIMEMultipart email
    msg = MIMEMultipart()
    sender = config.SMTP_USERNAME or "copilot@example.com"
    msg['From'] = sender
    msg['To'] = config.EMAIL_RECEIVER
    msg['Subject'] = subject

    msg.attach(MIMEText(body_text, 'plain'))

    # Helper function to attach files
    def attach_file(path, filename):
        if path.is_file():
            try:
                with open(path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename= {filename}",
                    )
                    msg.attach(part)
            except Exception as e:
                print(f"[Email Service] Error attaching file {filename}: {e}")

    if has_transcript:
        attach_file(transcript_path, f"interview_transcript_{safe_name}_{timestamp}.md")
    if has_latency:
        attach_file(latency_path, f"latency_report_{safe_name}_{timestamp}.md")
    if has_token:
        attach_file(token_path, f"token_report_{safe_name}_{timestamp}.md")

    # Connect and send
    try:
        if not config.SMTP_SERVER:
            print("[Email Service] SMTP_SERVER not configured. Cannot send email.")
            return

        if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
            print("[Email Service] SMTP_USERNAME or SMTP_PASSWORD is not configured in .env. Please configure your email credentials (such as Gmail app password) to send transcripts via email.")
            return

        print(f"[Email Service] Connecting to SMTP server {config.SMTP_SERVER}:{config.SMTP_PORT}...")
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=15)
        
        if config.SMTP_USE_TLS:
            server.starttls()
            
        if config.SMTP_USERNAME and config.SMTP_PASSWORD:
            print(f"[Email Service] Logging in as {config.SMTP_USERNAME}...")
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            
        server.sendmail(sender, config.EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("[Email Service] Email sent successfully.")
    except Exception as e:
        print(f"[Email Service] Failed to send email: {e}")
        traceback.print_exc()
