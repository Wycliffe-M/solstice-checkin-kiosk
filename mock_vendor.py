"""
mock_vendor.py

Simulates Solstice Events Co.'s badge-printer vendor API (PRE-PIVOT version).

In the real world, this would be an external third-party service reached
over the network. For this MVP, we simulate it as a local Flask Blueprint
with an artificial delay, to mimic the fact that a real synchronous HTTP
call to an external printer would take a moment to respond.

This is the exact piece of the system that gets DEPRECATED at the Day 4
pivot, when the vendor kills the synchronous API in favor of an async
message-queue + webhook model.
"""

import time
import random
from flask import Blueprint, request, jsonify

mock_vendor_bp = Blueprint("mock_vendor", __name__)


@mock_vendor_bp.route("/vendor/print", methods=["POST"])
def print_badge():
    """
    Simulates a synchronous call to the vendor's badge-printer API.

    Expects JSON: {"attendee_id": "A001"}

    Blocks for ~1 second to simulate real network/printer latency,
    then returns a success response - mirroring the real vendor's
    synchronous "wait for print job success" behavior described in
    the client handout.
    """
    data = request.get_json()

    if not data or "attendee_id" not in data:
        return jsonify({"error": "Missing attendee_id in request"}), 400

    attendee_id = data["attendee_id"]

    # Simulate real-world printer/network latency (0.8-1.5s)
    time.sleep(random.uniform(0.8, 1.5))

    # For this MVP mock, printing always succeeds.
    # (A more advanced mock could randomly simulate failures if needed.)
    return jsonify({
        "status": "success",
        "attendee_id": attendee_id,
        "message": "Badge printed successfully"
    }), 200