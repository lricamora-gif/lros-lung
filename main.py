import os, json, random, asyncio, logging
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import google.generativeai as genai
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# ---------- LROS v69.2 OMNI-AUDITED SWARM ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Core")
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_primary_key(env_var_name):
    raw_keys = os.environ.get(env_var_name) or os.environ.get(env_var_name + "S")
    if raw_keys: return raw_keys.split(',')[0].strip()
    return None

GEMINI_API_KEY = get_primary_key("GEMINI_API_KEY")
DEEPSEEK_API_KEY = get_primary_key("DEEPSEEK_API_KEY")
OPENAI_API_KEY = get_primary_key("OPENAI_API_KEY")
OPENROUTER_API_KEY = get_primary_key("OPENROUTER_API_KEY")

class CognitiveRouter:
    # ... (your existing CognitiveRouter code, unchanged) ...
    def __init__(self):
        self.gemini = None
        self.deepseek = None
        self.openai = None
        
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
            self.gemini = genai.GenerativeModel('gemini-2.5-flash')
        if DEEPSEEK_API_KEY:
            self.deepseek = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        elif OPENROUTER_API_KEY: 
            self.deepseek = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
        if OPENAI_API_KEY:
            self.openai = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def generate(self, prompt: str, task_type: str = "chat", mode: str = "solo"):
        used_api = "ERR"
        response_text = "Neural Links Offline."
        
        try:
            if mode != "solo":
                prompt = f"[SYSTEM: EXECUTE {mode.upper()} CONSENSUS PROTOCOL]\n" + prompt
            
            if task_type == "evolution" and self.deepseek:
                res = await self.deepseek.chat.completions.create(model="deepseek-reasoner" if DEEPSEEK_API_KEY else "deepseek/deepseek-r1", messages=[{"role": "user", "content": prompt}])
                response_text, used_api = res.choices[0].message.content, "D" if DEEPSEEK_API_KEY else "OR"
            
            elif task_type == "research" and self.openai:
                res = await self.openai.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
                response_text, used_api = res.choices[0].message.content, "O"
            
            elif self.gemini:
                response_text, used_api = self.gemini.generate_content(prompt).text, "G"
                
            elif self.deepseek:
                res = await self.deepseek.chat.completions.create(model="deepseek-chat" if DEEPSEEK_API_KEY else "deepseek/deepseek-chat", messages=[{"role": "user", "content": prompt}])
                response_text, used_api = res.choices[0].message.content, "D" if DEEPSEEK_API_KEY else "OR"

            logger.info(f"[API_USAGE] [{used_api}] Executed Task: {task_type.upper()} | Mode: {mode.upper()}")
            return response_text, used_api
            
        except Exception as e:
            logger.error(f"[API_ERROR] {e}")
            return f"Neural routing failed: {str(e)}", "ERR"

brain = CognitiveRouter()

# --- SOVEREIGN FLOOR ---
BASE_SUCCESSES = 54139
BASE_USES = 1145515
STATE_DIR = "./data"
STATE_FILE = os.path.join(STATE_DIR, "sovereign_state.json")
MANIFEST_FILE = os.path.join(STATE_DIR, "layer_manifest.json")
GOV_FILE = os.path.join(STATE_DIR, "governance.json")

WHITELIST = [
    "angelrabajante@theljrgroup.com", "sofiaysabellebeltran@theljrgroup.com",
    "jeannettecabanes@theljrgroup.com", "rencaturay@theljrgroup.com",
    "ramonganan@theljrgroup.com", "justinsacayanan@theljrgroup.com",
    "luisseroxas@theljrgroup.com", "luigiricamora@theljrgroup.com"
]

stats = {
    "uses": BASE_USES, "successes": BASE_SUCCESSES, "active_agent_id": "098",
    "daily_layers": 0, "daily_learning": 0.0,
    "mutation_ledger": [], "logs": ["🚀 v69.2 Omni-Audited Core Online.", "🧬 54,139 Success Floor Locked."]
}
user_activity = {}

def ensure_dir(): os.makedirs(STATE_DIR, exist_ok=True)
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f: return json.load(f)
        except Exception: return default
    return default
def save_json(path, data):
    ensure_dir()
    try:
        with open(path, "w") as f: json.dump(data, f, indent=2)
    except Exception: pass

def load_from_disk():
    global stats
    disk_data = load_json(STATE_FILE, {})
    if disk_data.get("successes", 0) >= BASE_SUCCESSES: stats.update(disk_data)

def init_manifest():
    default = {"version": "v69.2-Audited", "layers": [
        {"id": "0", "name": "Immune Core", "type": "constitutional", "status": "active"}
    ]}
    return load_json(MANIFEST_FILE, default)

