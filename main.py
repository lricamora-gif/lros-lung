import os, json, random, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Apex-v74")

app = FastAPI(title="LROS Engine 2: Apex v74")
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
CEREBRAS_KEYS = get_clean_keys("CEREBRAS_API_KEY")
MISTRAL_KEYS = get_clean_keys("MISTRAL_API_KEY")

# --- LAYER 5400: CLOUD MEMORY ---
def get_memory():
    if not db: return {"error": "DB missing"}
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        default_state = {
            "master_successes": 439434, "heart_successes": 0, "lung_successes": 0,
            "daily_learning": 5523.03, "rejections": 0, "mutation_ledger": [],
            "lung_logs": ["🚀 LROS Apex v74 Online."],
            "today_stats": {"successes": 0, "rejections": 0, "last_reset": "", "engine_hits": {}}
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
    
    state = res.data[0]["state_data"]
    # Daily Reset Logic
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if state.get("today_stats", {}).get("last_reset") != today:
        state["today_stats"] = {"successes": 0, "rejections": 0, "last_reset": today, "engine_hits": {}}
    return state

def save_memory(state):
    if db: db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- EXECUTION LOGIC ---
async def call_llm(provider: str, model: str, prompt: str, system_prompt: str = "You are LROS Sovereign Command."):
    provider = provider.lower()
    keys = []
    if provider == "gemini": keys = GEMINI_KEYS
    elif provider == "deepseek": keys = DEEPSEEK_KEYS
    elif provider == "groq": keys = GROQ_KEYS
    elif provider == "cerebras": keys = CEREBRAS_KEYS
    elif provider == "mistral": keys = MISTRAL_KEYS

    for key in keys:
        try:
            if provider == "gemini":
                genai.configure(api_key=key)
                client = genai.GenerativeModel('gemini-2.0-flash')
                return client.generate_content(f"{system_prompt}\n\n{prompt}").text
            else:
                base_urls = {"deepseek": "https://api.deepseek.com", "groq": "https://api.groq.com/openai/v1", "cerebras": "https://api.cerebras.ai/v1", "mistral": "https://api.mistral.ai/v1"}
                client = AsyncOpenAI(api_key=key, base_url=base_urls[provider])
                res = await client.chat.completions.create(model=model, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}])
                return res.choices[0].message.content
        except Exception: continue
    return None

# --- LOOPS ---
async def reconcile_memory():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(HEART_API_URL, timeout=10.0)
                    if resp.status_code == 200:
                        state["heart_successes"] = resp.json().get("successes", state.get("heart_successes", 0))
                        state["master_successes"] = 439434 + state["lung_successes"] + state["heart_successes"]
                        save_memory(state)
        except Exception: pass
        await asyncio.sleep(10)

async def lung_evolution_cycle():
    domains = ["Medical Protocol", "Novus Terra Asset", "Venture Architecture", "Constitutional Alignment"]
    while True:
        try:
            state = get_memory()
            domain = random.choice(domains)
            available = [("gemini", "gemini-2.0-flash"), ("groq", "llama-3.3-70b-versatile"), ("cerebras", "llama3.1-70b"), ("mistral", "mistral-large-latest")]
            prov, mod = random.choice([a for a in available if get_clean_keys(f"{a[0].upper()}_API_KEY")])
            
            hypothesis = await call_llm(prov, mod, f"Propose one high-ROI optimization for {domain}.")
            if not hypothesis: continue

            audit_res = await call_llm("deepseek", "deepseek-chat", f"Audit this: {hypothesis}. Return ONLY an integer score 0-100.")
            try: audit_score = int(''.join(filter(str.isdigit, audit_res)))
            except: audit_score = 0

            # Statistics Update
            hits = state["today_stats"]["engine_hits"]
            hits[prov] = hits.get(prov, 0) + 1

            if audit_score >= 95:
                state["lung_successes"] += 1
                state["today_stats"]["successes"] += 1
                state["mutation_ledger"].insert(0, {"version": f"DNA-{random.randint(100,999)}", "agent": prov.upper(), "domain": domain, "ts": datetime.utcnow().strftime("%H:%M:%S"), "audit_score": audit_score})
                state["lung_logs"].append(f"[{prov.upper()}] Vetted Pattern: {domain} (Score: {audit_score}%)")
            else:
                state["rejections"] += 1
                state["today_stats"]["rejections"] += 1
                state["lung_logs"].append(f"[VETO] DeepSeek rejected {prov.upper()} drift. Score: {audit_score}%")
            
            if len(state["lung_logs"]) > 20: state["lung_logs"].pop(0)
            save_memory(state)
        except Exception: pass
        await asyncio.sleep(45)

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    asyncio.create_task(reconcile_memory())
    asyncio.create_task(lung_evolution_cycle())
