# ─────────────────────────────────────────────────────────────────
# IMPORTS — bringing in the tools we need
# ─────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
# FastAPI → the framework that runs our API
# HTTPException → lets us send error responses like 404, 400 etc.

from pydantic import BaseModel
# BaseModel → lets us define what incoming JSON should look like

from typing import Optional
# Optional → means a field can be present or absent (not required)

import asyncio
# asyncio → Python's built-in library for running background tasks
# We need this to run timers in the background without freezing the API

from datetime import datetime
# datetime → for timestamps when alerts fire

import logging
# logging → Python's built-in logging system
# More professional than plain print() — used in every real backend system
# Levels: DEBUG → INFO → WARNING → ERROR → CRITICAL
# We use CRITICAL for device down alerts so they stand out in logs

# ─────────────────────────────────────────────────────────────────
# LOGGING SETUP
# basicConfig sets the format for every log message in this app
# asctime = timestamp, levelname = INFO/CRITICAL etc, message = our text
# In production: logs would go to a file or monitoring service like Datadog
# ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s"
)

# Create a logger for this specific module (main.py)
# Best practice: each file has its own named logger
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pulse Check API",
    description="Dead Man's Switch API for monitoring remote devices",
    version="1.0.0"
)

# ─────────────────────────────────────────────────────────────────
# IN-MEMORY DATABASE
# A plain Python dictionary — works like a table in RAM
# Key = device id (string), Value = monitor info (dict)
# Resets on server restart — fine for this project
# In production: would use PostgreSQL or Redis for persistence
# ─────────────────────────────────────────────────────────────────

monitors_db = {}

# Stores the running background timer TASKS
# We need this so we can cancel a timer when a heartbeat arrives
# Key = device id, Value = the asyncio Task object
active_tasks = {}

# ─────────────────────────────────────────────────────────────────
# DATA MODELS — defining what JSON the API accepts
# ─────────────────────────────────────────────────────────────────

class MonitorCreate(BaseModel):
    """
    Shape of the JSON body for POST /monitors
    {
        "id": "device-123",
        "timeout": 60,
        "alert_email": "admin@critmon.com"
    }
    """
    id: str           # unique device identifier
    timeout: int      # seconds before alert fires
    alert_email: str  # who to notify when device goes down

# ─────────────────────────────────────────────────────────────────
# SIMULATED EMAIL FUNCTION
# In production this would use SendGrid, AWS SES, or smtplib
# For this project we simulate it with structured log messages
# This satisfies the spec requirement to "simulate sending an email"
# ─────────────────────────────────────────────────────────────────

def simulate_email_alert(device_id: str, alert_email: str, timestamp: str):
    """
    Simulates sending an email alert to the device administrator.

    In a real system this function would:
    - Connect to an SMTP server or email API (e.g. SendGrid)
    - Compose an HTML email with device details
    - Send it to the alert_email address
    - Log success or failure of the send

    For this project we log what the email would contain.
    """
    logger.info("=" * 55)
    logger.info("📧 SIMULATING EMAIL ALERT")
    logger.info(f"   To:      {alert_email}")
    logger.info(f"   Subject: CRITICAL — Device {device_id} is offline")
    logger.info(f"   Body:    Your device '{device_id}' has not sent a")
    logger.info(f"            heartbeat since {timestamp}.")
    logger.info(f"            Immediate action required.")
    logger.info(f"   Footer:  Sent by Pulse Check API — CritMon Systems")
    logger.info("=" * 55)

# ─────────────────────────────────────────────────────────────────
# BACKGROUND TIMER FUNCTION
# Runs silently while your API keeps working
# asyncio.sleep() pauses THIS function only — not the whole server
# ─────────────────────────────────────────────────────────────────

