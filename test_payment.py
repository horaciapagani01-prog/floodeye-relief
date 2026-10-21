import os, requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
CID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_CLIENT_SECRET")

if not CID or not SECRET:
    raise SystemExit("Keys not found. Check the .env file name and variable names.")

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

order_id, link = create_order()
print("Open this link and pay as the sandbox buyer:\n", link)
input("Press Enter after you approve the payment...")
print("Status:", capture(order_id)["status"])