# ─────────────────────────────────────────────────────────────────
# alerts.py — Logging Setup & Alert Notifications
#
# SEPARATION OF CONCERNS:
# All alerting logic lives here. If we upgrade from simulated
# emails to real SendGrid/AWS SES emails in production,
# we only change THIS file. No other file needs to know HOW
# alerts are sent — only that they call send_alert().
#
# WHY LOGGING INSTEAD OF PRINT?
# print() just dumps text to the terminal with no context.
# Python's logging module adds:
#   - Timestamp on every message automatically
#   - Severity levels (INFO, WARNING, CRITICAL etc.)
#   - Named loggers so you know which file the message came from
#   - In production: can route logs to files, Datadog, CloudWatch etc.
# ─────────────────────────────────────────────────────────────────

import logging
# Python's built-in logging library
# Used in every serious backend system

# ── LOGGING CONFIGURATION ─────────────────────────────────────────
# basicConfig sets the global format for ALL log messages
# %(asctime)s    → timestamp e.g. "2026-03-01 10:34:22"
# %(levelname)s  → severity e.g. "INFO", "CRITICAL"
# %(name)s       → which logger sent this e.g. "alerts"
# %(message)s    → the actual message we wrote
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — [%(name)s] — %(message)s"
)

# Create a named logger specifically for this file
# Best practice: each module has its own logger
# This makes it easy to trace WHERE a log message came from
logger = logging.getLogger("alerts")


def simulate_email_alert(device_id: str, alert_email: str, timestamp: str):
    """
    Simulates sending an email alert to the device administrator.

    WHY SIMULATE?
    The spec says: "simulate sending an email" — so we log exactly
    what the email would contain. This proves the system KNOWS
    what to send, even if it's not connected to a mail server.

    IN PRODUCTION this function would:
    1. Import SendGrid or AWS SES SDK
    2. Compose an HTML email template
    3. Call the email API with credentials from environment variables
    4. Handle success/failure and retry on failure
    5. Log the result either way

    We use environment variables for credentials — NEVER hardcode
    API keys in source code (security best practice).
    """

    logger.info("=" * 55)
    logger.info("📧 SIMULATING EMAIL ALERT")
    logger.info(f"   To:      {alert_email}")
    logger.info(f"   Subject: CRITICAL — Device '{device_id}' is offline")
    logger.info(f"   Body:    Device '{device_id}' has not sent a heartbeat.")
    logger.info(f"            Last checked: {timestamp}")
    logger.info(f"            Immediate action required.")
    logger.info(f"   From:    noreply@critmon.com")
    logger.info(f"   System:  Pulse Check API v1.0.0")
    logger.info("=" * 55)


def fire_alert(device_id: str, alert_email: str, timestamp: str):
    """
    The main alert function — called when a device timer expires.

    This function:
    1. Logs the CRITICAL alert to the console (spec requirement)
    2. Calls simulate_email_alert() to show what email would be sent

    Having this as a separate function means:
    - It's easy to test in isolation
    - Adding more alert channels (SMS, Slack, webhook) is just
      adding more function calls here
    """

    # Build the exact JSON alert object the spec requires:
    # {"ALERT": "Device device-123 is down!", "time": <timestamp>}
    alert_payload = {
        "ALERT": f"Device {device_id} is DOWN! No heartbeat received.",
        "time": timestamp,
        "alert_email": alert_email
    }

    # Log as CRITICAL — the most severe level
    # This is the console.log equivalent the spec asks for
    logger.critical("🚨 " + "=" * 50)
    logger.critical(f"DEVICE DOWN: {alert_payload}")
    logger.critical("=" * 50)

    # Simulate the email notification
    simulate_email_alert(device_id, alert_email, timestamp)