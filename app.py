"""
Collections Agent web app (FastAPI).

Local run:
    pip install -r requirements.txt
    uvicorn app:app --reload
    open http://127.0.0.1:8000

PayPal is the source of truth for invoices, so nothing is lost when Render
restarts. Webhook events are kept in memory as a live activity feed.
"""
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent_extract import extract
from paypal_client import PayPalClient, PayPalError

load_dotenv()

app = FastAPI(title="Collections Agent")
pp = PayPalClient()

WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")
# Set to "false" only when testing with PayPal's Webhook Simulator (its events can't be verified).
VERIFY_WEBHOOKS = os.getenv("VERIFY_WEBHOOKS", "true").lower() == "true"

EVENTS = deque(maxlen=100)  # live activity feed


def log_event(kind, message, invoice_id=None):
    EVENTS.appendleft({
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "message": message,
        "invoice_id": invoice_id,
    })


# ---------- API models ----------

class DraftRequest(BaseModel):
    message: str


class Item(BaseModel):
    name: str
    quantity: float
    unit_price: float


class SendRequest(BaseModel):
    client_email: str
    items: list[Item]
    currency: str = "USD"
    note: str = ""
    due_in_days: int = 10


# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
def index():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/draft")
def draft(req: DraftRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message is empty")
    try:
        result = extract(req.message)
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {e}")
    log_event("draft", f"AI drafted invoice for {result.get('client_name') or 'unknown client'}")
    return result


@app.post("/api/send")
def send(req: SendRequest):
    if not req.items:
        raise HTTPException(400, "No items to bill")
    if "@" not in req.client_email:
        raise HTTPException(400, "Valid client email required")
    try:
        inv_id = pp.create_invoice(
            recipient_email=req.client_email,
            items=[i.model_dump() for i in req.items],
            currency=req.currency or "USD",
            note=req.note,
            due_in_days=req.due_in_days,
        )
        pp.send_invoice(inv_id)
    except PayPalError as e:
        raise HTTPException(502, str(e))
    total = sum(i.quantity * i.unit_price for i in req.items)
    log_event("sent", f"Invoice sent to {req.client_email} for {total:.2f} {req.currency}", inv_id)
    return {"invoice_id": inv_id}


@app.get("/api/invoices")
def invoices():
    try:
        raw = pp.list_invoices()
    except PayPalError as e:
        raise HTTPException(502, str(e))
    rows = []
    for inv in raw:
        detail = inv.get("detail", {})
        recipients = inv.get("primary_recipients") or [{}]
        email = recipients[0].get("billing_info", {}).get("email_address", "")
        rows.append({
            "id": inv.get("id"),
            "number": detail.get("invoice_number"),
            "client": email,
            "amount": float(inv.get("amount", {}).get("value", 0) or 0),
            "currency": inv.get("amount", {}).get("currency_code", "USD"),
            "status": inv.get("status"),
            "due_date": detail.get("payment_term", {}).get("due_date"),
            "invoice_date": detail.get("invoice_date"),
        })
    return rows


@app.get("/api/events")
def events():
    return list(EVENTS)


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    event = await request.json()
    if VERIFY_WEBHOOKS:
        if not WEBHOOK_ID:
            raise HTTPException(500, "PAYPAL_WEBHOOK_ID not set")
        headers = {k.lower(): v for k, v in request.headers.items()}
        if not pp.verify_webhook(headers, event, WEBHOOK_ID):
            log_event("rejected", "Webhook failed signature check")
            raise HTTPException(400, "Invalid signature")

    etype = event.get("event_type", "")
    resource = event.get("resource", {})
    invoice = resource.get("invoice", resource)
    inv_id = invoice.get("id")

    if etype == "INVOICING.INVOICE.PAID":
        log_event("paid", f"Payment received for invoice {inv_id}", inv_id)
    elif etype == "INVOICING.INVOICE.CANCELLED":
        log_event("cancelled", f"Invoice {inv_id} cancelled", inv_id)
    elif etype == "INVOICING.INVOICE.REFUNDED":
        log_event("refunded", f"Invoice {inv_id} refunded", inv_id)
    else:
        log_event("webhook", f"{etype} received", inv_id)
    return {"received": True}
