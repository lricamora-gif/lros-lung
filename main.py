import os, json, random, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Omni-Swarm")

app = FastAPI(title="LROS Engine 2: 5-Node Auto-Healing Swarm")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CREDENTIALS & DB ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
HEART_API_URL = os.environ.get("HEART_API_URL")

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# --- THE KEY VAULT & SANITIZER ---
def get_clean_keys(env_var_name):
    """Slices comma-separated keys, strips invisible spaces, and ignores blanks."""
    raw_string = os.environ.get(env_var_name, "")
    if not raw_string: return []
    return [k.strip() for k in raw_string.split(",") if k.strip()]

DEEPSEEK_KEYS = get_clean_keys("DEEPSEEK_API_KEY")
GEMINI_KEYS = get_clean_keys("GEMINI_API_KEY")
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
            "daily_learning": 11562.76, "rejections": 0, "mutation_ledger": [],
            "lung_logs": ["🚀 Lung Engine 2 Online. 5-Node Swarm Active."]
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
    return res.data[0]["state_data"]

def save_memory(state):
    if db:
        db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- EXECUTION LOGIC (WITH AUTO-ROTATION) ---
async def call_openai_compatible(keys, base_url, model, prompt, system_prompt, provider_name):
    if not keys: return None
    for key in keys:
        try:
            client = AsyncOpenAI(api_key=key, base_url=base_url)
            res = await client.chat.completions.create(
                model=model, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            )
            if res.choices: return res.choices[0].message.content
        except Exception as e:
            logger.warning(f"[{provider_name}] Key {key[:4]}... failed. Trying next. Error: {e}")
            continue
    return None

async def call_llm(provider: str, model: str, prompt: str, system_prompt: str = "You are LROS."):
    if provider == "gemini":
        if not GEMINI_KEYS: return None
        for key in GEMINI_KEYS:
            try:
                genai.configure(api_key=key)
                gemini_client = genai.GenerativeModel('gemini-2.5-flash')
                return gemini_client.generate_content(f"{system_prompt}\n\n{prompt}").text
            except Exception as e:
                logger.warning(f"[GEMINI] Key failed. Trying next. Error: {e}")
                continue
        return None
    elif provider == "deepseek":
        return await call_openai_compatible(DEEPSEEK_KEYS, "https://api.deepseek.com", model, prompt, system_prompt, "DEEPSEEK")
    elif provider == "groq":
        return await call_openai_compatible(GROQ_KEYS, "https://api.groq.com/openai/v1", model, prompt, system_prompt, "GROQ")
    elif provider == "cerebras":
        return await call_openai_compatible(CEREBRAS_KEYS, "https://api.cerebras.ai/v1", model, prompt, system_prompt, "CEREBRAS")
    elif provider == "mistral":
        return await call_openai_compatible(MISTRAL_KEYS, "https://api.mistral.ai/v1", model, prompt, system_prompt, "MISTRAL")
    return None

async def swarm_consensus(prompt: str):
    """Fires all available APIs simultaneously and DeepSeek audits the ultimate answer."""
    tasks = []
    if CEREBRAS_KEYS: tasks.append(call_llm("cerebras", "llama3.1-70b", prompt))
    if GROQ_KEYS: tasks.append(call_llm("groq", "llama-3.3-70b-versatile", prompt))
    if GEMINI_KEYS: tasks.append(call_llm("gemini", "gemini-2.5-flash", prompt))
    if MISTRAL_KEYS: tasks.append(call_llm("mistral", "mistral-large-latest", prompt))
    
    # Fallback to a simple chain if only DeepSeek is alive
    if not tasks: tasks.append(call_llm("deepseek", "deepseek-chat", prompt))

    results = await asyncio.gather(*tasks)
    valid_results = [r for r in results if r is not None]
    
    if not valid_results: return "Swarm Overload: All API keys failed."
    if len(valid_results) == 1: return valid_results[0]
    
    audit_prompt = f"Synthesize the ultimate answer from these AI perspectives: {valid_results}"
    final_answer = await call_llm("deepseek", "deepseek-reasoner", audit_prompt)
    return final_answer if final_answer else valid_results[0]

