import os, requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
CID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

if not CID or not SECRET:
    raise SystemExit("Keys not found. Check the .env file.")

def check(r):
    if not r.ok:
        print("ERROR:", r.status_code, r.text)
        raise SystemExit(1)
    return r.json()

def get_token():
    r = requests.post(f"{BASE}/v1/oauth2/token", auth=(CID, SECRET),
                      data={"grant_type": "client_credentials"})
    return check(r)["access_token"]

def create_order():
    r = requests.post(f"{BASE}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {get_token()}"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}],
            "payment_source": {"paypal": {"experience_context": {
                "user_action": "PAY_NOW",
                "return_url": "https://example.com/return",
                "cancel_url": "https://example.com/cancel"}}}
        })
    d = check(r)
    link = next(l["href"] for l in d["links"] if l["rel"] in ("approve", "payer-action"))
    return d["id"], link

def capture(order_id):
    r = requests.post(f"{BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"})
    return check(r)

def refund(capture_id, amount=None):
    body = {"amount": {"value": amount, "currency_code": "USD"}} if amount else {}
    r = requests.post(f"{BASE}/v2/payments/captures/{capture_id}/refund",
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"},
        json=body)
    return check(r)

order_id, link = create_order()
print("Open this link in an Incognito window and pay as the US buyer:\n", link)
input("Press Enter after you click Complete Purchase...")

result = capture(order_id)
print("Capture status:", result["status"])
capture_id = result["purchase_units"][0]["payments"]["captures"][0]["id"]
print("Capture ID:", capture_id)

input("Press Enter to refund $2.00 (partial refund)...")
print("Refund 1 status:", refund(capture_id, "2.00")["status"])

input("Press Enter to refund the remaining $3.00...")
print("Refund 2 status:", refund(capture_id)["status"])