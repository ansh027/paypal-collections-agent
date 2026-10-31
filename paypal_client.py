"""Thin PayPal sandbox client for the collections agent."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"


class PayPalError(Exception):
    pass


class PayPalClient:
    def __init__(self):
        self.client_id = os.getenv("PAYPAL_CLIENT_ID")
        self.secret = os.getenv("PAYPAL_CLIENT_SECRET")
        if not self.client_id or not self.secret:
            raise PayPalError("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing from .env")
        self._token = None

    def _headers(self):
        if not self._token:
            r = requests.post(
                f"{BASE}/v1/oauth2/token",
                auth=(self.client_id, self.secret),
                data={"grant_type": "client_credentials"},
                timeout=30,
            )
            if r.status_code != 200:
                raise PayPalError(f"Token failed: {r.status_code} {r.text}")
            self._token = r.json()["access_token"]
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def create_invoice(self, recipient_email, items, currency="USD", note="", due_in_days=10):
        """items: list of {"name": str, "quantity": number, "unit_price": number}"""
        term = f"NET_{due_in_days}" if due_in_days in (10, 15, 30, 45, 60, 90) else "NET_10"
        body = {
            "detail": {
                "currency_code": currency,
                "note": note,
                "payment_term": {"term_type": term},
            },
            "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
            "items": [
                {
                    "name": it["name"][:200],
                    "quantity": str(it["quantity"]),
                    "unit_amount": {"currency_code": currency, "value": f"{float(it['unit_price']):.2f}"},
                }
                for it in items
            ],
        }
        r = requests.post(f"{BASE}/v2/invoicing/invoices", headers=self._headers(), json=body, timeout=30)
        if r.status_code not in (200, 201):
            raise PayPalError(f"Create invoice failed: {r.status_code} {r.text}")
        data = r.json()
        return data.get("id") or data["href"].rstrip("/").split("/")[-1]

    def send_invoice(self, invoice_id):
        r = requests.post(
            f"{BASE}/v2/invoicing/invoices/{invoice_id}/send",
            headers=self._headers(),
            json={"send_to_invoicer": True},
            timeout=30,
        )
        if r.status_code not in (200, 202):
            raise PayPalError(f"Send invoice failed: {r.status_code} {r.text}")
        return True

    def get_invoice(self, invoice_id):
        r = requests.get(f"{BASE}/v2/invoicing/invoices/{invoice_id}", headers=self._headers(), timeout=30)
        if r.status_code != 200:
            raise PayPalError(f"Get invoice failed: {r.status_code} {r.text}")
        return r.json()

    def list_invoices(self, page_size=50):
        r = requests.get(
            f"{BASE}/v2/invoicing/invoices",
            headers=self._headers(),
            params={"page_size": page_size, "total_required": "true"},
            timeout=30,
        )
        if r.status_code != 200:
            raise PayPalError(f"List invoices failed: {r.status_code} {r.text}")
        return r.json().get("items", [])
