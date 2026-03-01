# ─────────────────────────────────────────────────────────────────
# models.py — Data Models (Pydantic Schemas)
#
# WHAT IS PYDANTIC?
# Pydantic is a data validation library. When a device sends JSON
# to our API, Pydantic automatically:
#   1. Checks that all required fields are present
#   2. Checks that each field is the correct type
#   3. Returns a clear error message if anything is wrong
#
# This means invalid data NEVER reaches our business logic.
# It's rejected at the door.
#
# SEPARATION OF CONCERNS:
# All data shapes live here. If the API contract changes
# (e.g. adding a new field), we only update THIS file.
# ─────────────────────────────────────────────────────────────────

from pydantic import BaseModel
# BaseModel is the foundation class for all Pydantic models
# Any class that extends BaseModel gets automatic validation for free


class MonitorCreate(BaseModel):
    """
    Defines the shape of the request body for POST /monitors

    When a device sends this JSON:
    {
        "id": "device-123",
        "timeout": 60,
        "alert_email": "admin@critmon.com"
    }

    Pydantic will:
    - Confirm "id" is a string
    - Confirm "timeout" is an integer
    - Confirm "alert_email" is a string
    - Reject the request if any field is missing or wrong type
    """

    id: str           # unique identifier for the device
    timeout: int      # how many seconds before the alert fires
    alert_email: str  # email address to notify when device goes down


class MonitorResponse(BaseModel):
    """
    Defines the shape of the response we send BACK to the client
    after successfully creating a monitor.

    Using a response model makes our API contract explicit —
    the client always knows exactly what fields to expect back.
    """

    message: str      # human readable confirmation
    device_id: str    # echoes back the device id
    timeout: int      # echoes back the timeout
    status: str       # will always be "active" on creation