"""
mock_queue.py

Simulates the vendor's asynchronous message-queue based print system
(POST-PIVOT version).

In the real world, publishing here would mean sending a message to an
actual broker (e.g. RabbitMQ, AWS SQS, etc.) that the vendor's own
system consumes independently, on its own schedule. We simulate that
using a background timer that "completes" the job after a short delay
and then calls back into our own webhook endpoint - mirroring how a
real vendor would notify us once printing is done.

This replaces the synchronous /vendor/print call used in the pre-pivot
version (see the 'pre-pivot-v1' git tag for that implementation).
"""

import threading
import random
import uuid
import requests

# In-memory store of print jobs: job_id -> {"attendee_id": ..., "status": ...}
# For this MVP, an in-memory dict stands in for a real queue/broker.
print_jobs = {}

# Where our own webhook endpoint lives, so the "vendor" can call us back.
WEBHOOK_URL = "http://127.0.0.1:5000/webhook/print-complete"


def publish_print_job(attendee_id):
    """
    Simulates publishing a print request onto the vendor's message queue.

    Returns immediately with a job_id - it does NOT wait for the print
    to finish. The actual "printing" and webhook callback happen later,
    asynchronously, via a background timer.
    """
    job_id = str(uuid.uuid4())
    print_jobs[job_id] = {"attendee_id": attendee_id, "status": "queued"}

    # Simulate the vendor's own processing time before it calls our webhook.
    # Using a background Timer so this function can return immediately,
    # just like a real queue publish would not block on the consumer.
    delay_seconds = random.uniform(2, 4)
    timer = threading.Timer(delay_seconds, _simulate_vendor_completion, args=[job_id])
    timer.daemon = True
    timer.start()

    return job_id


def _simulate_vendor_completion(job_id):
    """
    Simulates the vendor's system finishing the print job and calling
    OUR webhook endpoint to report completion - exactly like a real
    third-party vendor would push a callback once done.
    """
    job = print_jobs.get(job_id)
    if not job:
        return  # job was somehow removed - nothing to do

    job["status"] = "completed"

    try:
        requests.post(
            WEBHOOK_URL,
            json={"job_id": job_id, "attendee_id": job["attendee_id"], "status": "success"},
            timeout=5
        )
    except requests.exceptions.RequestException:
        # In a real system we'd log/retry here. For this MVP, we accept
        # the failure silently - the attendee would simply stay "pending".
        pass