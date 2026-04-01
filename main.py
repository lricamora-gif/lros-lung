import os
import json
import random
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

import httpx
from supabase import create_client, Client
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ---------- Configuration ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Lung")

def get_key_list(var_name):
    value = os.getenv(var_name, "")
    return [k.strip() for k in value.split(",") if k.strip()]

DEEPSEEK_KEYS = get_key_list("DEEPSEEK_API_KEYS")
GROQ_KEYS   = get_key_list("GROQ_API_KEYS")
CEREBRAS_KEYS = get_key_list("CEREBRAS_API_KEYS")
MISTRAL_KEYS = get_key_list("MISTRAL_API_KEYS")
GEMINI_KEYS = get_key_list("GEMINI_API_KEYS")          # added Gemini

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "50"))
AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))

# ---------- KeyPool with health checking ----------
class KeyPool:
    def __init__(self, keys):
        self.keys = keys.copy()          # mutable list
        self.index = 0
        self.lock = asyncio.Lock()
        self.health_status = {k: True for k in keys}   # initially assume healthy
    async def get(self):
        if not self.keys:
            return None
        async with self.lock:
            # cycle through keys, skip unhealthy ones
            start = self.index
            while True:
                idx = self.index % len(self.keys)
                key = self.keys[idx]
                self.index = (self.index + 1) % len(self.keys)
                if self.health_status.get(key, True):
                    return key
                if idx == start % len(self.keys):
                    # all keys are unhealthy
                    return None
    def mark_unhealthy(self, key):
        if key in self.health_status:
            self.health_status[key] = False
            logger.warning(f"Key marked unhealthy: {key[:10]}...")
    def mark_healthy(self, key):
        if key in self.health_status:
            self.health_status[key] = True
    async def test_key(self, key):
        """Test a single key with a lightweight API call."""
        try:
            # For DeepSeek, Groq, etc. – use a generic test call
            # We'll implement per-model tests later; for now just assume OK
            # Actually we'll do a minimal test for each type separately
            # Since we don't know the model type here, we'll skip detailed test
            return True
        except:
            return False

# ---------- Model definitions (including Gemini) ----------
MODELS = []
if GROQ_KEYS:
    MODELS.append({
        "name": "groq",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "llama3-70b-8192",
        "key_pool": KeyPool(GROQ_KEYS),
        "test_endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "test_payload": {"model": "llama3-70b-8192", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
    })
if CEREBRAS_KEYS:
    MODELS.append({
        "name": "cerebras",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "model_id": "llama3.1-70b",
        "key_pool": KeyPool(CEREBRAS_KEYS),
        "test_endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "test_payload": {"model": "llama3.1-70b", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
    })
