import os
import sqlite3
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Import our custom AI validator module
from ai_validator import validate_proof_image

app = FastAPI()

# Mount uploads directory to serve images statically
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")

def get_db():
    conn = sqlite3.connect("floodeye.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Proofs table with ai_verdict column
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proofs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id TEXT,
            ngo_name TEXT,
            amount REAL,
            note TEXT,
            image_path TEXT,
            ai_verdict TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.post("/submit-proof")
async def submit_proof(
    request: Request,
    zone_id: str = Form(...),
    ngo_name: str = Form(...),
    amount: float = Form(...),
    note: str = Form(...),
    proof_image: UploadFile = File(...)
):
    # 1. Save uploaded image to disk
    file_path = os.path.join("uploads", proof_image.filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await proof_image.read())

    # 2. Run Claude AI audit on the image & details
    ai_verdict = validate_proof_image(file_path, ngo_name, amount, note)

    # 3. Store record in SQLite database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO proofs (zone_id, ngo_name, amount, note, image_path, ai_verdict, status)
        VALUES (?, ?, ?, ?, ?, ?, 'Pending')
        """,
        (zone_id, ngo_name, amount, note, file_path, ai_verdict)
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proofs ORDER BY id DESC")
    proofs = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin.html", {"proofs": proofs})