async def start_countdown(device_id: str, timeout: int):
    """
    Counts down in the background.
    If no heartbeat arrives before timeout → fires the alert.
    """

    try:
        # Wait for the full timeout duration (e.g. 60 seconds)
        await asyncio.sleep(timeout)

    except asyncio.CancelledError:
        # This runs when a heartbeat cancels the task
        # We return silently — cancellation is normal and expected
        # No alert should fire when a device is actively sending heartbeats
        return

    # After sleeping, check the monitor still exists
    if device_id not in monitors_db:
        return  # monitor was removed, do nothing

    monitor = monitors_db[device_id]

    # Only fire alert if status is still "active"
    # (not paused, not already down)
    if monitor["status"] == "active":

        # Update status to "down" in our database
        monitors_db[device_id]["status"] = "down"

        # Get the current timestamp for the alert
        timestamp = datetime.utcnow().isoformat()

        # Build the alert payload — exact format the spec requires
        alert = {
            "ALERT": f"Device {device_id} is DOWN! No heartbeat received.",
            "time": timestamp,
            "alert_email": monitor["alert_email"]
        }

        # Log as CRITICAL — the highest severity level
        # This is the console.log equivalent the spec asks for
        logger.critical("🚨 " + "=" * 50)
        logger.critical(f"DEVICE DOWN ALERT: {alert}")
        logger.critical("=" * 50)

        # Simulate sending the email notification
        simulate_email_alert(device_id, monitor["alert_email"], timestamp)

