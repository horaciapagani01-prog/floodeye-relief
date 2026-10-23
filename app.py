import os
import sqlite3
import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

load_dotenv()

BASE = "https://api-m.sandbox.paypal.com"
CID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
APP_URL = "http://127.0.0.1:8000"
DB = "floodeye.db"

app = FastAPI()

ZONES = [
    {"id": "zone-a", "name": "Zone A: Riverside Village", "severity": "High", "need_usd": 500},
    {"id": "zone-b", "name": "Zone B: Market Road", "severity": "Medium", "need_usd": 300},
    {"id": "zone-c", "name": "Zone C: Paddy Fields", "severity": "High", "need_usd": 400},
    {"id": "zone-d", "name": "Zone D: School Area", "severity": "Low", "need_usd": 150},
]
ZONE_NAMES = {z["id"]: z["name"] for z in ZONES}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id TEXT NOT NULL,
            amount REAL NOT NULL,
            capture_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


init_db()


def get_token():
    r = requests.post(f"{BASE}/v1/oauth2/token", auth=(CID, SECRET),
                      data={"grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]


def page(body):
    return HTMLResponse(
        f"<html><body style='font-family:Arial;max-width:800px;margin:40px auto'>{body}</body></html>"
    )


def raised(zone_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM donations WHERE zone_id=? AND status='COMPLETED'",
            (zone_id,),
        ).fetchone()
    return row[0]


@app.get("/", response_class=HTMLResponse)
def home():
    rows = ""
    for z in ZONES:
        rows += (
            f"<tr><td>{z['name']}</td><td>{z['severity']}</td>"
            f"<td>${raised(z['id']):.2f} of ${z['need_usd']}</td>"
            f"<td><form action='/donate/{z['id']}' method='get'>"
            f"$<input name='amount' value='5' size='3'> <button>Donate</button></form></td></tr>"
        )
    return page(
        "<h1>FloodEye Relief</h1>"
        "<p>Demo with sample data. Sandbox payments only. <a href='/ledger'>View ledger</a></p>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>Severity</th><th>Raised</th><th>Donate</th></tr>"
        f"{rows}</table>"
    )


@app.get("/donate/{zone_id}")
def donate(zone_id: str, amount: float = 5):
    zone = next((z for z in ZONES if z["id"] == zone_id), None)
    if not zone:
        return page("<p>Unknown zone.</p><a href='/'>Back</a>")
    amount = round(max(1, min(100, amount)), 2)
    r = requests.post(
        f"{BASE}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {get_token()}"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "custom_id": zone_id,
                "description": f"Flood relief: {zone['name']}",
                "amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
            }],
            "payment_source": {"paypal": {"experience_context": {
                "user_action": "PAY_NOW",
                "return_url": f"{APP_URL}/return",
                "cancel_url": f"{APP_URL}/",
            }}},
        },
    )
    if not r.ok:
        return page(f"<p>PayPal error: {r.status_code}</p><pre>{r.text}</pre><a href='/'>Back</a>")
    d = r.json()
    link = next(l["href"] for l in d["links"] if l["rel"] in ("approve", "payer-action"))
    return RedirectResponse(link)


@app.get("/return")
def paypal_return(token: str):
    r = requests.post(
        f"{BASE}/v2/checkout/orders/{token}/capture",
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"},
    )
    if not r.ok:
        if "ORDER_ALREADY_CAPTURED" in r.text:
            return RedirectResponse("/")
        return page(f"<p>Could not capture the payment.</p><pre>{r.text}</pre><a href='/'>Back</a>")
    d = r.json()
    unit = d["purchase_units"][0]
    cap = unit["payments"]["captures"][0]
    zone_id = cap.get("custom_id") or unit.get("custom_id") or "unknown"
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO donations (zone_id, amount, capture_id, status) VALUES (?, ?, ?, ?)",
            (zone_id, float(cap["amount"]["value"]), cap["id"], cap["status"]),
        )
    return page(
        f"<h2>Thank you!</h2><p>Payment {cap['status']}.</p>"
        f"<p>Receipt ID: {cap['id']}</p><a href='/'>Back to zones</a>"
    )


@app.get("/ledger", response_class=HTMLResponse)
def ledger():
    with db() as conn:
        rows = conn.execute("SELECT * FROM donations ORDER BY id DESC").fetchall()
    body = "".join(
        f"<tr><td>{ZONE_NAMES.get(r['zone_id'], r['zone_id'])}</td><td>${r['amount']:.2f}</td>"
        f"<td>{r['capture_id']}</td><td>{r['status']}</td><td>{r['created_at']}</td></tr>"
        for r in rows
    )
    return page(
        "<h1>Donation ledger</h1><a href='/'>Back to zones</a><br><br>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>Amount</th><th>Receipt</th><th>Status</th><th>Time (UTC)</th></tr>"
        f"{body}</table>"
    )