import os, json, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Sovereign-v76")

app = FastAPI(title="LROS Engine 2: Sovereign v76")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CREDENTIALS & DB ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
HEART_API_URL = os.environ.get("HEART_API_URL")

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

def get_clean_keys(env_var_name):
    raw_string = os.environ.get(env_var_name, "")
    return [k.strip() for k in raw_string.split(",") if k.strip()]

GEMINI_KEYS = get_clean_keys("GEMINI_API_KEY")
DEEPSEEK_KEYS = get_clean_keys("DEEPSEEK_API_KEY")

# --- LAYER 5400: DYNAMIC CLOUD MEMORY ---
def get_memory():
    if not db: return {"error": "DB Neural Link Severed"}
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    
    if not res.data:
        # DATA SYNC FROM TELEMETRY: 928,951
        default_state = {
            "baseline_anchor": 928951, 
            "master_successes": 928951, 
            "heart_successes": 0, 
            "heart_at_anchor": 0,
            "lung_successes": 0,
            "rejections": 56, 
            "lung_logs": ["[MANDATE] Sovereign v76 Online. 928,951 Verified."],
            "node_performance": {"gemini": 0, "deepseek": 0}
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
    return res.data[0]["state_data"]

def save_memory(state):
    if db: db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- THE ABSORPTION LOGIC ---
@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_memory()
    new_anchor = state["master_successes"]
    
    # Anchor the current total and reset session counters
    state["baseline_anchor"] = new_anchor
    state["lung_successes"] = 0
    # Store Heart's current value to calculate 'gain' relative to this anchor
    state["heart_at_anchor"] = state.get("heart_successes", 0)
    
    state["lung_logs"].append(f"[ANCHOR] New Baseline Secured: {new_anchor:,}")
    save_memory(state)
    return {"status": "success", "new_baseline": new_anchor}

async def reconcile_memory():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(HEART_API_URL, timeout=10.0)
                    if resp.status_code == 200:
                        state["heart_successes"] = resp.json().get("successes", 0)
            
            # TALLY CALCULATION: Anchor + Session Lung + Heart Gain
            heart_gain = state["heart_successes"] - state.get("heart_at_anchor", 0)
            state["master_successes"] = state["baseline_anchor"] + state["lung_successes"] + heart_gain
            save_memory(state)
        except Exception as e:
            logger.error(f"Reconciliation Error: {e}")
        await asyncio.sleep(10)

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    asyncio.create_task(reconcile_memory())
