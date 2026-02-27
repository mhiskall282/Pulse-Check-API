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
# BACKGROUND TIMER FUNCTION
# runs silently while your API keeps working
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
        # This runs when heartbeat cancels the task
        # We just return silently — no alert needed
        return

    # After sleeping, check the monitor still exists
    if device_id not in monitors_db:
        return  # monitor was removed, do nothing

    monitor = monitors_db[device_id]

    # Only fire alert if status is still "active"
    # (not paused, not already down)
    if monitor["status"] == "active":

        # Update status to "down"
        monitors_db[device_id]["status"] = "down"

        # Build the alert — in production this sends an email/webhook
        alert = {
            "ALERT": f"Device {device_id} is DOWN! No heartbeat received.",
            "time": datetime.utcnow().isoformat(),
            "alert_email": monitor["alert_email"]
        }

        # Print to console (spec requirement)
        print("\n🚨 " + "="*50)
        print(alert)
        print("="*50 + "\n")

# ─────────────────────────────────────────────────────────────────
# ROUTE 1: GET / — Health check
# ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
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
    """

    # Reject duplicate device IDs
    if monitor.id in monitors_db:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{monitor.id}' already exists"
        )

    # Timeout must be a positive number
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
        "last_heartbeat": None         # no heartbeat received yet
    }

    # Start the background countdown and save the task reference
    # so we can cancel it later when a heartbeat arrives
    task = asyncio.create_task(
        start_countdown(monitor.id, monitor.timeout)
    )
    active_tasks[monitor.id] = task

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
    Cancels the old timer and starts a fresh one.
    """

    # Device must exist
    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    monitor = monitors_db[device_id]

    # If monitor is already down, can't reset it
    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Create a new one."
        )

    # If monitor was paused, heartbeat un-pauses it
    if monitor["status"] == "paused":
        monitors_db[device_id]["status"] = "active"

    # Cancel the currently running timer
    if device_id in active_tasks:
        old_task = active_tasks[device_id]
        old_task.cancel()  # sends cancellation — our try/except catches it

    # Start a brand new countdown from the full timeout
    new_task = asyncio.create_task(
        start_countdown(device_id, monitor["timeout"])
    )
    active_tasks[device_id] = new_task

    # Record when this heartbeat arrived
    monitors_db[device_id]["last_heartbeat"] = datetime.utcnow().isoformat()
    monitors_db[device_id]["status"] = "active"

    return {
        "message": f"Heartbeat received. Timer reset for '{device_id}'",
        "device_id": device_id,
        "timeout": monitor["timeout"],
        "last_heartbeat": monitors_db[device_id]["last_heartbeat"],
        "status": "active"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 4: POST /monitors/{id}/pause — Pause the countdown
# Bonus story from the spec
# ─────────────────────────────────────────────────────────────────

@app.post("/monitors/{device_id}/pause")
async def pause_monitor(device_id: str):
    """
    Pauses the countdown for a device.
    No alert will fire while paused.
    Sending a heartbeat will automatically un-pause it.
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    monitor = monitors_db[device_id]

    if monitor["status"] == "down":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already down. Cannot pause."
        )

    if monitor["status"] == "paused":
        raise HTTPException(
            status_code=400,
            detail=f"Monitor '{device_id}' is already paused."
        )

    # Cancel the running timer so it doesn't fire while paused
    if device_id in active_tasks:
        active_tasks[device_id].cancel()

    # Update status to paused
    monitors_db[device_id]["status"] = "paused"

    return {
        "message": f"Monitor '{device_id}' paused. Send a heartbeat to resume.",
        "device_id": device_id,
        "status": "paused"
    }

# ─────────────────────────────────────────────────────────────────
# ROUTE 5: GET /monitors/{id} — Get a single monitor's status
# Bonus route — shows initiative, great for interview demo
# ─────────────────────────────────────────────────────────────────

@app.get("/monitors/{device_id}")
def get_monitor(device_id: str):
    """
    Returns the current state of a single monitor.
    """

    if device_id not in monitors_db:
        raise HTTPException(
            status_code=404,
            detail=f"Monitor '{device_id}' not found"
        )

    return monitors_db[device_id]

# ─────────────────────────────────────────────────────────────────
# ROUTE 6: GET /monitors — List all monitors
# Great for a dashboard overview
# ─────────────────────────────────────────────────────────────────

@app.get("/monitors")
def list_monitors():
    """
    Returns all registered monitors and their statuses.
    """

    if not monitors_db:
        return {"monitors": [], "total": 0}

    return {
        "monitors": list(monitors_db.values()),
        "total": len(monitors_db)
    }