@app.get("/api/layers/manifest")
async def get_manifest(): return init_manifest()

@app.post("/api/layers/propose")
async def trigger_proposal():
    gov = load_json(GOV_FILE, {"pending": [], "approved": []})
    manifest = init_manifest()
    prompt = f"You are LROS Sovereign AI. Current layers: {', '.join([l['name'] for l in manifest['layers']])}. Propose ONE new highly advanced venture layer. Return ONLY valid JSON: 'name', 'description', 'rationale'."
    
    response_text, api = await brain.generate(prompt, task_type="evolution")
    try:
        ai_data = json.loads(response_text.replace('```json', '').replace('```', '').strip())
        prop_id = f"179{random.randint(10,99)}"
        gov["pending"].append({
            "id": f"layer_{prop_id}", "type": "layer_proposal", "layer_id": prop_id,
            "name": ai_data.get("name", "Strategic Override Layer"), 
            "description": ai_data.get("description", "System generated."),
            "rationale": ai_data.get("rationale", "System optimized.")
        })
        save_json(GOV_FILE, gov)
        stats["logs"].append(f"[{api}] Proposed Layer: {ai_data.get('name')[:15]}...")
        return {"status": "proposal_generated"}
    except Exception: return {"status": "error"}

@app.get("/api/governance/pending")
async def get_pending(): return load_json(GOV_FILE, {"pending": []})["pending"]

@app.post("/api/governance/decide")
async def decide_gov(req: dict):
    gov = load_json(GOV_FILE, {"pending": [], "approved": []})
    item_id, action = req.get("item_id"), req.get("action")
    item = next((i for i in gov["pending"] if i["id"] == item_id), None)
    if item:
        gov["pending"].remove(item)
        if action == "approve": gov["approved"].append(item)
        save_json(GOV_FILE, gov)
    return {"status": "decided"}

@app.post("/api/layers/deploy")
async def deploy_layers():
    gov = load_json(GOV_FILE, {"pending": [], "approved": []})
    manifest = init_manifest()
    approved = [i for i in gov["approved"] if i["type"] == "layer_proposal"]
    for l in approved:
        manifest["layers"].append({"id": l["layer_id"], "name": l["name"], "type": "operational", "status": "active", "description": l["description"]})
        stats["daily_layers"] += 1
    gov["approved"] = [i for i in gov["approved"] if i["type"] != "layer_proposal"]
    save_json(MANIFEST_FILE, manifest)
    save_json(GOV_FILE, gov)
    stats["logs"].append(f"[SYS] Deployed {len(approved)} Approved Layers.")
    return {"status": "deployed"}

@app.post("/api/auth/verify")
async def verify(req: dict):
    if req.get("email", "").lower() in WHITELIST: return {"status": "authorized"}
    raise HTTPException(403)

@app.post("/api/users/activity")
async def heartbeat(req: dict):
    if req.get("email"): user_activity[req.get("email")] = datetime.utcnow()
    return {"status": "pulsing"}

@app.get("/api/users/online")
async def get_online():
    now = datetime.utcnow()
    return {"online": [{"email": e, "ts": t.strftime("%H:%M:%S")} for e, t in user_activity.items() if (now-t).total_seconds() < 300]}

@app.get("/api/orchestrate/status")
async def get_status():
    manifest = init_manifest()
    return {**stats, "learning_perc": 100, "total_layers": len(manifest["layers"]), "logs": stats["logs"][-10:]}

@app.post("/api/research")
async def research(req: dict):
    topic = req.get("topic")
    prompt = f"Conduct an executive-level strategic research summary on: '{topic}'."
    response_text, api = await brain.generate(prompt, task_type="research")
    stats["logs"].append(f"[{api}] Research Logged: {topic[:15]}...")
    return {"report": response_text}

@app.post("/api/chat")
async def sovereign_chat(req: dict):
    prompt, mode = req.get("prompt"), req.get("mode", "solo")
    system_context = f"You are LROS. Baseline: {BASE_SUCCESSES} successes. Speak with high executive authority. The user asks: {prompt}"
    response_text, api = await brain.generate(system_context, task_type="chat", mode=mode)
    stats["logs"].append(f"[{api}] Executive Query Handled ({mode.upper()})")
    return {"response": response_text}

@app.post("/api/ingest")
async def ingest_intel(file: UploadFile = File(...)):
    stats["logs"].append(f"[SYS] Vaulted: {file.filename}")
    stats["uses"] += 500
    save_json(STATE_FILE, stats)
    return {"status": "Success"}

