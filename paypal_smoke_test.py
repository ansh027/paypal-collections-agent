"""
PayPal sandbox smoke test: OAuth token -> create invoice -> send invoice.

Setup (in your project folder):
    pip install requests python-dotenv

Create a file named .env (never commit it to git) containing:
    PAYPAL_CLIENT_ID=your_sandbox_client_id
    PAYPAL_CLIENT_SECRET=your_sandbox_secret
    BUYER_EMAIL=your_sandbox_personal_account_email

Run:
    python paypal_smoke_test.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
BUYER_EMAIL = os.getenv("BUYER_EMAIL")

if not all([CLIENT_ID, SECRET, BUYER_EMAIL]):
    sys.exit("Missing values in .env (PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, BUYER_EMAIL)")


def fail(step, resp):
    print(f"\n[FAIL] {step}: HTTP {resp.status_code}")
    print(resp.text)
    sys.exit(1)


# 1. OAuth token
r = requests.post(
    f"{BASE}/v1/oauth2/token",
    auth=(CLIENT_ID, SECRET),
    data={"grant_type": "client_credentials"},
    timeout=30,
)
if r.status_code != 200:
    fail("Get access token", r)
token = r.json()["access_token"]
print("[OK] Access token received")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# 2. Create a draft invoice
invoice = {
    "detail": {
        "currency_code": "USD",
        "note": "Hackathon smoke test invoice",
        "payment_term": {"term_type": "NET_10"},
    },
    "primary_recipients": [
        {"billing_info": {"email_address": BUYER_EMAIL}}
    ],
    "items": [
        {
            "name": "Logo design",
            "quantity": "1",
            "unit_amount": {"currency_code": "USD", "value": "150.00"},
        }
    ],
}
r = requests.post(f"{BASE}/v2/invoicing/invoices", headers=headers, json=invoice, timeout=30)
if r.status_code not in (200, 201):
    fail("Create invoice", r)
data = r.json()
invoice_id = data.get("id") or data["href"].rstrip("/").split("/")[-1]
print(f"[OK] Draft invoice created: {invoice_id}")

# 3. Send it
r = requests.post(
    f"{BASE}/v2/invoicing/invoices/{invoice_id}/send",
    headers=headers,
    json={"send_to_invoicer": True},
    timeout=30,
)
if r.status_code not in (200, 202):
    fail("Send invoice", r)
print("[OK] Invoice sent")
print(f"\nCheck it: log into https://www.sandbox.paypal.com as {BUYER_EMAIL} and pay it.")
print("If that works, the core of the project is unblocked.")
