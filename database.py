# ─────────────────────────────────────────────────────────────────
# database.py — In-Memory Storage
#
# SEPARATION OF CONCERNS:
# This file owns all data storage for the application.
# If we ever swap to PostgreSQL or Redis, we only change THIS file.
# Nothing else in the project needs to know HOW data is stored —
# only that it can be accessed from here.
# ─────────────────────────────────────────────────────────────────

# monitors_db stores all registered device monitors
# Structure:
#   Key   → device id (string) e.g. "device-123"
#   Value → dict with id, timeout, status, history etc.
#
# In production: this would be a PostgreSQL table called "monitors"
# with columns: id, timeout, alert_email, status, created_at, last_heartbeat
monitors_db = {}


# active_tasks stores the running asyncio background timer for each device
# Structure:
#   Key   → device id (string) e.g. "device-123"
#   Value → asyncio.Task object (the running countdown)
#
# We need this so we can CANCEL the timer when a heartbeat arrives.
# Without storing the reference, we'd have no way to stop a running timer.
#
# In production: Redis would handle this — it has built-in TTL (time-to-live)
# support which is perfect for countdown timers
active_tasks = {}