# ─────────────────────────────────────────────────────────────────
# ROUTE 1: GET / — Health check
# Simple endpoint to confirm the API is running
# ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    logger.info("Health check endpoint hit")
    return {
        "message": "Pulse Check API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 2: POST /monitors — Register a new device monitor
# ─────────────────────────────────────────────────────────────────

@app.post("/monitors", status_code=201)
async def create_monitor(monitor: MonitorCreate):
    """
    Registers a new device and starts its countdown timer.

    - Validates the input using Pydantic
    - Stores monitor in memory
    - Starts a background countdown timer
    - Returns 201 Created
    """

    # Reject duplicate device IDs — each device needs a unique ID
    if monitor.id in monitors_db:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{monitor.id}' already exists"
        )

    # Timeout must be a positive number — 0 or negative makes no sense
    if monitor.timeout <= 0:
        raise HTTPException(
            status_code=400,
            detail="Timeout must be greater than 0"
        )

    # Save the monitor to our in-memory database
    monitors_db[monitor.id] = {
        "id": monitor.id,
        "timeout": monitor.timeout,
        "alert_email": monitor.alert_email,
        "status": "active",            # active | down | paused
        "created_at": datetime.utcnow().isoformat(),
        "last_heartbeat": None,        # no heartbeat received yet
        "heartbeat_history": []        # grows with every heartbeat received
        # In production: heartbeat_history would be a separate DB table
    }

    # Start the background countdown and save the task reference
    # asyncio.create_task() runs it concurrently without blocking this response
    # We save the reference so we can cancel it when a heartbeat arrives
    task = asyncio.create_task(
        start_countdown(monitor.id, monitor.timeout)
    )
    active_tasks[monitor.id] = task

    logger.info(f"✅ Monitor created for device '{monitor.id}' | timeout: {monitor.timeout}s")

    # Send confirmation back to client
    return {
        "message": f"Monitor created for device '{monitor.id}'",
        "device_id": monitor.id,
        "timeout": monitor.timeout,
        "status": "active"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 3: POST /monitors/{id}/heartbeat — Reset the countdown
# {device_id} is a path parameter — comes directly from the URL
# e.g. /monitors/device-123/heartbeat → device_id = "device-123"
# ─────────────────────────────────────────────────────────────────

@app.post("/monitors/{device_id}/heartbeat")
async def heartbeat(device_id: str):
    """
    Resets the countdown timer for a device.

    - Cancels the currently running timer
    - Starts a fresh timer from the full timeout duration
    - Records the heartbeat in history log
    - Returns 200 OK
    """

    # Device must exist in our database
    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    monitor = monitors_db[device_id]

    # A down device cannot send heartbeats
    # It must be re-registered as a new monitor
    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Create a new monitor."
        )

    # If monitor was paused, heartbeat automatically un-pauses it
    # This matches the spec: "Calling the heartbeat endpoint again
    # automatically un-pauses the monitor and restarts the timer"
    if monitor["status"] == "paused":
        monitors_db[device_id]["status"] = "active"
        logger.info(f"▶️  Monitor '{device_id}' resumed via heartbeat")

    # Cancel the currently running background timer
    # .cancel() sends a CancelledError to the coroutine
    # Our try/except in start_countdown catches it and returns silently
    if device_id in active_tasks:
        old_task = active_tasks[device_id]
        old_task.cancel()

    # Start a brand new countdown from the full timeout duration
    new_task = asyncio.create_task(
        start_countdown(device_id, monitor["timeout"])
    )
    active_tasks[device_id] = new_task

    # Record the timestamp of this heartbeat
    now = datetime.utcnow().isoformat()
    monitors_db[device_id]["last_heartbeat"] = now
    monitors_db[device_id]["status"] = "active"

    # Append this heartbeat to the history log (Developer's Choice feature)
    monitors_db[device_id]["heartbeat_history"].append({
        "received_at": now,
        "event": "heartbeat",
        "timer_reset_to": monitor["timeout"]
    })

    logger.info(f"💓 Heartbeat received for '{device_id}' | timer reset to {monitor['timeout']}s")

    return {
        "message": f"Heartbeat received. Timer reset for '{device_id}'",
        "device_id": device_id,
        "timeout": monitor["timeout"],
        "last_heartbeat": monitors_db[device_id]["last_heartbeat"],
        "status": "active"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 4: POST /monitors/{id}/pause — Pause the countdown
# Bonus story from the spec — the "Snooze Button"
# Use case: maintenance technician repairing a device
# ─────────────────────────────────────────────────────────────────

@app.post("/monitors/{device_id}/pause")
async def pause_monitor(device_id: str):
    """
    Pauses the countdown timer for a device.

    - Cancels the background timer completely
    - No alert will fire while monitor is paused
    - Send a heartbeat to automatically resume
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    monitor = monitors_db[device_id]

    # Can't pause a device that's already down
    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Cannot pause."
        )

    # Can't pause something already paused
    if monitor["status"] == "paused":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already paused."
        )

    # Cancel the running timer so it doesn't fire during maintenance
    if device_id in active_tasks:
        active_tasks[device_id].cancel()

    # Update status
    monitors_db[device_id]["status"] = "paused"

    logger.info(f"⏸️  Monitor '{device_id}' paused")

    return {
        "message": f"Monitor '{device_id}' paused. Send a heartbeat to resume.",
        "device_id": device_id,
        "status": "paused"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 5: GET /monitors/{id} — Get a single monitor's status
# Bonus route — great for checking device health on demand
# ─────────────────────────────────────────────────────────────────

@app.get("/monitors/{device_id}")
def get_monitor(device_id: str):
    """
    Returns the current state of a single monitor.
    Useful for dashboards and real-time status checks.
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    return monitors_db[device_id]

# ─────────────────────────────────────────────────────────────────
# ROUTE 6: GET /monitors — List all monitors
# Returns every registered monitor and their current status
# ─────────────────────────────────────────────────────────────────

@app.get("/monitors")
def list_monitors():
    """
    Returns all registered monitors and their statuses.
    Great for a dashboard overview of all devices.
    """

    if not monitors_db:
        return {"monitors": [], "total": 0}

    return {
        "monitors": list(monitors_db.values()),
        "total": len(monitors_db)
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 7: GET /monitors/{id}/history — Heartbeat history log
# ★ DEVELOPER'S CHOICE FEATURE ★
# Adds observability — engineers can audit device behaviour over time
# ─────────────────────────────────────────────────────────────────

@app.get("/monitors/{device_id}/history")
def get_monitor_history(device_id: str):
    """
    Returns the full heartbeat audit log for a device.

    Why this matters:
    - Shows HOW OFTEN a device is checking in
    - Identifies devices that are barely alive (pinging less frequently)
    - Gives engineers an audit trail before and after an incident
    - In production: stored in a time-series DB like InfluxDB or TimescaleDB
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    monitor = monitors_db[device_id]
    history = monitor["heartbeat_history"]

    return {
        "device_id": device_id,
        "status": monitor["status"],
        "total_heartbeats": len(history),
        "first_heartbeat": history[0]["received_at"] if history else None,
        "last_heartbeat": monitor["last_heartbeat"],
        "history": history
    }