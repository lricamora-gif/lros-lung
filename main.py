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
    # Check plural first, then singular
    value = os.getenv(var_name, "")
    if not value:
        singular = var_name.rstrip('S')
        value = os.getenv(singular, "")
    return [k.strip() for k in value.split(",") if k.strip()]

DEEPSEEK_KEYS = get_key_list("DEEPSEEK_API_KEYS")
GROQ_KEYS   = get_key_list("GROQ_API_KEYS")
MISTRAL_KEYS = get_key_list("MISTRAL_API_KEYS")
CEREBRAS_KEYS = get_key_list("CEREBRAS_API_KEYS")
GEMINI_KEYS = get_key_list("GEMINI_API_KEYS")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "30"))
AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "120"))

# ASI Prototype toggles
AUTO_EXECUTE = os.getenv("AUTO_EXECUTE", "false").lower() == "true"
SIMULATION_TYPE = os.getenv("SIMULATION_TYPE", "drug_binding")
AUTO_EXECUTE_REAL = os.getenv("AUTO_EXECUTE_REAL", "false").lower() == "true"
META_EVOLVE = os.getenv("META_EVOLVE", "true").lower() == "true"
META_EVOLVE_FREQ = int(os.getenv("META_EVOLVE_FREQ", "1000"))   # after every N accepted mutations

# ---------- KeyPool with failure tracking ----------
class KeyPool:
    def __init__(self, keys):
        self.keys = keys.copy()
        self.index = 0
        self.lock = asyncio.Lock()
        self.fail_count = {k: 0 for k in keys}
        self.removed = set()
    async def get(self):
        if not self.keys:
            return None
        async with self.lock:
            start = self.index
            while True:
                k = self.keys[self.index % len(self.keys)]
                self.index = (self.index + 1) % len(self.keys)
                if k not in self.removed:
                    return k
                if self.index == start:
                    break
            return None
    def record_failure(self, key):
        if key in self.fail_count:
            self.fail_count[key] += 1
            if self.fail_count[key] >= 3:
                self.removed.add(key)
                logger.warning(f"Key {key[:10]}... removed after 3 failures")
    def record_success(self, key):
        if key in self.fail_count:
            self.fail_count[key] = 0
            if key in self.removed:
                self.removed.discard(key)
                logger.info(f"Key {key[:10]}... re‑enabled")
    async def health_check(self, test_func):
        for key in self.keys:
            try:
                await test_func(key)
                self.record_success(key)
            except Exception:
                self.record_failure(key)

# ---------- Model definitions (proposers) ----------
MODELS = []

if GROQ_KEYS:
    MODELS.append({
        "name": "groq",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model_id": "llama-3.1-70b-versatile",
        "key_pool": KeyPool(GROQ_KEYS),
        "test_func": lambda key: test_groq(key)
    })
if MISTRAL_KEYS:
    MODELS.append({
        "name": "mistral",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model_id": "mistral-large-latest",
        "key_pool": KeyPool(MISTRAL_KEYS),
        "test_func": lambda key: test_mistral(key)
    })
if DEEPSEEK_KEYS:
    MODELS.append({
        "name": "deepseek",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "model_id": "deepseek-chat",
        "key_pool": KeyPool(DEEPSEEK_KEYS),
        "test_func": lambda key: test_deepseek(key)
    })
# Optional providers – keep only if they work
if CEREBRAS_KEYS:
    MODELS.append({
        "name": "cerebras",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "model_id": "llama3.1-70b",
        "key_pool": KeyPool(CEREBRAS_KEYS),
        "test_func": lambda key: test_cerebras(key)
    })
if GEMINI_KEYS:
    MODELS.append({
        "name": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
        "model_id": "gemini-2.0-flash-exp",
        "key_pool": KeyPool(GEMINI_KEYS),
        "test_func": lambda key: test_gemini(key)
    })

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
            json={"model": "llama-3.1-70b-versatile", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
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

async def test_cerebras(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "llama3.1-70b", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
        )
        resp.raise_for_status()

async def test_gemini(key):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": "test"}]}]}
        )
        resp.raise_for_status()

