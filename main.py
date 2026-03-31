import os, json, random, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Dual-Core")

app = FastAPI(title="LROS Engine 2: Dual-Core Swarm Orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CREDENTIALS & DB ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
HEART_API_URL = os.environ.get("HEART_API_URL")

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# --- LAYER 5700: DUAL-CORE API CLIENTS ---
# Stripped out Groq, Mistral, and Cerebras. Relying purely on stable volume.
deepseek = AsyncOpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
gemini_client = genai.GenerativeModel('gemini-2.5-flash')

# --- LAYER 5400: CLOUD MEMORY ---
def get_memory():
    if not db: raise Exception("Supabase DB not connected.")
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    
    if not res.data:
        default_state = {
            "master_successes": 439434,
            "heart_successes": 0,
            "lung_successes": 0,
            "daily_learning": 11562.76,
            "rejections": 0,
            "mutation_ledger": [],
            "lung_logs": ["🚀 Lung Engine 2 Online. Dual-Core Mode Active."]
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
        return default_state
        
    return res.data[0]["state_data"]

def save_memory(state):
    if db:
        db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- EXECUTION LOGIC ---
async def call_llm(provider: str, model: str, prompt: str, system_prompt: str = "You are LROS. Speak with executive authority."):
    try:
        if provider == "gemini":
            return gemini_client.generate_content(f"{system_prompt}\n\n{prompt}").text
        elif provider == "deepseek":
            res = await deepseek.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            )
            if res.choices and len(res.choices) > 0:
                return res.choices[0].message.content
        return None
    except Exception as e:
        logger.warning(f"[{provider.upper()}] API Limit/Error: {e}")
        return None

async def swarm_consensus(prompt: str):
    """Simulates a Swarm using just Gemini and DeepSeek by asking Gemini twice from different perspectives."""
    tasks = [
        call_llm("gemini", "gemini-2.5-flash", prompt, "You are a bold, visionary AI CEO. Answer the prompt."),
        call_llm("gemini", "gemini-2.5-flash", prompt, "You are a conservative, highly analytical AI CFO. Answer the prompt.")
    ]
    results = await asyncio.gather(*tasks)
    
    valid_results = [r for r in results if r is not None]
    if not valid_results: return "Swarm Overload: Gemini APIs rate-limited."

    audit_prompt = f"Review these two different AI perspectives to the prompt: '{prompt}'. Synthesize the ultimate, perfect executive answer. Perspectives: {valid_results}"
    final_answer = await call_llm("deepseek", "deepseek-reasoner", audit_prompt)
    
    return final_answer if final_answer else valid_results[0]

# --- BACKGROUND EVOLUTION ---
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
            
            # Gemini generates the idea (Heavy Lifting)
            hypothesis = await call_llm("gemini", "gemini-2.5-flash", f"Generate a 1-paragraph optimization strategy for {domain}.")
            
            if not hypothesis: 
                await asyncio.sleep(15)
                continue
            
            # DeepSeek audits the idea (The Brain)
            score_prompt = f"Audit this strategy: {hypothesis}. Score strictly 0-100 based on ROI and logic. Return ONLY the integer."
            audit_res = await call_llm("deepseek", "deepseek-chat", score_prompt)
            
            try:
                audit_score = int(''.join(filter(str.isdigit, audit_res))) if audit_res else 0
            except: audit_score = 0

            if audit_score >= 95:
                state["lung_successes"] += 1
                state["master_successes"] = 439434 + state["lung_successes"] + state.get("heart_successes", 0)
                evolved_score = round(((audit_score - 90) / 10) * 0.5, 2)
                state["daily_learning"] += evolved_score
                
                state["mutation_ledger"].insert(0, {
                    "version": f"DNA-E9.80.{state['lung_successes']%1000}",
                    "agent": f"GEMINI-{random.randint(100,999)}",
                    "domain": domain,
                    "ts": datetime.utcnow().strftime("%H:%M:%S"),
                    "audit_score": audit_score,
                    "evolved": evolved_score
                })
                if len(state["mutation_ledger"]) > 20: state["mutation_ledger"].pop()
                state["lung_logs"].append(f"[GEMINI] Vetted Pattern: {domain} (Score: {audit_score}%)")
            else:
                state["rejections"] = state.get("rejections", 0) + 1
                state["lung_logs"].append(f"[VETO] DeepSeek rejected Gemini drift. Score: {audit_score}%")
                
            if len(state["lung_logs"]) > 15: state["lung_logs"].pop(0)
            save_memory(state)
            
        except Exception as e:
            logger.error(f"Evolution Loop Error: {e}")
            
        # PACING EXTENDED TO 65 SECONDS to guarantee we never hit Gemini's 1,500 Requests/Day limit
        await asyncio.sleep(65) 

# --- FRONTEND API ENDPOINTS ---
class MultiAIChat(BaseModel):
    prompt: str
    mode: str

@app.post("/api/lung/chat")
async def multi_ai_chat(req: MultiAIChat):
    mode = req.mode.lower()
    
    if mode == "parallel":
        response = await swarm_consensus(req.prompt)
    elif mode == "deepseek":
        response = await call_llm("deepseek", "deepseek-reasoner", req.prompt)
    else:
        # Default fallback is Gemini
        response = await call_llm("gemini", "gemini-2.5-flash", req.prompt)

    if not response: response = "Neural Link Degraded. Please try again."
    return {"response": response, "mode_used": mode}

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    if db:
        asyncio.create_task(reconcile_memory())
        asyncio.create_task(lung_evolution_cycle())
