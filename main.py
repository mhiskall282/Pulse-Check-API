# ─────────────────────────────────────────────────────────────────
# main.py — Application Entry Point
#
# This file does ONE thing: create the FastAPI app and
# register all the routes.
#
# WHY SO SMALL?
# This is intentional. In a well-structured backend project,
# main.py should be the "front door" — it just wires things together.
# All business logic lives in the other modules.
#
# This follows the SEPARATION OF CONCERNS principle:
#   main.py      → app setup and routing
#   models.py    → data validation schemas
#   database.py  → in-memory storage
#   alerts.py    → logging and notifications
#   timer.py     → background countdown logic
#   routes/      → all API endpoint handlers
#
# If this were a larger application, we'd have more route files:
#   routes/users.py, routes/devices.py, routes/reports.py etc.
# ─────────────────────────────────────────────────────────────────

from fastapi import FastAPI
# FastAPI → the web framework that powers our API

from routes.monitors import router as monitors_router
# Import our monitors router from the routes package
# "as monitors_router" just gives it a clear name

import logging
# Set up logging for the main module
logger = logging.getLogger("main")

# ─────────────────────────────────────────────────────────────────
# CREATE THE APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pulse Check API",
    description="""
    ## Dead Man's Switch — Device Heartbeat Monitoring System

    A backend REST API that monitors remote devices using stateful countdown timers.
    If a device stops sending heartbeats before its timer expires, the system
    automatically fires an alert.

    ### Key Features
    - **Register** a device monitor with a custom timeout
    - **Heartbeat** endpoint to reset the countdown timer
    - **Pause** monitoring during maintenance windows
    - **History** log for full heartbeat audit trail
    - **Auto-alert** when a device goes silent
    """,
    version="1.0.0",
    contact={
        "name": "John Okyere",
        "url": "https://github.com/mhiskall282"
    }
)

# ─────────────────────────────────────────────────────────────────
# REGISTER ROUTES
# include_router() attaches all endpoints from monitors_router
# The prefix "/monitors" is already set inside the router itself
# ─────────────────────────────────────────────────────────────────

app.include_router(monitors_router)


# ─────────────────────────────────────────────────────────────────
# ROOT ENDPOINT — Health check
# Simple confirmation that the API is live
# ─────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    """
    Health check endpoint.
    Returns a simple confirmation that the API is running.
    Load balancers and monitoring tools ping this to verify uptime.
    """
    logger.info("Health check hit")
    return {
        "message": "Pulse Check API is running",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }