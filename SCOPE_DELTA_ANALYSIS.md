# Scope Delta Analysis — Solstice Events Check-In Kiosk

**Learner:** Wycliffe-M
**Sprint:** Meridian Pivot — Day 4/5
**Baseline tags:** `pre-pivot-v1` (original synchronous spec) → `post-pivot-v1` (async pivot spec)
**Repo:** solstice-checkin-kiosk

---

## 1. Context

The original spec required the kiosk to call Solstice Events Co.'s badge-printer
vendor **synchronously**: the app would call the vendor's REST API, wait for the
print job's success response, and only then show "Checked In" on screen.

On Day 4, the client (instructor) announced — with no extension and no
negotiating back to the original spec — that the vendor is deprecating this
synchronous API. The system had to be rebuilt around an **asynchronous** model:
publish a print request to the vendor's message queue, expose a webhook to
receive a completion callback, and reflect a **pending** state in the UI until
that callback confirms the job is done. Duplicate-scan protection had to keep
working even though confirmations could now arrive out of order.

This document records exactly what changed to meet that new requirement.

---

## 2. What Was Dropped

| Item | Why it was dropped |
|---|---|
| `mock_vendor.py` (synchronous `/vendor/print` route) | Simulated the vendor's now-deprecated synchronous print API. No longer valid under the new spec — deleted outright rather than left running in parallel, per the sprint's non-negotiable rule against obsolete code coexisting with the new implementation. Preserved in git history via the `pre-pivot-v1` tag for reference/comparison. |
| Direct `requests.post()` call to the vendor from `/checkin` | The check-in route can no longer call the printer directly and block waiting for a response — that blocking synchronous call was the exact mechanism the vendor killed. |
| Binary `checked_in: True/False` attendee status | Replaced because a binary flag can't represent the new "in-flight, unconfirmed" state that async processing introduces. |

---

## 3. What Was Modified

| Item | Before (pre-pivot) | After (post-pivot) |
|---|---|---|
| Attendee status model | `checked_in: bool` | `status: "not_checked_in" \| "pending" \| "checked_in"` — a three-state model needed to represent the gap between "job submitted" and "job confirmed done" |
| `/checkin` route | Called the vendor synchronously, waited (~1s simulated delay), then marked `checked_in = True` on success | Publishes a job to the mock queue and returns **immediately** with `status = "pending"`. Never itself sets `checked_in` |
| Duplicate-scan guard | Checked a single boolean (`if attendee["checked_in"]`) | Checks whether status is `"pending"` **or** `"checked_in"` — must block duplicates during the in-flight window, not just after confirmation |
| UI (`kiosk.html`) | Rendered "Checked In" / "Not checked in" only, updated on page reload | Adds a "Pending (waiting for printer)..." state; added a `/status` polling endpoint and JS so the page updates live without a manual refresh once the webhook confirms |

---

## 4. What Was Added

| Item | Purpose |
|---|---|
| `mock_queue.py` | Simulates publishing a print job to an async message queue. Returns a `job_id` immediately without blocking; uses a background timer to simulate the vendor's own processing delay before it calls back |
| `POST /webhook/print-complete` | New endpoint that receives the vendor's asynchronous confirmation. This — not `/checkin` — is now the only place that flips an attendee to `"checked_in"` |
| Job-level duplicate guard (`job["processed"]`) | Protects against a webhook confirmation arriving more than once, or arriving out of order, by tracking each print job independently via a unique `job_id` rather than relying on request order |
| `GET /status` | Lightweight JSON polling endpoint so the kiosk UI can detect status changes (e.g. pending → checked_in) without the user manually refreshing |

---

## 5. Regression Check

Confirms the pivot did not silently break anything the original spec required:

- ✅ **≥3 test attendees handled** — A001, A002, A003 all successfully move through the full flow (verified in browser + terminal logs)
- ✅ **Duplicate-scan protection still holds** — verified at two points:
  - **Scan-time guard:** an attendee already `pending` or `checked_in` cannot trigger a second print job (tested via rapid repeat scans and automated `curl` sequence)
  - **Webhook-time guard:** a webhook confirmation for an already-`processed` job is safely ignored, protecting against duplicate or out-of-order callback delivery
- ✅ **"Checked In" only shown after real confirmation** — under the new model, confirmation comes from the webhook, not from the scan itself; this preserves the spirit of the original rule ("shown on screen only once printing has actually succeeded"), just via an async signal instead of a synchronous response
- ⚠️ **Known limitation carried over:** attendee state is still in-memory only (no persistent database) in both versions — acceptable for MVP scope, flagged as a future improvement in both journal entries

---

## 6. Trade-offs & Backlog

**Trade-offs accepted for MVP scope under the 48-hour constraint:**
- Used Python's `threading.Timer` to simulate the vendor's async callback rather than integrating a real message broker (e.g. RabbitMQ) — sufficient to prove the architecture works without adding infrastructure complexity under deadline pressure.
- No retry/backoff logic if the simulated webhook call fails to reach `/webhook/print-complete` — acceptable for MVP; flagged below for future work.
- No signature verification (HMAC) on the incoming webhook payload — acceptable for a local MVP simulation; would be required before any real production use.

**Reprioritized backlog (not required for this sprint, noted for future iterations):**
1. Add webhook signature verification for security.
2. Add retry/backoff if the vendor's callback fails to arrive.
3. Replace in-memory attendee/job storage with a persistent database.
4. Replace polling (`/status` every 1.5s) with a more efficient push mechanism (e.g. WebSockets or Server-Sent Events) for the kiosk UI.

---

## 7. Evidence

- Pre-pivot implementation: git tag `pre-pivot-v1` (commit `2814c52`)
- Post-pivot implementation: git tag `post-pivot-v1` (commit `ddbe020`)
- Full diff of the refactor: `git diff pre-pivot-v1 post-pivot-v1`

### Diff summary (`git diff --stat pre-pivot-v1 post-pivot-v1`)

app.py | 151 +++++++++++++++++++++++++++++++++------------------
mock_queue.py | 74 +++++++++++++++++++++++++
mock_vendor.py | 51 -----------------
templates/kiosk.html | 44 +++++++++++++--
4 files changed, 210 insertions(+), 110 deletions(-)


`mock_vendor.py` shows as fully deleted (51 lines removed, 0 added) — confirming
the obsolete synchronous code was actually removed, not left running alongside
the new implementation. `mock_queue.py` is a wholly new file (74 lines added,
0 removed) — the new async publishing mechanism. `app.py` shows the heaviest
churn (151 lines changed) since the core check-in logic itself needed the
real refactor, not just a config change.

### Excerpt: the duplicate-scan guard, before vs after

This is the clearest single proof that the refactor was structural, not
cosmetic — the guard condition itself had to change shape, and the blocking
vendor call was replaced with a non-blocking queue publish:

```diff
     attendee = attendees[attendee_id]

-    # --- Duplicate-scan protection ---
-    if attendee["checked_in"]:
+    # --- Duplicate-scan protection (scan-time guard) ---
+    if attendee["status"] in ("pending", "checked_in"):
         flash(
-            f"{attendee['name']} ({attendee_id}) is already checked in. "
-            f"No badge will be printed again.",
+            f"{attendee['name']} ({attendee_id}) already has a print job "
+            f"in progress or completed. No new badge will be queued.",
             "warning"
         )
         return redirect(url_for("kiosk_home"))

-    # --- Not yet checked in: call the vendor's print API synchronously ---
-    try:
-        response = requests.post(
-            VENDOR_PRINT_URL,
-            json={"attendee_id": attendee_id},
-            timeout=5  # sensible timeout for a synchronous call
-        )
-    except requests.exceptions.RequestException as e:
-        flash(f"Could not reach printer service: {e}", "error")
-        return redirect(url_for("kiosk_home"))
-
-    if response.status_code == 200 and response.json().get("status") == "success":
-        # Only NOW, after print success, do we mark them as checked in.
-        attendee["checked_in"] = True
-        flash(f"{attendee['name']} ({attendee_id}) - Checked In! Badge printed.", "success")
-    else:
-        flash(f"Print failed for {attendee['name']} ({attendee_id}). Please try again.", "error")
+    # --- Not yet checked in: publish to the queue and return immediately ---
+    job_id = publish_print_job(attendee_id)
+    attendee["status"] = "pending"
+    attendee["job_id"] = job_id
```

Note the pre-pivot version's `requests.post(...)` call **blocked** on the
vendor's response before deciding anything. The post-pivot version never
calls the vendor directly at all — it publishes a job and returns
immediately, deferring the actual "checked in" decision entirely to the
`/webhook/print-complete` route (see Section 4).