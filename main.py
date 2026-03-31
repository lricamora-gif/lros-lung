#!/usr/bin/env python3
"""
LROS Lung Engine – 500‑Agent Swarm with 50 Parallel Self‑Play Workers
Ombudsman: DeepSeek Reasoner (multi‑key)
Storage: Supabase (mutations & vetoes)
Promotion: Active – accepted mutations are anchored to the sovereign ledger
"""

import os
import asyncio
import json
import random
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import httpx
from supabase import create_client, Client
from pydantic import BaseModel, Field

# ------------------------------
# Configuration
# ------------------------------
load_dotenv()

class Config:
    # DeepSeek keys (comma separated)
    DEEPSEEK_API_KEYS = [k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(",") if k.strip()]
    # Model keys
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    # Lung parameters
    OMBUDSMAN_THRESHOLD = int(os.getenv("OMBUDSMAN_THRESHOLD", "95"))
    MAX_CONCURRENT_AUDITS = int(os.getenv("MAX_CONCURRENT_AUDITS", "10"))
    WORKER_COUNT = int(os.getenv("WORKER_COUNT", "50"))
    AGENT_COUNT = int(os.getenv("AGENT_COUNT", "500"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    # Optional: set to "debug" to see full proposal content
    LOG_PROPOSALS = os.getenv("LOG_PROPOSALS", "false").lower() == "true"

# ------------------------------
# Models (Pydantic)
# ------------------------------
class Proposal(BaseModel):
    source: str          # model name (groq, cerebras, mistral)
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class AuditResult(BaseModel):
    proposal_id: str
    score: int
    accepted: bool
    reason: Optional[str] = None

class MutationRecord(BaseModel):
    source: str
    content: str
    score: int
    created_at: datetime
    type: str = "mutation"

# ------------------------------
# Agent definitions (500)
# ------------------------------
MODELS = [
    {"name": "groq", "endpoint": "https://api.groq.com/openai/v1/chat/completions",
     "model_id": "llama3-70b-8192", "api_key_var": "GROQ_API_KEY"},
    {"name": "cerebras", "endpoint": "https://api.cerebras.ai/v1/chat/completions",
     "model_id": "llama3.1-70b", "api_key_var": "CEREBRAS_API_KEY"},
    {"name": "mistral", "endpoint": "https://api.mistral.ai/v1/chat/completions",
     "model_id": "mistral-large-latest", "api_key_var": "MISTRAL_API_KEY"}
]

PROMPT_TEMPLATES = [
    "Generate a strategic mutation for venture architecture optimization. Focus on capital efficiency.",
    "Propose a novel medical protocol for exosome therapy efficiency. Include measurable KPIs.",
    "Create a land valuation prediction model enhancement for Novus Terra. Use machine learning insights.",
    "Develop a new business creation workflow with one‑button automation. Describe steps.",
    "Optimize a Safemed clinical pathway for cost reduction without quality loss. List changes.",
    "Suggest a novel way to integrate AI diagnostics with patient triage.",
    "Propose a smart contract structure for tokenized real estate syndication.",
    "Design a swarm‑based learning algorithm for autonomous medical record analysis.",
    "Outline a competitive absorption strategy for a small health tech startup.",
    "Create a constitutional clause to prevent AI drift in autonomous decision systems.",
    "Generate a protocol for cross‑instance learning across sovereign AI nodes.",
    "Propose a zero‑knowledge proof system for patient data consent.",
    "Design a predictive maintenance schedule for autonomous drone fleets.",
    "Outline a one‑button corporate entity creation flow with legal wrappers.",
    "Suggest a novel approach to palliative care coordination using AI agents.",
    "Create a tokenomics model for a health data marketplace.",
    "Propose a method to detect and block AI hallucinations in real‑time.",
    "Design a constitutional audit layer for autonomous financial transactions.",
    "Generate a mutation that reduces latency in multi‑agent consensus protocols.",
    "Outline a strategy for ingesting and synthesizing medical journals at scale.",
]

def generate_agents(count: int) -> List[Dict[str, Any]]:
    agents = []
    for i in range(count):
        model = random.choice(MODELS)
        prompt = random.choice(PROMPT_TEMPLATES)
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

AGENTS = generate_agents(Config.AGENT_COUNT)

# ------------------------------
# Proposer: generate proposal from agent
# ------------------------------
async def generate_proposal(agent: Dict[str, Any]) -> Proposal:
    api_key = getattr(Config, agent["api_key_var"], None)
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
        if Config.LOG_PROPOSALS:
            logging.debug(f"Proposal from {agent['model_name']}: {content[:200]}...")
        return Proposal(source=agent["model_name"], content=content)

# ------------------------------
# Auditor: DeepSeek Ombudsman with key pool
# ------------------------------
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
    def __init__(self, keys: List[str]):
        self.keys = keys
        self.index = 0
        self.lock = asyncio.Lock()
    async def get_key(self):
        async with self.lock:
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            return key

key_pool = DeepSeekKeyPool(Config.DEEPSEEK_API_KEYS)

async def audit_proposal(proposal: Proposal) -> AuditResult:
    key = await key_pool.get_key()
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
        accepted = score >= Config.OMBUDSMAN_THRESHOLD
        if Config.LOG_PROPOSALS:
            logging.debug(f"Audit: score={score}, accepted={accepted}")
        return AuditResult(
            proposal_id=f"{proposal.source}_{proposal.timestamp.isoformat()}",
            score=score,
            accepted=accepted,
            reason=reason
        )

# ------------------------------
# Storage: Supabase
# ------------------------------
_supabase: Optional[Client] = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _supabase

def store_mutation(proposal: Proposal, audit: AuditResult):
    if not audit.accepted:
        return
    supabase = get_supabase()
    record = MutationRecord(
        source=proposal.source,
        content=proposal.content,
        score=audit.score,
        created_at=datetime.utcnow()
    )
    supabase.table("mutations").insert(record.model_dump()).execute()
    logging.info(f"Stored mutation from {proposal.source} (score {audit.score})")

def log_veto(proposal: Proposal, audit: AuditResult):
    supabase = get_supabase()
    supabase.table("vetoes").insert({
        "source": proposal.source,
        "content": proposal.content[:500],
        "score": audit.score,
        "reason": audit.reason,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()
    logging.info(f"Vetoed {proposal.source} (score {audit.score}): {audit.reason}")

# ------------------------------
# Self‑Play Worker
# ------------------------------
class SelfPlayWorker:
    def __init__(self, agent: Dict[str, Any], audit_semaphore: asyncio.Semaphore):
        self.agent = agent
        self.audit_semaphore = audit_semaphore

    async def run(self):
        while True:
            try:
                proposal = await generate_proposal(self.agent)
                async with self.audit_semaphore:
                    audit = await audit_proposal(proposal)
                if audit.accepted:
                    store_mutation(proposal, audit)
                else:
                    log_veto(proposal, audit)
                # Small delay to avoid overwhelming APIs
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.exception(f"Worker {self.agent['id']} error")
                await asyncio.sleep(1)

# ------------------------------
# Main Entry Point
# ------------------------------
async def main():
    logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))
    logger = logging.getLogger(__name__)
    logger.info(f"Starting LROS Lung Engine with {Config.WORKER_COUNT} workers, {Config.AGENT_COUNT} agents")
    
    if not Config.DEEPSEEK_API_KEYS:
        raise ValueError("No DeepSeek API keys provided in DEEPSEEK_API_KEYS")
    if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
        raise ValueError("Supabase credentials missing")
    
    audit_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_AUDITS)
    workers = []
    for i in range(Config.WORKER_COUNT):
        agent = AGENTS[i % len(AGENTS)]
        workers.append(SelfPlayWorker(agent, audit_semaphore))
    
    logger.info(f"Workers created. Lung is breathing. Ombudsman watching.")
    await asyncio.gather(*[worker.run() for worker in workers])

if __name__ == "__main__":
    asyncio.run(main())
