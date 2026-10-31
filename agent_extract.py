"""
Day 2: messy client message -> structured invoice (Claude) -> PayPal invoice.

Setup:
    pip install anthropic requests python-dotenv
    Add ANTHROPIC_API_KEY=... to .env

Run:
    python agent_extract.py
    (paste the client message, then type END on its own line)
"""
import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

from paypal_client import PayPalClient, PayPalError

load_dotenv()

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

INVOICE_TOOL = {
    "name": "draft_invoice",
    "description": "Record the invoice details extracted from a freelancer's conversation with a client.",
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {"type": "string"},
            "client_email": {"type": "string", "description": "Empty string if not mentioned"},
            "currency": {"type": "string", "description": "ISO code, default USD"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                    },
                    "required": ["name", "quantity", "unit_price"],
                },
            },
            "due_in_days": {"type": "integer", "description": "Days until due; default 10"},
            "note": {"type": "string", "description": "Short, polite note to the client"},
            "missing_or_unclear": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Anything required that was missing or ambiguous. Never invent prices or emails.",
            },
        },
        "required": ["client_name", "client_email", "currency", "items", "due_in_days", "note", "missing_or_unclear"],
    },
}

SYSTEM = (
    "You extract billable work from a freelancer's client conversation. "
    "Only include amounts actually agreed in the text. If a price, quantity, or email is missing, "
    "leave it out or empty and list it in missing_or_unclear. Never guess money. "
    "ALWAYS respond by calling the draft_invoice tool exactly once, even if the message "
    "contains nothing billable (then return an empty items list)."
)


def extract(message: str) -> dict:
    client = Anthropic()
    messages = [{"role": "user", "content": f"Client conversation:\n\n{message}"}]
    for _ in range(2):  # one retry if the model answers in plain text
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=[INVOICE_TOOL],
            tool_choice={"type": "auto"},
            messages=messages,
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "draft_invoice":
                return block.input
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": "Call the draft_invoice tool now. If nothing is billable, use an empty items list and explain in missing_or_unclear."},
        ]
    raise RuntimeError("Model did not return an invoice draft")


def read_message() -> str:
    print("Paste the client message. Type END on its own line when done:")
    lines = []
    for line in sys.stdin:
        if line.strip() == "END":
            break
        lines.append(line)
    return "".join(lines).strip()


def main():
    message = read_message()
    if not message:
        sys.exit("No message given.")

    draft = extract(message)
    print("\n--- Draft invoice ---")
    print(json.dumps(draft, indent=2))

    if draft["missing_or_unclear"]:
        print("\n[!] Needs your input:", "; ".join(draft["missing_or_unclear"]))
    if not draft["items"]:
        sys.exit("No billable items found. Not creating an invoice.")

    email = draft["client_email"] or input("\nClient email (for testing use your sandbox personal email): ").strip()
    if input(f"\nCreate and send this invoice to {email}? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled. Nothing was sent.")

    try:
        pp = PayPalClient()
        inv_id = pp.create_invoice(
            recipient_email=email,
            items=draft["items"],
            currency=draft["currency"] or "USD",
            note=draft["note"],
            due_in_days=draft["due_in_days"],
        )
        pp.send_invoice(inv_id)
    except PayPalError as e:
        sys.exit(f"PayPal error: {e}")
    print(f"\n[OK] Invoice {inv_id} created and sent.")


if __name__ == "__main__":
    main()