# ─────────────────────────────────────────────────────────────────
# timer.py — Background Countdown Timer Logic
#
# SEPARATION OF CONCERNS:
# All timer logic lives here. This file answers the question:
# "What happens when we start counting down for a device?"
#
# WHY ASYNCIO?
# We need timers that run in the BACKGROUND while the API
# continues serving other requests.
#
# Option 1 — Threading: Create a new OS thread per timer.
#   Problem: threads are expensive. 1000 devices = 1000 threads.
#
# Option 2 — asyncio (what we use): Single-threaded event loop.
#   asyncio.sleep() pauses ONLY this coroutine, not the server.
#   The event loop switches between coroutines efficiently.
#   Much lighter than threads. Used by Discord, FastAPI, aiohttp.
# ─────────────────────────────────────────────────────────────────

import asyncio
# Python's built-in async library
# Powers the entire concurrent timer system

import logging
from datetime import datetime

# Import our storage and alert systems
from database import monitors_db, active_tasks
from alerts import fire_alert

# Named logger for this module
logger = logging.getLogger("timer")


async def start_countdown(device_id: str, timeout: int):
    """
    Runs a countdown in the background for a specific device.

    HOW IT WORKS:
    1. await asyncio.sleep(timeout) — pauses THIS coroutine for
       `timeout` seconds without blocking anything else
    2. If a heartbeat arrives during the sleep:
       - The task is cancelled via active_tasks[device_id].cancel()
       - CancelledError is raised inside asyncio.sleep()
       - Our except block catches it and returns silently
       - No alert fires — this is the HAPPY PATH
    3. If sleep completes (no heartbeat received):
       - We check if monitor still exists and is still active
       - We fire the alert — this is the FAILURE PATH

    THE TRY/EXCEPT IS CRITICAL:
    Without it, every successful heartbeat would print an ugly
    "Task was cancelled" error in the terminal. The except block
    makes cancellation silent and clean — which is correct behaviour
    because cancellation means the device IS alive and working.
    """

    try:
        # Pause this coroutine for the full timeout duration
        # e.g. await asyncio.sleep(60) waits 60 seconds
        # During this time the server handles other requests normally
        await asyncio.sleep(timeout)

    except asyncio.CancelledError:
        # A heartbeat arrived and cancelled this timer
        # This is NORMAL and EXPECTED — not an error
        # We return silently. No alert. Device is alive.
        logger.info(f"⏱️  Timer cancelled for '{device_id}' — heartbeat received")
        return

    # ── TIMER EXPIRED — no heartbeat received ─────────────────────

    # Safety check: monitor might have been deleted while we slept
    if device_id not in monitors_db:
        return

    monitor = monitors_db[device_id]

    # Only fire alert if status is still "active"
    # If it's "paused" or already "down", do nothing
    if monitor["status"] == "active":

        # Mark the device as down in our database
        monitors_db[device_id]["status"] = "down"

        # Get the exact time the alert fired
        timestamp = datetime.utcnow().isoformat()

        logger.warning(f"⚠️  No heartbeat received for '{device_id}' after {timeout}s")

        # Fire the alert — logs to console + simulates email
        # Imported from alerts.py (single responsibility)
        fire_alert(device_id, monitor["alert_email"], timestamp)