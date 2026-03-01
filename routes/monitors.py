# ─────────────────────────────────────────────────────────────────
# routes/monitors.py — All API Endpoints
#
# WHAT IS A ROUTER?
# Instead of defining all routes directly on the `app` object
# in main.py, FastAPI lets us create an APIRouter.
# Think of it like a mini-app that handles a specific group
# of related endpoints — in this case, everything about monitors.
#
# In main.py we simply "include" this router.
# This pattern is called MODULAR ROUTING and is standard in
# production FastAPI applications.
#
# SEPARATION OF CONCERNS:
# This file owns all HTTP request/response logic.
# It does NOT know how timers work (that's timer.py)
# It does NOT know how alerts work (that's alerts.py)
# It does NOT know where data is stored (that's database.py)
# It just receives requests, calls the right functions, returns responses.
# ─────────────────────────────────────────────────────────────────

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
# APIRouter → groups related endpoints together
# HTTPException → sends proper HTTP error responses

from models import MonitorCreate
# Import our Pydantic model for request validation

from database import monitors_db, active_tasks
# Import our in-memory storage dictionaries

from timer import start_countdown
# Import the background countdown function

# Named logger for this module
logger = logging.getLogger("routes")

# Create the router
# prefix="/monitors" means ALL routes here start with /monitors
# tags=["monitors"] groups them together in the /docs page
router = APIRouter(
    prefix="/monitors",
    tags=["Monitors"]
)


# ─────────────────────────────────────────────────────────────────
# POST /monitors — Register a new device monitor
# ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_monitor(monitor: MonitorCreate):
    """
    Registers a new device and starts its countdown timer.

    Flow:
    1. Validate input via Pydantic (automatic)
    2. Reject duplicate device IDs
    3. Reject invalid timeout values
    4. Store monitor in memory
    5. Start background countdown timer
    6. Return 201 Created
    """

    # Reject duplicate IDs — every device must have a unique identifier
    if monitor.id in monitors_db:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{monitor.id}' already exists. Use a unique device ID."
        )

    # Timeout must make logical sense — 0 or negative is meaningless
    if monitor.timeout <= 0:
        raise HTTPException(
            status_code=400,
            detail="Timeout must be greater than 0 seconds."
        )

    # Save the monitor to our in-memory storage
    # This is our "database record" for this device
    monitors_db[monitor.id] = {
        "id": monitor.id,
        "timeout": monitor.timeout,
        "alert_email": monitor.alert_email,
        "status": "active",              # possible values: active | paused | down
        "created_at": datetime.utcnow().isoformat(),
        "last_heartbeat": None,          # None until first heartbeat arrives
        "heartbeat_history": []          # grows with every heartbeat — Developer's Choice
    }

    # Start the background timer
    # asyncio.create_task() schedules start_countdown() to run concurrently
    # It does NOT block — this line returns immediately
    # The countdown runs silently in the background
    task = asyncio.create_task(
        start_countdown(monitor.id, monitor.timeout)
    )

    # Store the task reference so we can cancel it on heartbeat
    # Without this reference we'd have no way to stop the timer
    active_tasks[monitor.id] = task

    logger.info(f"✅ Monitor registered: '{monitor.id}' | timeout: {monitor.timeout}s | email: {monitor.alert_email}")

    return {
        "message": f"Monitor created for device '{monitor.id}'",
        "device_id": monitor.id,
        "timeout": monitor.timeout,
        "status": "active"
    }


# ─────────────────────────────────────────────────────────────────
# POST /monitors/{device_id}/heartbeat — Reset the countdown
# ─────────────────────────────────────────────────────────────────

