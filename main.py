import os, json, random, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-HardReset-v83")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- DATABASE & CONFIG ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
HEART_API_URL = os.environ.get("HEART_API_URL")

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

def get_clean_keys(env_var):
    raw = os.environ.get(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GEMINI_KEYS = get_clean_keys("GEMINI_API_KEY")
DEEPSEEK_KEYS = get_clean_keys("DEEPSEEK_API_KEY")

# --- CORE STATE RECOVERY ---
def get_memory():
    if not db: return {"error": "Link Severed"}
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    
    if not res.data:
        # FORCED RECOVERY: Syncing to Master 928,951
        init_state = {
            "baseline_anchor": 439434, 
            "master_successes": 928951, 
            "heart_successes": 489517, 
            "lung_successes": 0,
            "rejections": 56, 
            "daily_learning": 5523.03,
            "lung_logs": ["[MANDATE] Hard Reset Complete. Ground Truth 928,951 Locked."],
            "node_performance": {"gemini": 0, "deepseek": 0}
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": init_state}).execute()
        return init_state
    return res.data[0]["state_data"]

def save_memory(state):
    if db: db.table("sovereign_state").update({"state_data": state}).eq("id", 1).execute()

# --- THE EVOLUTION TRIGGER ---
@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_memory()
    # Migration: Anchor moves to total, Engine progress resets to zero.
    state["baseline_anchor"] = state["master_successes"]
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    state["lung_logs"].append(f"[ANCHOR] Evolution Secured. New Baseline: {state['baseline_anchor']:,}")
    save_memory(state)
    return {"status": "success", "new_baseline": state["baseline_anchor"]}

async def reconcile():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(HEART_API_URL, timeout=10.0)
                    if resp.status_code == 200:
                        state["heart_successes"] = resp.json().get("successes", 0)
            
            # THE IMMUTABLE FORMULA
            state["master_successes"] = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
            save_memory(state)
        except Exception as e:
            logger.error(f"Sync Error: {e}")
        await asyncio.sleep(10)

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup(): asyncio.create_task(reconcile())