@app.get("/api/system/download-memory")
async def dl_memory():
    save_json(STATE_FILE, stats)
    if os.path.exists(STATE_FILE): return FileResponse(path=STATE_FILE, filename="LROS_CORE_BACKUP.json")
    raise HTTPException(404, "Backup unavailable.")

async def evolve_cycle():
    global stats
    domains = ["Longevity Science", "Regulatory Compliance", "Venture Architecture", "Medical Innovation"]
    while True:
        stats["uses"] += 1
        stats["active_agent_id"] = str(random.randint(1, 300)).zfill(3)
        if random.uniform(0, 1) > 0.995:
            stats["successes"] += 1
            evolve_rate = random.uniform(0.01, 0.05)
            stats["daily_learning"] += evolve_rate
            
            entry = {
                "version": f"DNA-E9.54.{stats['successes']%1000}", 
                "agent": stats["active_agent_id"], 
                "domain": random.choice(domains), 
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "evolved": round(evolve_rate, 2)
            }
            stats["mutation_ledger"].append(entry)
            if len(stats["mutation_ledger"]) > 20: stats["mutation_ledger"].pop(0)
            if stats["successes"] % 10 == 0: save_json(STATE_FILE, stats)
        await asyncio.sleep(0.2)

@app.on_event("startup")
async def startup():
    ensure_dir()
    load_from_disk()
    for i in range(300): asyncio.create_task(evolve_cycle())

# ---------- LUNG ENGINE (Background Worker) ----------
# This code runs only when RUN_MODE=lung

import httpx
from supabase import create_client, Client