@router.post("/{device_id}/heartbeat")
async def heartbeat(device_id: str):
    """
    Resets the countdown timer for a device.

    Flow:
    1. Check device exists → 404 if not
    2. Check device is not already down → 400 if down
    3. If paused → automatically resume it
    4. Cancel the current running timer
    5. Start a fresh timer from full timeout
    6. Record heartbeat in history log
    7. Return 200 OK
    """

    # Device must be registered before it can send heartbeats
    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found. Register it first via POST /monitors."
        )

    monitor = monitors_db[device_id]

    # A down device cannot be revived by a heartbeat
    # It needs to be fully re-registered
    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Create a new monitor to restart tracking."
        )

    # Per the spec: "Calling the heartbeat endpoint again automatically
    # un-pauses the monitor and restarts the timer"
    if monitor["status"] == "paused":
        monitors_db[device_id]["status"] = "active"
        logger.info(f"▶️  Monitor '{device_id}' automatically resumed via heartbeat")

    # Cancel the currently running background timer
    # .cancel() injects CancelledError into the sleeping coroutine
    # The try/except in timer.py catches it and returns silently
    if device_id in active_tasks:
        active_tasks[device_id].cancel()

    # Start a completely fresh countdown from the full timeout duration
    new_task = asyncio.create_task(
        start_countdown(device_id, monitor["timeout"])
    )
    active_tasks[device_id] = new_task

    # Record this heartbeat with a precise UTC timestamp
    now = datetime.utcnow().isoformat()
    monitors_db[device_id]["last_heartbeat"] = now
    monitors_db[device_id]["status"] = "active"

    # Append to the heartbeat history log (Developer's Choice feature)
    monitors_db[device_id]["heartbeat_history"].append({
        "received_at": now,
        "event": "heartbeat",
        "timer_reset_to": monitor["timeout"]
    })

    logger.info(f"💓 Heartbeat: '{device_id}' | timer reset to {monitor['timeout']}s")

    return {
        "message": f"Heartbeat received. Timer reset for '{device_id}'",
        "device_id": device_id,
        "timeout": monitor["timeout"],
        "last_heartbeat": now,
        "status": "active"
    }


# ─────────────────────────────────────────────────────────────────
# POST /monitors/{device_id}/pause — Pause the countdown
# Bonus story: The "Snooze Button" for maintenance windows
# ─────────────────────────────────────────────────────────────────

@router.post("/{device_id}/pause")
async def pause_monitor(device_id: str):
    """
    Pauses the countdown timer for a device.
    Use case: maintenance technician repairing a device.

    - Cancels the background timer completely
    - No alert will fire while paused
    - Sending a heartbeat automatically resumes the monitor
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found."
        )

    monitor = monitors_db[device_id]

    # Can't pause a device that's already triggered
    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Cannot pause a down monitor."
        )

    # Idempotency check — pausing an already-paused monitor does nothing useful
    if monitor["status"] == "paused":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already paused."
        )

    # Cancel the countdown so it doesn't fire during maintenance
    if device_id in active_tasks:
        active_tasks[device_id].cancel()

    monitors_db[device_id]["status"] = "paused"

    logger.info(f"⏸️  Monitor '{device_id}' paused")

    return {
        "message": f"Monitor '{device_id}' paused. Send a heartbeat to resume.",
        "device_id": device_id,
        "status": "paused"
    }


# ─────────────────────────────────────────────────────────────────
# GET /monitors — List all monitors
# ─────────────────────────────────────────────────────────────────

@router.get("")
def list_monitors():
    """
    Returns all registered monitors and their current statuses.
    Great for a dashboard overview of all devices.
    """

    if not monitors_db:
        return {"monitors": [], "total": 0}

    return {
        "monitors": list(monitors_db.values()),
        "total": len(monitors_db)
    }


# ─────────────────────────────────────────────────────────────────
# GET /monitors/{device_id} — Get a single monitor's status
# ─────────────────────────────────────────────────────────────────

@router.get("/{device_id}")
def get_monitor(device_id: str):
    """
    Returns the current state of a single monitor.
    Useful for real-time status checks and dashboards.
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found."
        )

    return monitors_db[device_id]


# ─────────────────────────────────────────────────────────────────
# GET /monitors/{device_id}/history — Heartbeat history log
# ★ DEVELOPER'S CHOICE FEATURE ★
# ─────────────────────────────────────────────────────────────────

@router.get("/{device_id}/history")
def get_monitor_history(device_id: str):
    """
    Returns the full heartbeat audit log for a device.

    WHY I BUILT THIS (Developer's Choice reasoning):
    The spec tracks current state but has no memory.
    Engineers responding to alerts need to know:
    - Was this device pinging consistently before it died?
    - Did heartbeat frequency drop recently (early warning sign)?
    - When exactly was the last healthy ping?

    This is the OBSERVABILITY layer. Tools like AWS CloudWatch,
    Datadog, and Grafana are built on this principle —
    time-series event logs for diagnosing incidents.

    In production: stored in InfluxDB or TimescaleDB
    (purpose-built time-series databases)
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found."
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