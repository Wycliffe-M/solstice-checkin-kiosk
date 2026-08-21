"""
app.py

Solstice Events Co. - Check-In Kiosk (POST-PIVOT version, async spec).

REFACTOR NOTE (Day 4 pivot):
The vendor's synchronous badge-printer API has been deprecated. The old
version of this file called the vendor directly with requests.post() and
waited for a success response before showing "Checked In" (see the
'pre-pivot-v1' git tag for that implementation - it has been fully
removed from this version, not left running in parallel).

New flow:
  1. Staff "scans" an attendee's QR code.
  2. Instead of calling the vendor directly, the app PUBLISHES a print
     job onto a (simulated) message queue and returns immediately.
  3. The attendee is shown as "Pending" - NOT "Checked In" - until the
     vendor's webhook callback confirms the print actually completed.
  4. When the webhook fires, the attendee flips to "Checked In".
  5. Duplicate-scan protection must hold even though confirmations can
     arrive out of order - guarded at BOTH scan-time (no duplicate job
     creation) and webhook-time (no duplicate processing of a
     confirmation).
"""

from flask import Flask, request, render_template, redirect, url_for, flash, jsonify

from mock_queue import publish_print_job, print_jobs

app = Flask(__name__)
app.secret_key = "dev-only-secret-key"  # fine for local MVP, not for production

# --- In-memory attendee "database" ---------------------------------------
# Status can be: "not_checked_in", "pending", "checked_in"
attendees = {
    "A001": {"name": "Wanjiku Mwangi", "status": "not_checked_in"},
    "A002": {"name": "David Otieno", "status": "not_checked_in"},
    "A003": {"name": "Fatuma Hassan", "status": "not_checked_in"},
}


@app.route("/", methods=["GET"])
def kiosk_home():
    """Render the kiosk screen: list of attendees + scan form."""
    return render_template("kiosk.html", attendees=attendees)


@app.route("/checkin", methods=["POST"])
def checkin():
    """
    Handles a simulated QR scan for a given attendee (POST-PIVOT).

    - If already "pending" or "checked_in": reject immediately, do NOT
      publish a new print job (prevents duplicate jobs from a duplicate
      scan, even before any webhook has confirmed anything).
    - If "not_checked_in": publish a print job to the mock queue and
      mark the attendee as "pending". The UI will NOT say "Checked In"
      yet - that only happens once the webhook confirms completion.
    """
    attendee_id = request.form.get("attendee_id")

    if not attendee_id or attendee_id not in attendees:
        flash(f"Unknown attendee ID: {attendee_id}", "error")
        return redirect(url_for("kiosk_home"))

    attendee = attendees[attendee_id]

    # --- Duplicate-scan protection (scan-time guard) ---
    if attendee["status"] in ("pending", "checked_in"):
        flash(
            f"{attendee['name']} ({attendee_id}) already has a print job "
            f"in progress or completed. No new badge will be queued.",
            "warning"
        )
        return redirect(url_for("kiosk_home"))

    # --- Not yet checked in: publish to the queue and return immediately ---
    job_id = publish_print_job(attendee_id)
    attendee["status"] = "pending"
    attendee["job_id"] = job_id

    flash(
        f"{attendee['name']} ({attendee_id}) - Print job queued. "
        f"Waiting for printer confirmation...",
        "info"
    )
    return redirect(url_for("kiosk_home"))


@app.route("/webhook/print-complete", methods=["POST"])
def webhook_print_complete():
    """
    Receives the vendor's asynchronous confirmation that a print job
    has completed. This is what finally flips an attendee to
    "Checked In" - never the /checkin route itself.

    Guards against out-of-order or duplicate webhook deliveries using
    the job_id: a job already marked "processed" is ignored safely.
    """
    data = request.get_json()

    if not data or "job_id" not in data or "attendee_id" not in data:
        return jsonify({"error": "Malformed webhook payload"}), 400

    job_id = data["job_id"]
    attendee_id = data["attendee_id"]

    job = print_jobs.get(job_id)

    # --- Webhook-time duplicate/out-of-order guard ---
    if not job:
        # Unknown job - ignore safely (could be a stale/duplicate delivery)
        return jsonify({"status": "ignored", "reason": "unknown job_id"}), 200

    if job.get("processed"):
        # Already handled this confirmation once - ignore duplicates
        return jsonify({"status": "ignored", "reason": "already processed"}), 200

    job["processed"] = True

    attendee = attendees.get(attendee_id)
    if attendee and attendee["status"] == "pending":
        attendee["status"] = "checked_in"

    return jsonify({"status": "acknowledged"}), 200


@app.route("/status", methods=["GET"])
def status_poll():
    """
    Lightweight JSON endpoint so the kiosk page can poll for status
    updates without a full page reload (used by the auto-refresh
    script in kiosk.html).
    """
    return jsonify({
        aid: info["status"] for aid, info in attendees.items()
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)