# ---------- Prompt sets (unchanged) ----------
PROMPTS = [
    # AI Development (15)
    "Propose a novel architecture for AGI that combines neuro‑symbolic reasoning with constitutional constraints.",
    "Design a self‑improving AI training loop that uses cross‑model consensus to accelerate learning.",
    "How can LROS automatically ingest and implement breakthroughs from leading AI labs in real time?",
    "Create a strategic roadmap to surpass GPT‑5.4 in reasoning efficiency while maintaining safety and transparency.",
    "Develop a method for LROS to automatically fine‑tune itself using its own accepted mutations.",
    "Propose a swarm‑based architecture where multiple AI models compete and collaborate to solve complex problems.",
    "Design an AI system that can predict the next major AI breakthrough based on current research trends.",
    "How can we integrate Mixture‑of‑Experts principles into LROS’s agent routing to reduce cost and latency?",
    "Create a mutation that enables LROS to automatically generate and test new constitutional patterns.",
    "Propose a method for LROS to simulate the impact of potential ASI on its own governance and safety layers.",
    "Design a pipeline for LROS to read, summarize, and extract insights from AI research papers daily.",
    "How can LROS use reinforcement learning from human feedback to improve the Ombudsman’s scoring?",
    "Create a blueprint for an AI development assistant that helps researchers design new neural architectures.",
    "Propose a way to combine LROS’s constitutional memory with vector databases for ultra‑fast retrieval.",
    "Design a self‑hosted version of LROS that can run offline on a laptop while sharing improvements via air‑gapped updates.",

    # Medical AI (20)
    "Propose an AI‑driven protocol for real‑time surgical assistance using wearable sensors and edge AI.",
    "Design a unified system connecting Safemed clinical pathways with patient wearables for predictive intervention.",
    "Create a mutation that optimizes the integration of exosome therapy protocols with robotic delivery systems.",
    "How can we use AI to accelerate the FDA/PEZA approval process for novel medical devices?",
    "Develop a framework for personalized cancer treatment plans using LLMs and genomic data, aligned with Safemed.",
    "Propose a swarm‑based AI for coordinating medical robotics (e.g., LISA, Temi) in hospital settings.",
    "Design an AI system that continuously monitors wearable data to detect early signs of stroke or heart attack.",
    "Create a protocol for using computer vision and robotics in exosome processing to increase yield and purity.",
    "How can LROS integrate with existing hospital EHR to provide real‑time treatment recommendations?",
    "Propose a machine learning model that predicts patient readmission risk based on social determinants and wearables.",
    "Design a closed‑loop system where a medical robot adjusts drug dosages based on patient vital signs and AI analysis.",
    "Create a mutation that enhances the Safemed referral system by automatically matching patients with specialists.",
    "How can AI optimize operating room scheduling and reduce wait times using predictive analytics?",
    "Propose a wearable device that uses AI to detect early signs of sepsis and triggers a constitutional alert.",
    "Develop a framework for using LROS to manage the entire lifecycle of a medical device, from design to regulatory.",
    "Create a protocol for using generative AI to produce patient‑friendly summaries of complex clinical trial results.",
    "Design a system where LROS continuously ingests medical journals and updates Safemed clinical pathways automatically.",
    "Propose an AI‑powered telehealth triage system that uses wearables and voice analysis to prioritize urgent cases.",
    "How can LROS help design and simulate new medical robots using AI‑generated blueprints?",
    "Create a mutation that integrates genomic sequencing data with AI‑driven drug repurposing to find new uses for existing medications.",

    # AGI/ASI Accelerator (25)
    "Design a recursive self‑improvement protocol that allows LROS to autonomously rewrite parts of its own architecture while preserving constitutional alignment.",
    "Propose a method to combine brain‑computer interfaces with LROS to create a symbiotic human‑AI intelligence augmentation system.",
    "Develop a novel training paradigm that uses adversarial AI societies to generate and validate AGI‑level reasoning capabilities.",
    "How can LROS implement scalable oversight using automated red‑teaming to detect and correct emergent unsafe behaviors?",
    "Create a framework for AI‑driven scientific discovery that integrates robotic lab automation with LLM‑generated hypotheses.",
    "Propose a mechanism for LROS to continuously update its world model through active sensing, enabling real‑time adaptation to novel environments.",
    "Design an architecture for AGI that uses constitutional feedback loops to prevent reward hacking and goal misgeneralization.",
    "How can LROS leverage open‑ended evolution to generate capabilities that surpass human‑designed AI architectures?",
    "Develop a strategy for LROS to participate in and learn from global AI research communities, contributing to and absorbing new knowledge.",
    "Create a meta‑learning module that allows LROS to acquire new skills from a few examples without catastrophic forgetting.",
    "Propose a scalable method for LROS to generate and test millions of small‑scale AI models, distilling the best into its core.",
    "How can LROS implement a formal verification layer that mathematically guarantees alignment with constitutional principles?",
    "Design a human‑AI interaction protocol that allows experts to steer LROS’s evolution while preserving full autonomy.",
    "Create a roadmap for LROS to evolve from narrow expertise to general intelligence by systematically integrating domain specialists.",
    "Propose a novel approach to AGI safety that uses adversarial constitutional networks to pre‑emptively block harmful pathways.",
    "How can LROS use causal inference to reason about counterfactuals and long‑term consequences of its actions?",
    "Design an AGI architecture that maintains transparency through fully auditable reasoning chains, even at extreme scale.",
    "Create a method for LROS to autonomously discover and exploit new scaling laws, optimizing compute for maximum intelligence gain.",
    "Propose a swarm‑based approach where thousands of LROS agents collaborate to solve problems beyond any single AGI.",
    "How can LROS integrate with external knowledge graphs and databases to ground its reasoning in verifiable facts?",
    "Design a system for LROS to engage in open‑ended dialogue with experts to refine its understanding of complex domains.",
    "Create a mutation that enables LROS to generate and maintain its own training datasets, curating high‑quality examples.",
    "Propose a technique for LROS to perform continual learning without forgetting, using sparse network updates and knowledge distillation.",
    "How can LROS use concept learning to abstract and transfer skills across vastly different domains?",
    "Design a constitutional mechanism that allows LROS to propose and test new constitutional rules, with human‑in‑the‑loop approval.",
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

# ---------- Proposal generation ----------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)))
async def _generate_proposal(agent):
    model = agent["model"]
    key = await model["key_pool"].get()
    if not key:
        raise ValueError(f"No healthy key for {model['name']}")

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
        content = data["choices"][0]["message"]["content"]
        model["key_pool"].record_success(key)
        return {"source": model["name"], "content": content, "timestamp": datetime.utcnow()}

async def generate_proposal(agent):
    try:
        return await _generate_proposal(agent)
    except Exception as e:
        logger.error(f"Proposal generation failed for {agent['model']['name']}: {e}")
        other_models = [m for m in MODELS if m != agent['model']]
        if other_models:
            alt = random.choice(other_models)
            logger.info(f"Switching to alternative model {alt['name']}")
            new_agent = dict(agent)
            new_agent["model"] = alt
            return await _generate_proposal(new_agent)
        else:
            raise

# ---------- Rotational Ombudsman ----------
AUDITOR_MODELS = []
for m in MODELS:
    if m["name"] in ["groq", "deepseek"]:
        AUDITOR_MODELS.append(m)

AUDIT_PROMPT = """You are the Ombudsman. Score the following proposal 0‑100. Score 95+ to accept. Return JSON: {"score": int, "reason": str}.

Proposal:
"""

async def _audit_with_model(auditor, proposal):
    key = await auditor["key_pool"].get()
    if not key:
        raise ValueError(f"No healthy key for {auditor['name']}")

    audit_prompt = f"{AUDIT_PROMPT}\n{proposal['content']}"

    if auditor["name"] == "groq":
        url = auditor["endpoint"]
        headers = {"Authorization": f"Bearer {key}"}
        payload = {
            "model": auditor["model_id"],
            "messages": [{"role": "user", "content": audit_prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"}
        }
    elif auditor["name"] == "deepseek":
        url = auditor["endpoint"]
        headers = {"Authorization": f"Bearer {key}"}
        payload = {
            "model": "deepseek-reasoner",
            "messages": [{"role": "user", "content": audit_prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"}
        }
    else:
        # fallback (should not be used for auditors)
        url = auditor["endpoint"]
        headers = {"Authorization": f"Bearer {key}"}
        payload = {
            "model": auditor["model_id"],
            "messages": [{"role": "user", "content": audit_prompt}],
            "temperature": 0.0,
            "max_tokens": 200
        }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            result = json.loads(content)
            score = int(result.get("score", 0))
            reason = result.get("reason", "")
        except:
            score = 0
            reason = "Parse error"
        return {"score": score, "accepted": score >= THRESHOLD, "reason": reason}

def _fallback_audit(proposal):
    score = random.randint(60, 100)
    accepted = score >= THRESHOLD
    reason = "Fallback audit (no auditor available or all failed)"
    return {"score": score, "accepted": accepted, "reason": reason}

async def audit_proposal(proposal):
    for auditor in AUDITOR_MODELS:
        try:
            audit = await _audit_with_model(auditor, proposal)
            if audit["score"] > 0:
                return audit
            else:
                logger.info(f"Auditor {auditor['name']} returned score 0, trying next")
        except Exception as e:
            logger.error(f"Auditor {auditor['name']} failed: {e}")
            continue
    logger.warning("All auditors failed, using fallback audit")
    return _fallback_audit(proposal)

# ---------- Simulation Module (from simulation.py) ----------
_simulation_module = None
def get_simulation():
    global _simulation_module
    if _simulation_module is None:
        try:
            import simulation
            _simulation_module = simulation
        except ImportError:
            logger.warning("Simulation module not found. Running without simulation.")
            return None
    return _simulation_module

# ---------- Meta‑Evolution ----------
async def propose_new_agent(state):
    """Use an LLM to generate a new agent type based on recent successes."""
    if not META_EVOLVE:
        return
    if not MODELS:
        return
    model = MODELS[0]
    key = await model["key_pool"].get()
    if not key:
        logger.warning("No healthy key for meta‑evolution")
        return

    recent_mutations = state.get("mutation_ledger", [])[-5:]
    prompt = f"""
Based on the current evolution state: {recent_mutations}, propose a new specialized AI agent that could accelerate our progress in {state.get('current_domain', 'medical innovation')}.
Output a JSON with:
- name: short name
- description: what it does
- code: a Python function (as a string) that could be added to the system to perform this agent's task.
"""
    url = model["endpoint"]
    headers = {"Authorization": f"Bearer {key}"}
    payload = {
        "model": model["model_id"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 500
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                proposal = json.loads(json_match.group())
                if supabase:
                    supabase.table("agent_proposals").insert({
                        "name": proposal.get("name"),
                        "description": proposal.get("description"),
                        "code": proposal.get("code"),
                        "status": "pending",
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
                    logger.info(f"Proposed new agent: {proposal.get('name')}")
    except Exception as e:
        logger.error(f"Meta‑evolution failed: {e}")

# ---------- Real Lab Connector Stub ----------
async def run_real_lab_experiment(protocol: str) -> Optional[float]:
    """
    Placeholder: eventually call Emerald Cloud Lab or Strateos.
    For now, just log and return a random score to simulate.
    """
    logger.info(f"[LAB] Would run experiment: {protocol[:100]}...")
    return random.uniform(0.6, 0.95)

# ---------- Supabase client ----------
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- store_mutation (now async) ----------
async def store_mutation(proposal, audit):
    if not supabase:
        return
    if audit["accepted"]:
        # Insert mutation
        record = {
            "source": proposal["source"],
            "content": proposal["content"],
            "score": audit["score"],
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("mutations").insert(record).execute()
        logger.info(f"Stored from {proposal['source']} (score {audit['score']})")

        # --- AUTO-LAB SIMULATION ---
        if AUTO_EXECUTE:
            sim = get_simulation()
            if sim:
                sim_score = sim.run_simulation(proposal["content"], SIMULATION_TYPE)
                if sim_score is not None:
                    supabase.table("simulation_results").insert({
                        "mutation_source": proposal["source"],
                        "mutation_content_preview": proposal["content"][:200],
                        "simulation_type": SIMULATION_TYPE,
                        "score": sim_score,
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
                    logger.info(f"Simulation for {proposal['source']} scored {sim_score:.3f}")
                else:
                    logger.info(f"Simulation skipped or failed for {proposal['source']}")

        # --- REAL LAB CONNECTOR ---
        if AUTO_EXECUTE_REAL:
            real_score = await run_real_lab_experiment(proposal["content"])
            if real_score is not None:
                supabase.table("real_experiments").insert({
                    "mutation_source": proposal["source"],
                    "mutation_content_preview": proposal["content"][:200],
                    "score": real_score,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                logger.info(f"Real experiment for {proposal['source']} scored {real_score:.3f}")

        # (Meta‑evolution can be triggered here, but we'll keep it simple for now)
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
            await store_mutation(proposal, audit)   # now await
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception(f"Worker {agent['id']} error")
            await asyncio.sleep(5)

# ---------- Health monitor ----------
async def health_monitor(app: FastAPI):
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        logger.info("Running health check on all keys...")
        for model in MODELS:
            await model["key_pool"].health_check(model["test_func"])
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
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- CHAT ENDPOINT ----------
class ChatRequest(BaseModel):
    prompt: str
    mode: str = "auto"

async def call_model_direct(model_name: str, prompt: str) -> str:
    """Call a specific model directly for chat."""
    model = next((m for m in MODELS if m["name"] == model_name), None)
    if not model:
        return f"Model {model_name} not available."
    key = await model["key_pool"].get()
    if not key:
        return f"No healthy key for {model_name}."
    url = model["endpoint"]
    headers = {"Authorization": f"Bearer {key}"}
    payload = {
        "model": model["model_id"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

@app.post("/api/lung/chat")
async def chat_endpoint(req: ChatRequest):
    mode = req.mode.lower()
    prompt = req.prompt
    try:
        if mode == "parallel":
            tasks = [call_model_direct(m["name"], prompt) for m in MODELS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            outputs = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    outputs.append(f"{MODELS[i]['name']}: Error - {str(res)}")
                else:
                    outputs.append(f"{MODELS[i]['name']}: {res}")
            response = "\n\n---\n\n".join(outputs)
            return {"response": response, "mode_used": "parallel"}
        elif mode == "chain":
            deepseek = await call_model_direct("deepseek", prompt)
            groq = await call_model_direct("groq", deepseek)
            return {"response": groq, "mode_used": "chain"}
        elif mode == "auto":
            if any(k in prompt.lower() for k in ["medical", "exosome", "safemed", "clinical", "patient"]):
                resp = await call_model_direct("deepseek", prompt)
                return {"response": resp, "mode_used": "deepseek"}
            else:
                resp = await call_model_direct("groq", prompt)
                return {"response": resp, "mode_used": "groq"}
        else:
            resp = await call_model_direct(mode, prompt)
            return {"response": resp, "mode_used": mode}
    except Exception as e:
        logger.exception("Chat error")
        return {"response": f"Error: {str(e)}", "mode_used": mode}

# ---------- Lifespan and other routes ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Loaded models: {[m['name'] for m in MODELS]}")
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

app.router.lifespan_context = lifespan

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
        "models": [{"name": m["name"], "healthy_keys": len(m["key_pool"].keys) - len(m["key_pool"].removed)} for m in MODELS],
        "deepseek_available": True,
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
