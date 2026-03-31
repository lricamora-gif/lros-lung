import os, json, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Sovereign-v76")

app = FastAPI(title="LROS Engine 2: Sovereign v76")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CREDENTIALS ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# --- SYNCED DATA FROM IMAGE 4C51C3.JPG ---
def get_memory():
    if not db: return {"error": "Neural Link Severed"}
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    
    if not res.data:
        # INITIAL STATE LOADED DIRECTLY FROM TELEMETRY
        default_state = {
            "baseline_anchor": 439434, 
            "master_successes": 932004, 
            "heart_successes": 492570, 
            "lung_successes": 0,
            "rejections": 64, 
            "learning_yield": 5523.03,
            "lung_logs": ["[MANDATE] Sovereign v76 Synchronized. Baseline: 439,434 anchored."]
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
    return res.data[0]["state_data"]

def save_memory(state):
    if db: db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- THE "SECURE BASELINE" ENHANCEMENT ---
@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_memory()
    # Logic: Freeze the current 932k as the new foundation
    new_anchor = state["master_successes"]
    state["baseline_anchor"] = new_anchor
    state["heart_successes"] = 0 # Reset session count after anchoring
    state["lung_successes"] = 0
    state["lung_logs"].append(f"[ANCHOR] New Baseline Secured: {new_anchor:,}")
    save_memory(state)
    return {"status": "success", "new_baseline": new_anchor}

@app.get("/api/lung/status")
async def get_status(): return get_memory()

# Heartbeat reconciliation loop
async def reconcile():
    while True:
        try:
            state = get_memory()
            # Master = Anchor + Heart + Lung
            state["master_successes"] = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
            save_memory(state)
        except Exception: pass
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup(): asyncio.create_task(reconcile())