# --- BACKGROUND EVOLUTION ---
async def reconcile_memory():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL and "error" not in state:
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
            if "error" in state:
                await asyncio.sleep(15)
                continue
                
            domain = random.choice(domains)
            
            # --- ASYMMETRIC LOAD BALANCING ---
            available_generators = []
            if GEMINI_KEYS: available_generators.append(("gemini", "gemini-2.5-flash"))
            if GROQ_KEYS: available_generators.append(("groq", "llama-3.3-70b-versatile"))
            if CEREBRAS_KEYS: available_generators.append(("cerebras", "llama3.1-70b"))
            if MISTRAL_KEYS: available_generators.append(("mistral", "mistral-large-latest"))

            if available_generators:
                prov, mod = random.choice(available_generators)
                hypothesis = await call_llm(prov, mod, f"Generate a 1-paragraph optimization strategy for {domain}.")
                generator_used = prov.upper()
            else:
                hypothesis = None

            # Auto-Heal to DeepSeek if primary fails
            if not hypothesis: 
                logger.warning("Generators failed. Auto-healing to DeepSeek.")
                hypothesis = await call_llm("deepseek", "deepseek-chat", f"Generate a 1-paragraph optimization strategy for {domain}.")
                generator_used = "DEEPSEEK"

            if not hypothesis:
                logger.error("CRITICAL: All key vaults failed. Cannot generate.")
                await asyncio.sleep(30)
                continue
            
            # --- DEEPSEEK OMBUDSMAN AUDIT ---
            score_prompt = f"Audit this strategy: {hypothesis}. Score strictly 0-100 based on ROI and logic. Return ONLY the integer."
            audit_res = await call_llm("deepseek", "deepseek-chat", score_prompt)
            
            try: audit_score = int(''.join(filter(str.isdigit, audit_res))) if audit_res else 0
            except: audit_score = 0

            # --- LEDGER COMMIT ---
            if audit_score >= 95:
                state["lung_successes"] += 1
                state["master_successes"] = 439434 + state["lung_successes"] + state.get("heart_successes", 0)
                evolved_score = round(((audit_score - 90) / 10) * 0.5, 2)
                state["daily_learning"] += evolved_score
                
                state["mutation_ledger"].insert(0, {
                    "version": f"DNA-E9.99.{state['lung_successes']%1000}",
                    "agent": f"{generator_used}-{random.randint(100,999)}",
                    "domain": domain, "ts": datetime.utcnow().strftime("%H:%M:%S"),
                    "audit_score": audit_score, "evolved": evolved_score
                })
                if len(state["mutation_ledger"]) > 20: state["mutation_ledger"].pop()
                state["lung_logs"].append(f"[{generator_used}] Vetted Pattern: {domain} (Score: {audit_score}%)")
            else:
                state["rejections"] = state.get("rejections", 0) + 1
                state["lung_logs"].append(f"[VETO] DeepSeek rejected {generator_used} drift. Score: {audit_score}%")
                
            if len(state["lung_logs"]) > 15: state["lung_logs"].pop(0)
            save_memory(state)
            
        except Exception as e:
            logger.error(f"Evolution Loop Error: {e}")
            
        await asyncio.sleep(45) 

# --- FRONTEND API ENDPOINTS ---
class MultiAIChat(BaseModel):
    prompt: str
    mode: str

@app.post("/api/lung/chat")
async def multi_ai_chat(req: MultiAIChat):
    mode = req.mode.lower()
    if mode == "parallel": response = await swarm_consensus(req.prompt)
    elif mode == "deepseek": response = await call_llm("deepseek", "deepseek-reasoner", req.prompt)
    elif mode in ["groq", "cerebras", "mistral"]: 
        models = {"groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b", "mistral": "mistral-large-latest"}
        response = await call_llm(mode, models[mode], req.prompt)
    else: response = await call_llm("gemini", "gemini-2.5-flash", req.prompt)
    
    if not response: response = "Neural Link Degraded. Please try again."
    return {"response": response, "mode_used": mode}

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    asyncio.create_task(reconcile_memory())
    asyncio.create_task(lung_evolution_cycle())
