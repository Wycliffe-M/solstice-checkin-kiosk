"""
app.py

Solstice Events Co. - Check-In Kiosk (PRE-PIVOT version, original spec).

Flow:
  1. Staff "scans" an attendee's QR code (simulated via a simple web form
     where the attendee ID is entered/selected).
  2. The app calls the vendor's badge-printer API SYNCHRONOUSLY and waits
     for the print job's success response.
  3. "Checked In" is shown on screen only once printing has succeeded.
  4. Duplicate scans of an already-checked-in attendee must NOT trigger
     a second print job.

This version will be refactored at the Day 4 pivot to use an async
message-queue + webhook model instead of the synchronous vendor call.
"""

import requests
from flask import Flask, request, render_template, redirect, url_for, flash

from mock_vendor import mock_vendor_bp

app = Flask(__name__)
app.secret_key = "dev-only-secret-key"  # fine for local MVP, not for production

# Register the mock vendor endpoint (simulates the external printer API)
app.register_blueprint(mock_vendor_bp)

# Base URL where our own mock vendor endpoint lives.
# In a real system this would be the vendor's actual API base URL.
VENDOR_PRINT_URL = "http://127.0.0.1:5000/vendor/print"

# --- In-memory attendee "database" ---------------------------------------
# For this MVP, a simple dict is enough. Keys are attendee IDs.
attendees = {
    "A001": {"name": "Wanjiku Mwangi", "checked_in": False},
    "A002": {"name": "David Otieno", "checked_in": False},
    "A003": {"name": "Fatuma Hassan", "checked_in": False},
}


@app.route("/", methods=["GET"])
def kiosk_home():
    """Render the kiosk screen: list of attendees + scan form."""
    return render_template("kiosk.html", attendees=attendees)


@app.route("/checkin", methods=["POST"])
def checkin():
    """
    Handles a simulated QR scan for a given attendee.

    - If the attendee is already checked in: reject, do NOT call the
      printer again (duplicate-scan protection).
    - If not yet checked in: call the vendor's print API synchronously,
      wait for success, then mark as checked in and show "Checked In".
    """
    attendee_id = request.form.get("attendee_id")

    if not attendee_id or attendee_id not in attendees:
        flash(f"Unknown attendee ID: {attendee_id}", "error")
        return redirect(url_for("kiosk_home"))

    attendee = attendees[attendee_id]

    # --- Duplicate-scan protection ---
    if attendee["checked_in"]:
        flash(
            f"{attendee['name']} ({attendee_id}) is already checked in. "
            f"No badge will be printed again.",
            "warning"
        )
        return redirect(url_for("kiosk_home"))

    # --- Not yet checked in: call the vendor's print API synchronously ---
    try:
        response = requests.post(
            VENDOR_PRINT_URL,
            json={"attendee_id": attendee_id},
            timeout=5  # sensible timeout for a synchronous call
        )
    except requests.exceptions.RequestException as e:
        flash(f"Could not reach printer service: {e}", "error")
        return redirect(url_for("kiosk_home"))

    if response.status_code == 200 and response.json().get("status") == "success":
        # Only NOW, after print success, do we mark them as checked in.
        attendee["checked_in"] = True
        flash(f"{attendee['name']} ({attendee_id}) - Checked In! Badge printed.", "success")
    else:
        flash(f"Print failed for {attendee['name']} ({attendee_id}). Please try again.", "error")

    return redirect(url_for("kiosk_home"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)