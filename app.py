import html
import os
import sqlite3
import uuid
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

BASE = "https://api-m.sandbox.paypal.com"
CID = (os.getenv("PAYPAL_CLIENT_ID") or "").strip()
SECRET = (os.getenv("PAYPAL_CLIENT_SECRET") or "").strip()
APP_URL = "http://127.0.0.1:8000"
DB = "floodeye.db"
esc = html.escape

os.makedirs("uploads", exist_ok=True)
app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

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
        conn.execute("""CREATE TABLE IF NOT EXISTS releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id TEXT NOT NULL,
            ngo_name TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            filename TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


init_db()


def get_token():
    r = requests.post(f"{BASE}/v1/oauth2/token", auth=(CID, SECRET),
                      data={"grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]


def page(body):
    return HTMLResponse(
        f"<html><body style='font-family:Arial;max-width:900px;margin:40px auto'>{body}</body></html>"
    )


def raised(zone_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM donations WHERE zone_id=? AND status='COMPLETED'",
            (zone_id,),
        ).fetchone()
    return row[0]


def released(zone_id):
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM releases WHERE zone_id=? AND status='APPROVED'",
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
            f"<td>${released(z['id']):.2f}</td>"
            f"<td><form action='/donate/{z['id']}' method='get'>"
            f"$<input name='amount' value='5' size='3'> <button>Donate</button></form>"
            f"<a href='/proof/{z['id']}'>NGO: submit proof</a></td></tr>"
        )
    return page(
        "<h1>FloodEye Relief</h1>"
        "<p>Demo with sample data. Sandbox payments only. "
        "<a href='/ledger'>Ledger</a> | <a href='/admin'>Admin</a></p>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>Severity</th><th>Raised</th><th>Released to NGOs</th><th>Actions</th></tr>"
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
        return page(f"<p>PayPal error: {r.status_code}</p><pre>{esc(r.text)}</pre><a href='/'>Back</a>")
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
        return page(f"<p>Could not capture the payment.</p><pre>{esc(r.text)}</pre><a href='/'>Back</a>")
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


@app.get("/proof/{zone_id}", response_class=HTMLResponse)
def proof_form(zone_id: str):
    if zone_id not in ZONE_NAMES:
        return page("<p>Unknown zone.</p><a href='/'>Back</a>")
    avail = raised(zone_id) - released(zone_id)
    return page(f"""
    <h1>Submit proof: {ZONE_NAMES[zone_id]}</h1>
    <p>Funds available: ${avail:.2f}</p>
    <form action='/proof/{zone_id}' method='post' enctype='multipart/form-data'>
    <p>NGO / supplier name:<br><input name='ngo_name' required></p>
    <p>Amount spent (USD):<br><input name='amount' type='number' step='0.01' min='1' required></p>
    <p>What was delivered?<br><textarea name='note' rows='3' cols='40'></textarea></p>
    <p>Photo or receipt (jpg or png):<br><input type='file' name='photo' accept='.jpg,.jpeg,.png' required></p>
    <button>Submit proof</button></form><br><a href='/'>Back</a>
    """)


@app.post("/proof/{zone_id}")
def submit_proof(zone_id: str, ngo_name: str = Form(...), amount: float = Form(...),
                 note: str = Form(""), photo: UploadFile = File(...)):
    if zone_id not in ZONE_NAMES:
        return page("<p>Unknown zone.</p><a href='/'>Back</a>")
    avail = raised(zone_id) - released(zone_id)
    if amount <= 0 or amount > avail + 0.001:
        return page(f"<p>Amount must be between $0.01 and the available ${avail:.2f}.</p>"
                    f"<a href='/proof/{zone_id}'>Try again</a>")
    ext = os.path.splitext(photo.filename or "")[1].lower()
    data = photo.file.read()
    if ext not in (".jpg", ".jpeg", ".png") or len(data) > 5 * 1024 * 1024:
        return page("<p>Please upload a jpg or png under 5 MB.</p>"
                    f"<a href='/proof/{zone_id}'>Try again</a>")
    filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join("uploads", filename), "wb") as f:
        f.write(data)
    with db() as conn:
        conn.execute(
            "INSERT INTO releases (zone_id, ngo_name, amount, note, filename) VALUES (?, ?, ?, ?, ?)",
            (zone_id, ngo_name.strip()[:100], round(amount, 2), note.strip()[:500], filename),
        )
    return page("<h2>Proof submitted</h2><p>An admin will review it.</p><a href='/'>Back to zones</a>")


@app.get("/admin", response_class=HTMLResponse)
def admin():
    with db() as conn:
        rows = conn.execute("SELECT * FROM releases ORDER BY id DESC").fetchall()
    body = ""
    for r in rows:
        buttons = ""
        if r["status"] == "PENDING":
            buttons = (
                f"<form action='/admin/{r['id']}/approve' method='post' style='display:inline'>"
                f"<button>Approve</button></form> "
                f"<form action='/admin/{r['id']}/reject' method='post' style='display:inline'>"
                f"<button>Reject</button></form>"
            )
        body += (
            f"<tr><td>{ZONE_NAMES.get(r['zone_id'], r['zone_id'])}</td><td>{esc(r['ngo_name'])}</td>"
            f"<td>${r['amount']:.2f}</td><td>{esc(r['note'] or '')}</td>"
            f"<td><a href='/uploads/{r['filename']}' target='_blank'>View proof</a></td>"
            f"<td>{r['status']}</td><td>{buttons}</td></tr>"
        )
    return page(
        "<h1>Admin: review proof</h1><p>Demo only: no login. A human approves every release.</p>"
        "<a href='/'>Back to zones</a><br><br>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>NGO</th><th>Amount</th><th>Note</th><th>Proof</th><th>Status</th><th></th></tr>"
        f"{body}</table>"
    )


@app.post("/admin/{release_id}/{action}")
def admin_action(release_id: int, action: str):
    if action not in ("approve", "reject"):
        return RedirectResponse("/admin", status_code=303)
    with db() as conn:
        rel = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if rel and rel["status"] == "PENDING":
        if action == "approve":
            avail = raised(rel["zone_id"]) - released(rel["zone_id"])
            if rel["amount"] > avail + 0.001:
                return page(f"<p>Not enough funds. Available: ${avail:.2f}.</p><a href='/admin'>Back</a>")
            new_status = "APPROVED"
        else:
            new_status = "REJECTED"
        with db() as conn:
            conn.execute("UPDATE releases SET status=? WHERE id=?", (new_status, release_id))
    return RedirectResponse("/admin", status_code=303)


@app.get("/ledger", response_class=HTMLResponse)
def ledger():
    with db() as conn:
        dons = conn.execute("SELECT * FROM donations ORDER BY id DESC").fetchall()
        rels = conn.execute("SELECT * FROM releases WHERE status='APPROVED' ORDER BY id DESC").fetchall()
    dbody = "".join(
        f"<tr><td>{ZONE_NAMES.get(r['zone_id'], r['zone_id'])}</td><td>${r['amount']:.2f}</td>"
        f"<td>{r['capture_id']}</td><td>{r['status']}</td><td>{r['created_at']}</td></tr>"
        for r in dons
    )
    rbody = "".join(
        f"<tr><td>{ZONE_NAMES.get(r['zone_id'], r['zone_id'])}</td><td>{esc(r['ngo_name'])}</td>"
        f"<td>${r['amount']:.2f}</td><td>{esc(r['note'] or '')}</td>"
        f"<td><a href='/uploads/{r['filename']}' target='_blank'>Proof</a></td><td>{r['created_at']}</td></tr>"
        for r in rels
    )
    return page(
        "<h1>Ledger</h1><a href='/'>Back to zones</a><h2>Donations</h2>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>Amount</th><th>Receipt</th><th>Status</th><th>Time (UTC)</th></tr>"
        f"{dbody}</table>"
        "<h2>Money released (approved)</h2>"
        "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
        "<tr><th>Zone</th><th>NGO</th><th>Amount</th><th>What was delivered</th><th>Proof</th><th>Time (UTC)</th></tr>"
        f"{rbody}</table>"
    )