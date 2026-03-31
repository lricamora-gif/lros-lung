#!/usr/bin/env python3
import os
import json
import random
import asyncio
import logging
from datetime import datetime

import httpx
from supabase import create_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Lung")

# --- Environment ---
DEEPSEEK_KEYS = [k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(",") if k.strip()]
GROQ_KEY = os.getenv("GROQ_API_KEY")
CEREBRAS_KEY = os.getenv("CEREBRAS_API_KEY")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "50"))
AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))

# --- Models (no Gemini) ---
MODELS = [
    {"name": "groq", "endpoint": "https://api.groq.com/openai/v1/chat/completions",
     "model_id": "llama3-70b-8192", "api_key": GROQ_KEY},
    {"name": "cerebras", "endpoint": "https://api.cerebras.ai/v1/chat/completions",
     "model_id": "llama3.1-70b", "api_key": CEREBRAS_KEY},
    {"name": "mistral", "endpoint": "https://api.mistral.ai/v1/chat/completions",
     "model_id": "mistral-large-latest", "api_key": MISTRAL_KEY}
]

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

async def generate_proposal(agent):
    headers = {"Authorization": f"Bearer {agent['model']['api_key']}"}
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
        resp = await client.post(agent["model"]["endpoint"], headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"source": agent["model"]["name"], "content": content, "timestamp": datetime.utcnow()}

AUDIT_PROMPT = """You are the Ombudsman. Score the following proposal 0‑100. Score 95+ to accept. Return JSON: {"score": int, "reason": str}.

Proposal:
"""

class KeyPool:
    def __init__(self, keys):
        self.keys = keys
        self.index = 0
        self.lock = asyncio.Lock()
    async def get(self):
        async with self.lock:
            k = self.keys[self.index % len(self.keys)]
            self.index += 1
            return k

key_pool = KeyPool(DEEPSEEK_KEYS)

async def audit_proposal(proposal):
    key = await key_pool.get()
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

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def store_mutation(proposal, audit):
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
            await asyncio.sleep(1)

async def main():
    logger.info(f"Lung starting: {WORKER_COUNT} workers, {AGENT_COUNT} agents")
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = []
    for i in range(WORKER_COUNT):
        agent = AGENTS[i % len(AGENTS)]
        tasks.append(asyncio.create_task(worker(agent, sem)))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
