import os, json, random, asyncio, httpx, logging
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
GROQ_KEYS = get_clean_keys("GROQ_API_KEY")

# --- LAYER 5400: DYNAMIC CLOUD MEMORY ---
def get_memory():
    if not db: return {"error": "DB Neural Link Severed"}
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    
    if not res.data:
        # DATA SYNC FROM IMAGE 4bd33f.png
        default_state = {
            "baseline_anchor": 439434, 
            "master_successes": 926084, 
            "heart_successes": 486650, 
            "lung_successes": 0,
            "daily_learning": 5523.03, 
            "rejections": 56, 
            "mutation_ledger": [],
            "lung_logs": ["[MANDATE] Apex v76 Online. Evolving Baseline Logic."],
            "node_performance": {"gemini": 0, "groq": 0, "cerebras": 0, "mistral": 0, "deepseek": 0}
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
    
    return res.data[0]["state_data"]

def save_memory(state):
    if db: db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- NEW EVOLUTION: BASELINE ANCHORING ---
@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_memory()
    # Logic: Set current master as the new anchor and reset engine counters for a new 'Today' era
    state["baseline_anchor"] = state["master_successes"]
    # We maintain the tally but anchor the base
    state["lung_logs"].append(f"[ANCHOR] New Baseline Secured: {state['baseline_anchor']:,}")
    save_memory(state)
    return {"status": "success", "new_baseline": state["baseline_anchor"]}

# --- ENGINE LOGIC ---
async def call_llm(provider: str, model: str, prompt: str):
    provider = provider.lower()
    keys = {"gemini": GEMINI_KEYS, "deepseek": DEEPSEEK_KEYS, "groq": GROQ_KEYS}.get(provider, [])
    for key in keys:
        try:
            if provider == "gemini":
                genai.configure(api_key=key)
                client = genai.GenerativeModel('gemini-2.0-flash')
                return client.generate_content(prompt).text
            else:
                client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com" if provider=="deepseek" else "https://api.groq.com/openai/v1")
                res = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
                return res.choices[0].message.content
        except Exception: continue
    return None

async def reconcile_memory():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(HEART_API_URL, timeout=10.0)
                    if resp.status_code == 200:
                        heart_val = resp.json().get("successes", 0)
                        state["heart_successes"] = heart_val
                        # Master = Stored Anchor + Engine 1 + Engine 2
                        state["master_successes"] = state.get("baseline_anchor", 439434) + state["lung_successes"] + state["heart_successes"]
                        save_memory(state)
        except Exception: pass
        await asyncio.sleep(10)

async def lung_evolution_cycle():
    while True:
        try:
            state = get_memory()
            # ... (Existing Evolution Logic)
            await asyncio.sleep(45)
        except Exception: pass

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    asyncio.create_task(reconcile_memory())
    # Start the cycle logic here...
