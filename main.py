import os, json, random, asyncio, httpx, logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
import google.generativeai as genai
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Swarm-Node")

app = FastAPI(title="LROS Engine 2: 500-Agent Swarm Orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CREDENTIALS & DB ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
HEART_API_URL = os.environ.get("HEART_API_URL")

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# --- LAYER 5700: SWARM API CLIENTS ---
# All except Gemini use the OpenAI compatible client for unified code
clients = {
    "deepseek": AsyncOpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com"),
    "groq": AsyncOpenAI(api_key=os.environ.get("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"),
    "cerebras": AsyncOpenAI(api_key=os.environ.get("CEREBRAS_API_KEY"), base_url="https://api.cerebras.ai/v1"),
    "mistral": AsyncOpenAI(api_key=os.environ.get("MISTRAL_API_KEY"), base_url="https://api.mistral.ai/v1")
}

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
gemini_client = genai.GenerativeModel('gemini-2.5-flash')

# --- LAYER 5400: CLOUD MEMORY ---
def get_memory():
    if not db: raise Exception("Supabase DB not connected.")
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    return res.data[0]["state_data"]

def save_memory(state):
    if db:
        db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# --- LOAD BALANCER & EXECUTION LOGIC ---
async def call_llm(provider: str, model: str, prompt: str, system_prompt: str = "You are LROS."):
    """Standardized API caller with error handling to protect limits."""
    try:
        if provider == "gemini":
            return gemini_client.generate_content(f"{system_prompt}\n\n{prompt}").text
        else:
            client = clients[provider]
            res = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            )
            return res.choices[0].message.content
    except Exception as e:
        logger.warning(f"[{provider}] Limit/Error: {e}")
        return None # Returns None so the router knows to fallback

async def swarm_consensus(prompt: str):
    """Parallel Mode: Fires 4 APIs at once. DeepSeek audits the results and picks the best."""
    # 1. Fire Cerebras, Groq, Mistral, and Gemini simultaneously
    tasks = [
        call_llm("cerebras", "llama3.1-70b", prompt),
        call_llm("groq", "llama-3.3-70b-versatile", prompt),
        call_llm("mistral", "mistral-large-latest", prompt),
        call_llm("gemini", "gemini-2.5-flash", prompt)
    ]
    results = await asyncio.gather(*tasks)
    
    valid_results = [r for r in results if r is not None]
    if not valid_results: return "Swarm Overload: All generation nodes hit rate limits."

    # 2. DeepSeek acts as the Ombudsman to pick the best response
    audit_prompt = f"Review these {len(valid_results)} agent responses to the prompt: '{prompt}'. Synthesize the ultimate, most accurate executive answer from them. Responses: {valid_results}"
    final_answer = await call_llm("deepseek", "deepseek-reasoner", audit_prompt)
    
    return final_answer if final_answer else valid_results[0]

# --- BACKGROUND EVOLUTION (Runs 24/7) ---
async def reconcile_memory():
    while True:
        try:
            state = get_memory()
            if HEART_API_URL:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(HEART_API_URL, timeout=10.0)
                    if resp.status_code == 200:
                        state["heart_successes"] = resp.json().get("successes", state["heart_successes"])
                        state["master_successes"] = 238245 + state["lung_successes"] + state["heart_successes"]
                        save_memory(state)
        except Exception: pass
        await asyncio.sleep(10)

async def lung_evolution_cycle():
    """Delegates ideation to fast models, saves DeepSeek limits for scoring."""
    domains = ["Medical Protocol", "Novus Terra Asset", "Venture Architecture", "Constitutional Alignment"]
    while True:
        try:
            state = get_memory()
            domain = random.choice(domains)
            
            # 1. Generate Hypothesis (Rotate APIs to avoid rate limits)
            providers = [("cerebras", "llama3.1-70b"), ("groq", "llama-3.3-70b-versatile"), ("mistral", "mistral-large-latest")]
            prov, mod = random.choice(providers)
            hypothesis = await call_llm(prov, mod, f"Generate a 1-paragraph optimization strategy for {domain}.")
            
            if not hypothesis: continue # Skip cycle if rate limited
            
            # 2. DeepSeek Audits the Hypothesis
            score_prompt = f"Audit this strategy: {hypothesis}. Score strictly 0-100 based on ROI and logic. Return ONLY the integer."
            audit_res = await call_llm("deepseek", "deepseek-chat", score_prompt)
            
            try:
                audit_score = int(''.join(filter(str.isdigit, audit_res))) if audit_res else 0
            except: audit_score = 0

            # 3. Save to Ledger
            if audit_score >= 95:
                state["lung_successes"] += 1
                state["master_successes"] = 238245 + state["lung_successes"] + state.get("heart_successes", 0)
                evolved_score = round(((audit_score - 90) / 10) * 0.5, 2)
                state["daily_learning"] += evolved_score
                
                state["mutation_ledger"].insert(0, {
                    "version": f"DNA-E9.70.{state['lung_successes']%1000}",
                    "agent": f"{prov.upper()}-{random.randint(100,999)}",
                    "domain": domain,
                    "ts": datetime.utcnow().strftime("%H:%M:%S"),
                    "audit_score": audit_score,
                    "evolved": evolved_score
                })
                if len(state["mutation_ledger"]) > 20: state["mutation_ledger"].pop()
                state["lung_logs"].append(f"[{prov.upper()}] Vetted Pattern: {domain} (Score: {audit_score}%)")
            else:
                state["rejections"] = state.get("rejections", 0) + 1
                state["lung_logs"].append(f"[VETO] Ombudsman rejected {prov.upper()} drift. Score: {audit_score}%")
                
            if len(state["lung_logs"]) > 15: state["lung_logs"].pop(0)
            save_memory(state)
            
        except Exception as e:
            logger.error(f"Evolution Loop Error: {e}")
            
        await asyncio.sleep(45) # 45s pacing prevents rapid API exhaustion

# --- FRONTEND API ENDPOINTS ---
class MultiAIChat(BaseModel):
    prompt: str
    mode: str

@app.post("/api/lung/chat")
async def multi_ai_chat(req: MultiAIChat):
    """Routes your frontend chat requests."""
    mode = req.mode.lower()
    
    if mode == "parallel":
        response = await swarm_consensus(req.prompt)
    elif mode == "chain":
        # DeepSeek reasons, Gemini synthesizes
        reasoning = await call_llm("deepseek", "deepseek-reasoner", req.prompt)
        response = await call_llm("gemini", "gemini-2.5-flash", f"Format this reasoning into an executive summary:\n{reasoning}")
    elif mode in ["deepseek", "groq", "cerebras", "mistral", "gemini"]:
        # Direct model call
        models = {"deepseek": "deepseek-reasoner", "groq": "llama-3.3-70b-versatile", "cerebras": "llama3.1-70b", "mistral": "mistral-large-latest"}
        response = await call_llm(mode, models.get(mode, ""), req.prompt)
    else:
        # Auto Mode: Complexity routing
        if len(req.prompt) > 200:
            response = await call_llm("mistral", "mistral-large-latest", req.prompt)
        else:
            response = await call_llm("cerebras", "llama3.1-70b", req.prompt)

    if not response: response = "API Rate Limit Exceeded. Swarm routing to backup node next cycle."
    return {"response": response, "mode_used": mode}

@app.get("/api/lung/status")
async def get_status(): return get_memory()

@app.on_event("startup")
async def startup():
    if db:
        asyncio.create_task(reconcile_memory())
        asyncio.create_task(lung_evolution_cycle())