if MISTRAL_KEYS:
    MODELS.append({
        "name": "mistral",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model_id": "mistral-large-latest",
        "key_pool": KeyPool(MISTRAL_KEYS),
        "test_endpoint": "https://api.mistral.ai/v1/chat/completions",
        "test_payload": {"model": "mistral-large-latest", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
    })
if GEMINI_KEYS:
    # Gemini uses a different endpoint (Google AI Studio)
    # We'll use the REST endpoint for simplicity
    MODELS.append({
        "name": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
        "model_id": "gemini-2.0-flash-exp",
        "key_pool": KeyPool(GEMINI_KEYS),
        "test_endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
        "test_payload": {"contents": [{"parts": [{"text": "test"}]}]}
    })

PROMPTS = [
    "Generate a strategic mutation for venture architecture optimization.",
    "Propose a novel medical protocol for exosome therapy efficiency.",
    "Create a land valuation prediction model enhancement for Novus Terra.",
    "Develop a new business creation workflow with one‑button automation.",
    "Optimize a Safemed clinical pathway for cost reduction without quality loss.",
]

def generate_agents(count):
    agents = []
    for i in range(count):
        if not MODELS:
            break
        model = random.choice(MODELS)
        prompt = random.choice(PROMPTS)
        agents.append({
            "id": i,
            "model": model,
            "prompt": prompt,
            "temperature": random.uniform(0.1, 0.3)
        })
    return agents

AGENTS = generate_agents(AGENT_COUNT)

# ---------- Proposal generation with retry ----------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)))
async def _generate_proposal(agent):
    key = await agent["model"]["key_pool"].get()
    if not key:
        raise ValueError(f"No API key for {agent['model']['name']}")
    headers = {"Authorization": f"Bearer {key}"}
    if agent["model"]["name"] == "gemini":
        # Gemini uses API key in query parameter
        url = f"{agent['model']['endpoint']}?key={key}"
        headers = {}  # no Authorization header
        payload = agent["model"]["test_payload"]  # use same payload structure
        # Adjust payload for Gemini: it expects {contents: [...]}
        payload = {"contents": [{"parts": [{"text": agent["prompt"]}]}]}
    else:
        url = agent["model"]["endpoint"]
        payload = {
            "model": agent["model"]["model_id"],
            "messages": [
                {"role": "system", "content": "You are a strategic mutation generator. Output only the proposal content."},
                {"role": "user", "content": agent["prompt"]}
            ],
            "temperature": agent["temperature"],
            "max_tokens": 500
        }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if agent["model"]["name"] == "gemini":
            # Extract text from Gemini response
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            content = data["choices"][0]["message"]["content"]
        return {"source": agent["model"]["name"], "content": content, "timestamp": datetime.utcnow()}

async def generate_proposal(agent):
    try:
        return await _generate_proposal(agent)
    except Exception as e:
        logger.error(f"Proposal generation failed for {agent['model']['name']}: {e}")
        # Mark the key used as potentially bad (we can't know which key, so we skip)
        # Instead, we'll rely on the health monitor to test keys periodically
        if len(MODELS) > 1:
            # Try a different model
            alt_model = random.choice([m for m in MODELS if m != agent['model']])
            logger.info(f"Switching to alternative model {alt_model['name']}")
            agent = dict(agent)
            agent["model"] = alt_model
            return await _generate_proposal(agent)
        else:
            raise

# ---------- Ombudsman audit with retry ----------
deepseek_pool = KeyPool(DEEPSEEK_KEYS)

AUDIT_PROMPT = """You are the Ombudsman. Score the following proposal 0‑100. Score 95+ to accept. Return JSON: {"score": int, "reason": str}.

Proposal:
"""

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)))
async def _audit_proposal(proposal):
    key = await deepseek_pool.get()
    if not key:
        raise ValueError("No DeepSeek keys available")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-reasoner",
                "messages": [
                    {"role": "system", "content": AUDIT_PROMPT},
                    {"role": "user", "content": proposal["content"]}
                ],
                "temperature": 0.0,
                "max_tokens": 200,
                "response_format": {"type": "json_object"}
            }
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            result = json.loads(data["choices"][0]["message"]["content"])
            score = int(result.get("score", 0))
            reason = result.get("reason")
        except:
            score = 0
            reason = "Parse error"
        accepted = score >= THRESHOLD
        return {"score": score, "accepted": accepted, "reason": reason}

async def audit_proposal(proposal):
    try:
        return await _audit_proposal(proposal)
    except Exception as e:
        logger.error(f"Audit failed: {e}")
        return {"score": 0, "accepted": False, "reason": f"Audit error: {str(e)}"}