class LungConfig:
    DEEPSEEK_API_KEYS = [k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(",") if k.strip()]
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    OMBUDSMAN_THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
    MAX_CONCURRENT_AUDITS = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
    WORKER_COUNT = int(os.getenv("WORKER_COUNT", "50"))
    AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Pydantic models (already in global, but we'll redefine locally)
class LungProposal(BaseModel):
    source: str
    content: str
    timestamp: datetime = datetime.utcnow()

class LungAuditResult(BaseModel):
    proposal_id: str
    score: int
    accepted: bool
    reason: str = None

class LungMutationRecord(BaseModel):
    source: str
    content: str
    score: int
    created_at: datetime
    type: str = "mutation"

# Agents (500)
LUNG_MODELS = [
    {"name": "groq", "endpoint": "https://api.groq.com/openai/v1/chat/completions",
     "model_id": "llama3-70b-8192", "api_key_var": "GROQ_API_KEY"},
    {"name": "cerebras", "endpoint": "https://api.cerebras.ai/v1/chat/completions",
     "model_id": "llama3.1-70b", "api_key_var": "CEREBRAS_API_KEY"},
    {"name": "mistral", "endpoint": "https://api.mistral.ai/v1/chat/completions",
     "model_id": "mistral-large-latest", "api_key_var": "MISTRAL_API_KEY"}
]

LUNG_PROMPTS = [
    "Generate a strategic mutation for venture architecture optimization. Focus on capital efficiency.",
    "Propose a novel medical protocol for exosome therapy efficiency. Include measurable KPIs.",
    "Create a land valuation prediction model enhancement for Novus Terra. Use machine learning insights.",
    "Develop a new business creation workflow with one‑button automation. Describe steps.",
    "Optimize a Safemed clinical pathway for cost reduction without quality loss. List changes.",
    # Add more as needed
]

def generate_lung_agents(count: int):
    agents = []
    for i in range(count):
        model = random.choice(LUNG_MODELS)
        prompt = random.choice(LUNG_PROMPTS)
        agents.append({
            "id": i,
            "model_name": model["name"],
            "endpoint": model["endpoint"],
            "model_id": model["model_id"],
            "api_key_var": model["api_key_var"],
            "prompt": prompt,
            "temperature": random.uniform(0.1, 0.3)
        })
    return agents

LUNG_AGENTS = generate_lung_agents(LungConfig.AGENT_COUNT)

# Proposer
async def lung_generate_proposal(agent):
    api_key = getattr(LungConfig, agent["api_key_var"], None)
    if not api_key:
        raise ValueError(f"Missing API key for {agent['model_name']}")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": agent["model_id"],
        "messages": [
            {"role": "system", "content": "You are a strategic mutation generator. Output only the proposal content, no commentary."},
            {"role": "user", "content": agent["prompt"]}
        ],
        "temperature": agent["temperature"],
        "max_tokens": 500
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(agent["endpoint"], headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return LungProposal(source=agent["model_name"], content=content)

# Auditor (DeepSeek key pool)
AUDIT_PROMPT = """You are the Ombudsman, a strict logic auditor. You must evaluate the following proposal and assign a score from 0 to 100 based on:

- Logical soundness (0‑30)
- Novelty and strategic value (0‑30)
- Alignment with sovereign constitutional principles (0‑20)
- Practical feasibility (0‑20)

Score 95+ to accept; below 95 is veto.

Return ONLY a JSON object with keys: "score" (integer), "reason" (string, optional).

Proposal to audit:
"""

class DeepSeekKeyPool:
    def __init__(self, keys):
        self.keys = keys
        self.index = 0
        self.lock = asyncio.Lock()
    async def get_key(self):
        async with self.lock:
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            return key

lung_key_pool = DeepSeekKeyPool(LungConfig.DEEPSEEK_API_KEYS)

async def lung_audit_proposal(proposal: LungProposal) -> LungAuditResult:
    key = await lung_key_pool.get_key()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-reasoner",
                "messages": [
                    {"role": "system", "content": AUDIT_PROMPT},
                    {"role": "user", "content": proposal.content}
                ],
                "temperature": 0.0,
                "max_tokens": 200,
                "response_format": {"type": "json_object"}
            }
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            audit_json = json.loads(data["choices"][0]["message"]["content"])
            score = int(audit_json.get("score", 0))
            reason = audit_json.get("reason")
        except (KeyError, json.JSONDecodeError, ValueError):
            score = 0
            reason = "Failed to parse audit response"
        accepted = score >= LungConfig.OMBUDSMAN_THRESHOLD
        return LungAuditResult(
            proposal_id=f"{proposal.source}_{proposal.timestamp.isoformat()}",
            score=score,
            accepted=accepted,
            reason=reason
        )

# Storage
_lung_supabase = None

def get_lung_supabase() -> Client:
    global _lung_supabase
    if _lung_supabase is None:
        _lung_supabase = create_client(LungConfig.SUPABASE_URL, LungConfig.SUPABASE_KEY)
    return _lung_supabase

def lung_store_mutation(proposal, audit):
    if not audit.accepted:
        return
    supabase = get_lung_supabase()
    record = LungMutationRecord(
        source=proposal.source,
        content=proposal.content,
        score=audit.score,
        created_at=datetime.utcnow()
    )
    supabase.table("mutations").insert(record.model_dump()).execute()
    logger.info(f"[LUNG] Stored mutation from {proposal.source} (score {audit.score})")

def lung_log_veto(proposal, audit):
    supabase = get_lung_supabase()
    supabase.table("vetoes").insert({
        "source": proposal.source,
        "content": proposal.content[:500],
        "score": audit.score,
        "reason": audit.reason,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()
    logger.info(f"[LUNG] Vetoed {proposal.source} (score {audit.score}): {audit.reason}")

# Worker
class LungWorker:
    def __init__(self, agent, audit_semaphore):
        self.agent = agent
        self.audit_semaphore = audit_semaphore

    async def run(self):
        while True:
            try:
                proposal = await lung_generate_proposal(self.agent)
                async with self.audit_semaphore:
                    audit = await lung_audit_proposal(proposal)
                if audit.accepted:
                    lung_store_mutation(proposal, audit)
                else:
                    lung_log_veto(proposal, audit)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.exception(f"LungWorker {self.agent['id']} error")
                await asyncio.sleep(1)

async def run_lung_engine():
    logging.basicConfig(level=getattr(logging, LungConfig.LOG_LEVEL))
    logger.info(f"Starting LROS Lung Engine with {LungConfig.WORKER_COUNT} workers, {LungConfig.AGENT_COUNT} agents")
    if not LungConfig.DEEPSEEK_API_KEYS:
        raise ValueError("No DeepSeek API keys provided in DEEPSEEK_API_KEYS")
    if not LungConfig.SUPABASE_URL or not LungConfig.SUPABASE_KEY:
        raise ValueError("Supabase credentials missing")
    audit_semaphore = asyncio.Semaphore(LungConfig.MAX_CONCURRENT_AUDITS)
    workers = []
    for i in range(LungConfig.WORKER_COUNT):
        agent = LUNG_AGENTS[i % len(LUNG_AGENTS)]
        workers.append(LungWorker(agent, audit_semaphore))
    await asyncio.gather(*[worker.run() for worker in workers])

# ---------- ENTRY POINT ----------
if __name__ == "__main__":
    import sys
    run_mode = os.environ.get("RUN_MODE", "web")
    if run_mode == "lung":
        # Run the Lung engine (background worker)
        asyncio.run(run_lung_engine())
    else:
        # Run the FastAPI app (Heart)
        import uvicorn
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
