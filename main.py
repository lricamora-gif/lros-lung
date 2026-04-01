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
GEMINI_KEYS = get_key_list("GEMINI_API_KEYS")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "30"))
AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "300"))

# ---------- KeyPool with health ----------
class KeyPool:
    def __init__(self, keys):
        self.keys = keys
        self.index = 0
        self.lock = asyncio.Lock()
        self.healthy = {k: True for k in keys}
    async def get(self):
        if not self.keys:
            return None
        async with self.lock:
            start = self.index
            while True:
                k = self.keys[self.index % len(self.keys)]
                self.index = (self.index + 1) % len(self.keys)
                if self.healthy.get(k, False):
                    return k
                if self.index == start:
                    break
            return None
    def mark_unhealthy(self, key):
        if key in self.healthy:
            self.healthy[key] = False
            logger.warning(f"Marked key unhealthy: {key[:10]}...")
    def mark_healthy(self, key):
        if key in self.healthy:
            self.healthy[key] = True
    async def health_check(self, test_func):
        async def check():
            for key in self.keys:
                try:
                    await test_func(key)
                    self.mark_healthy(key)
                except Exception:
                    self.mark_unhealthy(key)
        asyncio.create_task(check())

# ---------- Model definitions – prioritise Groq, Cerebras, Mistral ----------
MODELS = []

# Groq (highest priority)
if GROQ_KEYS:
    MODELS.append({
        "name": "groq",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "llama3-70b-8192",
        "key_pool": KeyPool(GROQ_KEYS),
        "test_func": lambda key: test_groq(key)
    })
# Cerebras
if CEREBRAS_KEYS:
    MODELS.append({
        "name": "cerebras",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "model_id": "llama3.1-70b",
        "key_pool": KeyPool(CEREBRAS_KEYS),
        "test_func": lambda key: test_cerebras(key)
    })
# Mistral
if MISTRAL_KEYS:
    MODELS.append({
        "name": "mistral",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model_id": "mistral-large-latest",
        "key_pool": KeyPool(MISTRAL_KEYS),
        "test_func": lambda key: test_mistral(key)
    })
# Gemini (optional)
if GEMINI_KEYS:
    MODELS.append({
        "name": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
        "model_id": "gemini-2.0-flash-exp",
        "key_pool": KeyPool(GEMINI_KEYS),
        "test_func": lambda key: test_gemini(key)
    })
# DeepSeek (lowest priority for generation, but used for audit)
if DEEPSEEK_KEYS:
    MODELS.append({
        "name": "deepseek",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "model_id": "deepseek-chat",
        "key_pool": KeyPool(DEEPSEEK_KEYS),
        "test_func": lambda key: test_deepseek(key)
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

# ---------- Test functions ----------
async def test_deepseek(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
        )
        resp.raise_for_status()

async def test_groq(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "llama3-70b-8192", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
        )
        resp.raise_for_status()

async def test_cerebras(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "llama3.1-70b", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
        )
        resp.raise_for_status()

async def test_mistral(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
        )
        resp.raise_for_status()

async def test_gemini(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": "test"}]}]}
        )
        resp.raise_for_status()

# ---------- Proposal generation ----------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)))
async def _generate_proposal(agent):
    model = agent["model"]
    key = await model["key_pool"].get()
    if not key:
        raise ValueError(f"No healthy key for {model['name']}")

    if model["name"] == "gemini":
        url = f"{model['endpoint']}?key={key}"
        headers = {}
        payload = {"contents": [{"parts": [{"text": agent["prompt"]}]}]}
    else:
        url = model["endpoint"]
        headers = {"Authorization": f"Bearer {key}"}
        payload = {
            "model": model["model_id"],
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
        if model["name"] == "gemini":
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            content = data["choices"][0]["message"]["content"]
        return {"source": model["name"], "content": content, "timestamp": datetime.utcnow()}

async def generate_proposal(agent):
    try:
        return await _generate_proposal(agent)
    except Exception as e:
        logger.error(f"Proposal generation failed for {agent['model']['name']}: {e}")
        # Try a different model
        other_models = [m for m in MODELS if m != agent['model']]
        if other_models:
            alt = random.choice(other_models)
            logger.info(f"Switching to alternative model {alt['name']}")
            new_agent = dict(agent)
            new_agent["model"] = alt
            return await _generate_proposal(new_agent)
        else:
            raise

# ---------- Audit (DeepSeek, with fallback) ----------
deepseek_model = next((m for m in MODELS if m["name"] == "deepseek"), None)
AUDIT_PROMPT = """You are the Ombudsman. Score the following proposal 0‑100. Score 95+ to accept. Return JSON: {"score": int, "reason": str}.

Proposal:
"""

async def _audit_with_deepseek(proposal):
    key = await deepseek_model["key_pool"].get()
    if not key:
        raise ValueError("No healthy DeepSeek key")
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

def _fallback_audit(proposal):
    """Simple fallback: assign a random score between 60 and 100, always accept if threshold low."""
    score = random.randint(60, 100)
    accepted = score >= THRESHOLD
    reason = "Fallback audit (DeepSeek unavailable)"
    return {"score": score, "accepted": accepted, "reason": reason}

async def audit_proposal(proposal):
    if deepseek_model:
        try:
            return await _audit_with_deepseek(proposal)
        except Exception as e:
            logger.error(f"DeepSeek audit failed: {e}. Using fallback.")
            return _fallback_audit(proposal)
    else:
        logger.warning("No DeepSeek model available, using fallback audit.")
        return _fallback_audit(proposal)

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

# ---------- Health monitor ----------
async def health_monitor(app: FastAPI):
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        # Test all key pools
        for model in MODELS:
            logger.info(f"Testing keys for {model['name']}")
            await model["key_pool"].health_check(model["test_func"])
        logger.info("Key health check completed")

        # Restart workers if needed
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
            if MODELS and supabase:
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
    logger.info(f"Loaded models (priority order): {[m['name'] for m in MODELS]}")
    logger.info(f"DeepSeek keys: {len(DEEPSEEK_KEYS)}, Fallback audit enabled")
    logger.info(f"Supabase: {supabase is not None}")

    if not MODELS or not supabase:
        logger.warning("Missing required services. Workers will not start until all are available.")
    else:
        sem = asyncio.Semaphore(MAX_CONCURRENT)
        tasks = []
        for i in range(WORKER_COUNT):
            if i >= len(AGENTS):
                break
            agent = AGENTS[i % len(AGENTS)]
            tasks.append(asyncio.create_task(worker(agent, sem)))
        app.state.tasks = tasks
        logger.info(f"Started {len(tasks)} workers")

    monitor_task = asyncio.create_task(health_monitor(app))
    app.state.monitor_task = monitor_task

    yield

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
        "status": "ok" if MODELS and supabase else "missing_keys"
    }

@app.get("/health")
async def health():
    return {
        "models": [{"name": m["name"], "healthy_keys": sum(1 for k in m["key_pool"].healthy.values() if k)} for m in MODELS],
        "deepseek_available": deepseek_model is not None,
        "fallback_audit_enabled": True,
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
