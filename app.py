import os
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

load_dotenv()

app = FastAPI()

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
# This checks for BOTH PAYPAL_SECRET and PAYPAL_CLIENT_SECRET so it never misses it!
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET") or os.getenv("PAYPAL_CLIENT_SECRET")
PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com"

# Startup diagnostic check
print(">>> DEBUG: PAYPAL_CLIENT_ID:", "LOADED" if PAYPAL_CLIENT_ID else "MISSING")
print(">>> DEBUG: PAYPAL_SECRET:", "LOADED" if PAYPAL_SECRET else "MISSING")

ZONES = [
    {"id": "zone-a", "name": "Zone A: Riverside Village", "severity": "High", "need_usd": 500},
    {"id": "zone-b", "name": "Zone B: Market Road", "severity": "Medium", "need_usd": 300},
    {"id": "zone-c", "name": "Zone C: Paddy Fields", "severity": "High", "need_usd": 400},
    {"id": "zone-d", "name": "Zone D: School Area", "severity": "Low", "need_usd": 150},
]

def get_paypal_access_token():
    url = f"{PAYPAL_API_BASE}/v1/oauth2/token"
    auth = (PAYPAL_CLIENT_ID, PAYPAL_SECRET)
    headers = {"Accept": "application/json", "Accept-Language": "en_US"}
    data = {"grant_type": "client_credentials"}
    
    response = requests.post(url, auth=auth, headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    
    return f"ERROR {response.status_code}: {response.text}"

@app.get("/", response_class=HTMLResponse)
def home():
    rows = ""
    for z in ZONES:
        rows += (f"<tr><td>{z['name']}</td><td>{z['severity']}</td>"
                 f"<td>${z['need_usd']}</td>"
                 f"<td><a href='/pay/{z['id']}'><button style='background-color:#0070ba;color:white;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;'>Donate via PayPal</button></a></td></tr>")
    
    return f"""
    <html>
    <body style="font-family:Arial;max-width:700px;margin:40px auto">
        <h1>FloodEye Relief</h1>
        <p>Support vulnerable flood zones. Sandbox payments only.</p>
        <table border="1" cellpadding="8" style="border-collapse:collapse;width:100%">
            <tr><th>Zone</th><th>Severity</th><th>Funding need</th><th>Action</th></tr>
            {rows}
        </table>
    </body>
    </html>
    """

@app.get("/pay/{zone_id}")
def pay(zone_id: str):
    zone = next((z for z in ZONES if z["id"] == zone_id), None)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    token_result = get_paypal_access_token()
    
    if not token_result or str(token_result).startswith("ERROR"):
        raise HTTPException(status_code=500, detail=f"PayPal Auth Failed -> {token_result}")

    token = token_result
    url = f"{PAYPAL_API_BASE}/v2/checkout/orders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": "USD",
                "value": str(zone["need_usd"])
            },
            "description": f"Donation to {zone['name']}"
        }],
        "application_context": {
            "return_url": "http://127.0.0.1:8000/success",
            "cancel_url": "http://127.0.0.1:8000/"
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 201:
        raise HTTPException(status_code=500, detail=f"PayPal Order Failed ({response.status_code}): {response.text}")

    order_data = response.json()
    approval_url = None
    for link in order_data.get("links", []):
        if link["rel"] == "approve":
            approval_url = link["href"]
            break

    if approval_url:
        return RedirectResponse(url=approval_url, status_code=303)
    
    raise HTTPException(status_code=500, detail="PayPal approval URL not found")

@app.get("/success", response_class=HTMLResponse)
def success():
    return """
    <html>
    <body style="font-family:Arial;max-width:700px;margin:40px auto;text-align:center;">
        <h1 style="color:green;">Thank You for Your Donation!</h1>
        <p>Your sandbox payment was completed successfully.</p>
        <a href="/"><button style="padding:10px 20px;background:#0070ba;color:white;border:none;border-radius:4px;">Back to Zones</button></a>
    </body>
    </html>
    """