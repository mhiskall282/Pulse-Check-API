# ─────────────────────────────────────────────────────────────────
# IMPORTS — bringing in the tools we need
# ─────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException  
# FastAPI → the framework that runs our API
# HTTPException → lets us send error responses like 404, 400 etc.

from pydantic import BaseModel, EmailStr
# BaseModel → lets us define what incoming JSON should look like
# EmailStr → automatically validates that a string is a real email format

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
    title="Pulse Check API",           # shows in the /docs page
    description="Dead Man's Switch API for monitoring remote devices",
    version="1.0.0"
)

# ─────────────────────────────────────────────────────────────────
# IN-MEMORY DATABASE
# This is a Python dictionary that stores all monitors
# Think of it like a table in a database, but living in RAM
# Key = device id (string), Value = monitor info (dict)
#
# NOTE: This resets when the server restarts — that's fine for this
# project. In production you'd use a real database like PostgreSQL
# ─────────────────────────────────────────────────────────────────

monitors_db = {}

# ─────────────────────────────────────────────────────────────────
# DATA MODELS — defining what JSON the API accepts
# ─────────────────────────────────────────────────────────────────

class MonitorCreate(BaseModel):
    """
    This is the shape of the JSON body for POST /monitors
    Example:
    {
        "id": "device-123",
        "timeout": 60,
        "alert_email": "admin@critmon.com"
    }
    """
    id: str                    # unique device identifier
    timeout: int               # how many seconds before alert fires
    alert_email: str           # who to notify when device goes down

class MonitorResponse(BaseModel):
    """
    This is what we send BACK to the client after creating a monitor
    """
    message: str
    device_id: str
    timeout: int
    status: str

# ─────────────────────────────────────────────────────────────────
# BACKGROUND TIMER FUNCTION
# This runs silently in the background while your API keeps working
# asyncio.sleep() pauses THIS function only — not the whole server
# ─────────────────────────────────────────────────────────────────

async def start_countdown(device_id: str, timeout: int):
    """
    Counts down in the background.
    If the device doesn't send a heartbeat before timeout,
    this function fires the alert.
    """

    # Wait for the full timeout duration (e.g. 60 seconds)
    await asyncio.sleep(timeout)

    # After sleeping, check if this monitor still exists
    # (it might have been deleted or already handled)
    if device_id not in monitors_db:
        return  # monitor was removed, do nothing

    monitor = monitors_db[device_id]

    # Only fire alert if status is still "active"
    # (not paused, not already down)
    if monitor["status"] == "active":

        # Update the status to "down" in our database
        monitors_db[device_id]["status"] = "down"

        # Fire the alert — in production this would send an email
        # or call a webhook. For now we log it clearly.
        alert = {
            "ALERT": f"Device {device_id} is DOWN! No heartbeat received.",
            "time": datetime.utcnow().isoformat(),
            "alert_email": monitor["alert_email"]
        }

        # Print to console (this is what the spec requires)
        print("\n🚨 " + "="*50)
        print(alert)
        print("="*50 + "\n")

# ─────────────────────────────────────────────────────────────────
# ROUTE 1: ROOT — just a health check so we know API is alive
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

    - Receives device id, timeout, and alert email
    - Stores the monitor in our in-memory database
    - Starts a background countdown timer
    - Returns 201 Created with confirmation
    """

    # Check if a monitor with this ID already exists
    # We don't want duplicates
    if monitor.id in monitors_db:
        raise HTTPException(
            status_code=400,
            detail=f"Monitor with id '{monitor.id}' already exists"
        )

    # Validate timeout — must be a positive number
    if monitor.timeout <= 0:
        raise HTTPException(
            status_code=400,
            detail="Timeout must be greater than 0"
        )

    # Store the monitor in our dictionary
    monitors_db[monitor.id] = {
        "id": monitor.id,
        "timeout": monitor.timeout,
        "alert_email": monitor.alert_email,
        "status": "active",           # active | down | paused
        "created_at": datetime.utcnow().isoformat(),
        "last_heartbeat": None        # no heartbeat yet
    }

    # Start the background countdown timer
    # asyncio.create_task() runs it in the background
    # without blocking this response from being sent
    asyncio.create_task(start_countdown(monitor.id, monitor.timeout))

    # Send back confirmation to the client
    return {
        "message": f"Monitor created successfully for device '{monitor.id}'",
        "device_id": monitor.id,
        "timeout": monitor.timeout,
        "status": "active"
    }