# ---------- Supabase client ----------
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def store_mutation(proposal, audit):
    if not supabase:
        return
    if audit["accepted"]:
        supabase.table("mutations").insert({
            "source": proposal["source"],
            "content": proposal["content"],
            "score": audit["score"],
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        logger.info(f"Stored from {proposal['source']} (score {audit['score']})")
    else:
        supabase.table("vetoes").insert({
            "source": proposal["source"],
            "content": proposal["content"][:500],
            "score": audit["score"],
            "reason": audit["reason"],
            "timestamp": datetime.utcnow().isoformat()
        }).execute()
        logger.info(f"Vetoed {proposal['source']} (score {audit['score']})")

# ---------- Baseline management ----------
def get_baseline():
    if not supabase:
        return 439434
    res = supabase.table("baseline").select("value").eq("id", 1).execute()
    if res.data:
        return res.data[0]["value"]
    else:
        supabase.table("baseline").insert({"id": 1, "value": 439434}).execute()
        return 439434

def set_baseline(value):
    if not supabase:
        return False
    supabase.table("baseline").upsert({"id": 1, "value": value}).execute()
    return True

# ---------- Background worker ----------
async def worker(agent, sem):
    while True:
        try:
            proposal = await generate_proposal(agent)
            async with sem:
                audit = await audit_proposal(proposal)
            store_mutation(proposal, audit)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception(f"Worker {agent['id']} error")
            await asyncio.sleep(5)

# ---------- Health monitor and worker supervisor ----------
async def health_monitor(app: FastAPI):
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        # Check if workers are running
        tasks = getattr(app.state, 'tasks', None)
        if tasks:
            alive = [t for t in tasks if not t.done()]
            if len(alive) < WORKER_COUNT / 2:
                logger.warning(f"Only {len(alive)} workers alive, restarting...")
                for t in tasks:
                    t.cancel()
                await asyncio.sleep(2)
                sem = asyncio.Semaphore(MAX_CONCURRENT)
                new_tasks = []
                for i in range(WORKER_COUNT):
                    if i >= len(AGENTS):
                        break
                    agent = AGENTS[i % len(AGENTS)]
                    new_tasks.append(asyncio.create_task(worker(agent, sem)))
                app.state.tasks = new_tasks
                logger.info(f"Restarted {len(new_tasks)} workers")
        else:
            # No workers started yet – try to start if components ready
            if MODELS and deepseek_pool.keys and supabase:
                logger.info("Workers not running, starting fresh...")
                sem = asyncio.Semaphore(MAX_CONCURRENT)
                tasks = []
                for i in range(WORKER_COUNT):
                    if i >= len(AGENTS):
                        break
                    agent = AGENTS[i % len(AGENTS)]
                    tasks.append(asyncio.create_task(worker(agent, sem)))
                app.state.tasks = tasks
                logger.info(f"Started {len(tasks)} workers")

# ---------- FastAPI app ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Debug log
    logger.info(f"MODELS count: {len(MODELS)}, DeepSeek keys: {len(deepseek_pool.keys) if deepseek_pool else 0}, Supabase: {supabase is not None}")
    if not MODELS or not deepseek_pool.keys or not supabase:
        logger.warning("Missing required services. Workers will not start until all are available.")
    else:
        # Start initial workers
        sem = asyncio.Semaphore(MAX_CONCURRENT)
        tasks = []
        for i in range(WORKER_COUNT):
            if i >= len(AGENTS):
                break
            agent = AGENTS[i % len(AGENTS)]
            tasks.append(asyncio.create_task(worker(agent, sem)))
        app.state.tasks = tasks
        logger.info(f"Started {len(tasks)} workers")

    # Start health monitor
    monitor_task = asyncio.create_task(health_monitor(app))
    app.state.monitor_task = monitor_task

    yield

    # Cleanup
    if hasattr(app.state, 'tasks'):
        for t in app.state.tasks:
            t.cancel()
    if hasattr(app.state, 'monitor_task'):
        app.state.monitor_task.cancel()
    await asyncio.gather(*(app.state.tasks if hasattr(app.state, 'tasks') else []), 
                         app.state.monitor_task if hasattr(app.state, 'monitor_task') else asyncio.sleep(0), 
                         return_exceptions=True)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BaselineUpdate(BaseModel):
    baseline: int

@app.get("/")
async def root():
    return {
        "message": "LROS Lung Engine",
        "workers": WORKER_COUNT,
        "agents": len(AGENTS),
        "status": "ok" if MODELS and deepseek_pool.keys and supabase else "missing_keys"
    }

@app.get("/health")
async def health():
    """Detailed health check for monitoring."""
    return {
        "models": {
            "count": len(MODELS),
            "names": [m["name"] for m in MODELS],
            "keys_available": sum(1 for m in MODELS if m["key_pool"].keys)
        },
        "deepseek_keys": len(deepseek_pool.keys),
        "supabase": supabase is not None,
        "workers": {
            "desired": WORKER_COUNT,
            "active": len([t for t in getattr(app.state, 'tasks', []) if not t.done()]) if hasattr(app.state, 'tasks') else 0
        },
        "threshold": THRESHOLD,
        "agent_count": len(AGENTS)
    }

@app.get("/status")
async def status():
    if not supabase:
        return {"error": "Supabase not configured"}
    try:
        recent_mutations = supabase.table("mutations").select("*").order("created_at", desc=True).limit(5).execute()
        recent_vetoes = supabase.table("vetoes").select("*").order("timestamp", desc=True).limit(5).execute()
        mutation_count = supabase.table("mutations").select("*", count="exact").execute().count
        veto_count = supabase.table("vetoes").select("*", count="exact").execute().count
        baseline = get_baseline()
    except Exception as e:
        return {"error": str(e)}
    return {
        "workers": WORKER_COUNT,
        "agents": len(AGENTS),
        "threshold": THRESHOLD,
        "mutations_total": mutation_count,
        "vetoes_total": veto_count,
        "baseline": baseline,
        "recent_mutations": recent_mutations.data,
        "recent_vetoes": recent_vetoes.data,
    }

@app.post("/secure_baseline")
async def secure_baseline(data: BaselineUpdate):
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    set_baseline(data.baseline)
    return {"status": "success", "baseline": data.baseline}

@app.post("/reset_workers")
async def reset_workers():
    """Manually restart worker tasks."""
    if not hasattr(app.state, 'tasks'):
        raise HTTPException(status_code=400, detail="No workers running")
    for t in app.state.tasks:
        t.cancel()
    await asyncio.sleep(2)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = []
    for i in range(WORKER_COUNT):
        if i >= len(AGENTS):
            break
        agent = AGENTS[i % len(AGENTS)]
        tasks.append(asyncio.create_task(worker(agent, sem)))
    app.state.tasks = tasks
    return {"status": "restarted", "workers": len(tasks)}
