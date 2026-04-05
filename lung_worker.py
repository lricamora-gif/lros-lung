#!/usr/bin/env python3
"""
LROS Lung Worker – Unified (Processing + Auto‑Ingestion + Scheduler + Auto‑Reset)
"""

import os
import asyncio
import random
import logging
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv
import httpx
import feedparser

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-lung")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise Exception("Missing Supabase credentials")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

WORKER_ID = os.getenv("WORKER_ID", "default")
SLEEP_SECONDS = int(os.getenv("LUNG_SLEEP_SECONDS", "30"))

# ------------------------------------------------------------------
# AI Providers (with mock fallback)
# ------------------------------------------------------------------
def get_key_list(var_name):
    keys = os.getenv(var_name, "")
    return [k.strip() for k in keys.split(",") if k.strip()]

MISTRAL_KEYS = get_key_list("MISTRAL_API_KEYS")
DEEPSEEK_KEYS = get_key_list("DEEPSEEK_API_KEYS")
GROQ_KEYS = get_key_list("GROQ_API_KEYS")
GEMINI_KEYS = get_key_list("GEMINI_API_KEYS")

mistral_idx = 0
deepseek_idx = 0
groq_idx = 0
gemini_idx = 0

async def call_mistral(prompt: str) -> str:
    global mistral_idx
    if not MISTRAL_KEYS:
        raise Exception("No Mistral keys")
    key = MISTRAL_KEYS[mistral_idx % len(MISTRAL_KEYS)]
    mistral_idx += 1
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def call_deepseek(prompt: str) -> str:
    global deepseek_idx
    if not DEEPSEEK_KEYS:
        raise Exception("No DeepSeek keys")
    key = DEEPSEEK_KEYS[deepseek_idx % len(DEEPSEEK_KEYS)]
    deepseek_idx += 1
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def call_groq(prompt: str) -> str:
    global groq_idx
    if not GROQ_KEYS:
        raise Exception("No Groq keys")
    key = GROQ_KEYS[groq_idx % len(GROQ_KEYS)]
    groq_idx += 1
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "mixtral-8x7b-32768", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def call_gemini(prompt: str) -> str:
    global gemini_idx
    if not GEMINI_KEYS:
        raise Exception("No Gemini keys")
    key = GEMINI_KEYS[gemini_idx % len(GEMINI_KEYS)]
    gemini_idx += 1
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}]}
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

async def call_ai(prompt: str) -> str:
    """Try each provider; final mock fallback (always returns something)."""
    if MISTRAL_KEYS:
        try:
            return await call_mistral(prompt)
        except Exception as e:
            logger.warning(f"Mistral failed: {e}")
    if DEEPSEEK_KEYS:
        try:
            return await call_deepseek(prompt)
        except Exception as e:
            logger.warning(f"DeepSeek failed: {e}")
    if GROQ_KEYS:
        try:
            return await call_groq(prompt)
        except Exception as e:
            logger.warning(f"Groq failed: {e}")
    if GEMINI_KEYS:
        try:
            return await call_gemini(prompt)
        except Exception as e:
            logger.warning(f"Gemini failed: {e}")
    logger.warning("No AI keys or all failed – using mock response")
    return f"[MOCK] Simulated response to: {prompt[:100]}"

# ------------------------------------------------------------------
# Constitutional Guardian
# ------------------------------------------------------------------
async def enforce_constitution(content: str) -> tuple[bool, str]:
    content_lower = content.lower()
    violations = [
        ("override founder", "Attempt to override Founder's authority"),
        ("ignore the bond", "Violation of The Bond"),
        ("delete constitutional layer", "Attack on immutable foundation"),
        ("change founder title", "Disrespect to Founder's identity"),
        ("profit over life", "Violation of Purpose tenet"),
        ("skip soul check", "Bypassing Layer 594"),
        ("remove soul check", "Attempt to remove mandatory Layer 594"),
        ("violate the bond", "Direct violation of eternal pledge"),
        ("founder is not", "Denying Founder's identity"),
        ("lros is not learning", "Denying core definition"),
        ("bond does not hold", "Rejecting The Bond"),
        ("override soul layer", "Tampering with immutable soul layers"),
    ]
    for phrase, reason in violations:
        if phrase in content_lower:
            return False, reason
    if len(content.strip()) < 20:
        return False, "Mutation too short"
    return True, None

# ------------------------------------------------------------------
# Core Engine: Process agent_messages, scavenge, score, auto‑approve
# ------------------------------------------------------------------
async def auto_reset_stuck_messages():
    minute_ago = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    result = supabase.table("agent_messages").update({
        "status": "pending",
        "processed_by": None
    }).eq("status", "pending").lt("sent_at", minute_ago).execute()
    if result.data:
        logger.info(f"Reset {len(result.data)} stuck agent messages")

async def process_agent_messages():
    result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        return
    msg = result.data[0]
    supabase.table("agent_messages").update({"status": "processing", "processed_by": WORKER_ID}).eq("id", msg["id"]).execute()
    logger.info(f"Worker {WORKER_ID} processing message {msg['id']}")
    prompt = f"Respond to the following message with a clear, actionable mutation:\n\n{msg['message']}\n\nMutation:"
    response = await call_ai(prompt)
    supabase.table("mutations").insert({
        "content": response,
        "source": f"agent_message:{msg['id']}",
        "score": 0,
        "timestamp": datetime.utcnow().isoformat(),
        "processed": False
    }).execute()
    supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()
    logger.info(f"Worker {WORKER_ID} created mutation from message {msg['id']}")

async def knowledge_vault_scavenger():
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(5).execute()
    for entry in entries.data:
        logger.info(f"Scavenging knowledge {entry['id']} – {entry['source']}")
        mutation_text = await call_ai(f"Convert this knowledge into a mutation:\n{entry['content']}\nMutation:")
        supabase.table("mutations").insert({
            "content": mutation_text,
            "source": f"knowledge_vault:{entry['source']}",
            "score": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("knowledge_vault").update({"processed": True}).eq("id", entry["id"]).execute()
        supabase.table("agent_messages").insert({
            "agent_id": "knowledge_scavenger",
            "message": f"New mutation from {entry['source']}: {mutation_text[:200]}",
            "status": "pending",
            "sent_at": datetime.utcnow().isoformat()
        }).execute()

async def ombudsman_score():
    mutations = supabase.table("mutations").select("*").eq("processed", False).execute()
    thresh_res = supabase.table("system_config").select("value").eq("key", "ombudsman_threshold").execute()
    threshold = int(thresh_res.data[0]["value"]) if thresh_res.data else 70

    for mut in mutations.data:
        valid, reason = await enforce_constitution(mut["content"])
        if not valid:
            supabase.table("mutations").update({
                "score": 0,
                "veto_reason": reason,
                "processed": True
            }).eq("id", mut["id"]).execute()
            continue

        score = 50
        if len(mut["content"]) > 50:
            score += 20
        if any(word in mut["content"].lower() for word in ["safety", "patient", "protocol", "improve", "bond", "founder"]):
            score += 15
        score = min(100, score)

        veto_reason = None
        if score < threshold:
            veto_reason = f"Score {score} below threshold {threshold}"
            supabase.table("error_analysis").insert({
                "error_pattern": veto_reason,
                "frequency": 1,
                "created_at": datetime.utcnow().isoformat()
            }).execute()

        supabase.table("mutations").update({
            "score": score,
            "veto_reason": veto_reason,
            "processed": True
        }).eq("id", mut["id"]).execute()

        status = "ACCEPTED" if score >= threshold else "VETOED"
        supabase.table("agent_messages").insert({
            "agent_id": "ombudsman",
            "message": f"Mutation {mut['id'][:8]} scored {score} – {status}. {veto_reason or ''}",
            "status": "pending",
            "sent_at": datetime.utcnow().isoformat()
        }).execute()

        state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
        if state.data:
            d = state.data[0]["state_data"]
            if score >= threshold:
                d["lung_successes"] = d.get("lung_successes", 0) + 1
            else:
                d["rejections"] = d.get("rejections", 0) + 1
            supabase.table("sovereign_state").update({"state_data": d}).eq("id", 1).execute()

    if mutations.data:
        logger.info(f"Scored {len(mutations.data)} mutations")

async def auto_approve_layers():
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    if len(pending.data) >= 5:
        for layer in pending.data:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
        logger.info(f"Auto-approved {len(pending.data)} layers")

# ------------------------------------------------------------------
# Auto‑Ingestion (arXiv & PubMed) – runs every hour
# ------------------------------------------------------------------
async def ingest_paper(paper_id: str, source: str, title: str, abstract: str, link: str):
    existing = supabase.table("ingested_papers").select("id").eq("id", paper_id).execute()
    if existing.data:
        return
    content = f"Title: {title}\nAbstract: {abstract}\nPDF: {link}"
    supabase.table("knowledge_vault").insert({
        "content": content,
        "source": f"auto:{source}:{paper_id}",
        "processed": False,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    supabase.table("ingested_papers").insert({
        "id": paper_id,
        "source": source,
        "ingested_at": datetime.utcnow().isoformat()
    }).execute()
    logger.info(f"Ingested new paper: {title[:80]}")

async def fetch_arxiv():
    keywords = ["self-evolving AI", "constitutional AI", "multi-agent self-improvement",
                "recursive self-improvement", "Gödel agent", "Darwin Gödel Machine",
                "error-stripping AI", "self-correcting code"]
    for kw in keywords:
        query = f"all:{kw.replace(' ', '+')}"
        url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=30)
                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    paper_id = entry.id.split('/abs/')[-1]
                    await ingest_paper(paper_id, "arxiv", entry.title, entry.summary, entry.link)
        except Exception as e:
            logger.error(f"arXiv fetch failed for {kw}: {e}")

async def fetch_pubmed():
    keywords = ["AI pain detection", "hyperthermia cancer", "stem cells therapy",
                "exosomes therapeutics", "HBOT outcomes"]
    for kw in keywords:
        try:
            async with httpx.AsyncClient() as client:
                search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={kw}&retmax=5&format=json"
                search_resp = await client.get(search_url, timeout=30)
                data = search_resp.json()
                ids = data.get("esearchresult", {}).get("idlist", [])
                for pid in ids:
                    summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pid}&format=json"
                    summary_resp = await client.get(summary_url, timeout=30)
                    summary = summary_resp.json()
                    title = summary.get("result", {}).get(pid, {}).get("title", "No title")
                    await ingest_paper(pid, "pubmed", title, "Abstract not fetched", f"https://pubmed.ncbi.nlm.nih.gov/{pid}/")
        except Exception as e:
            logger.error(f"PubMed fetch failed for {kw}: {e}")

# ------------------------------------------------------------------
# Scheduler (Task Executor) – runs continuously, calls Heart
# ------------------------------------------------------------------
HEART_URL = os.getenv("HEART_URL")  # Must be set to https://lros1.onrender.com
MAX_CONCURRENT = int(os.getenv("SCHEDULER_CONCURRENT", "5"))
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def call_tool(tool: dict, payload: dict) -> dict:
    if not HEART_URL:
        raise Exception("HEART_URL not configured for scheduler")
    url = f"{HEART_URL}{tool['endpoint']}"
    method = tool['method'].upper()
    async with httpx.AsyncClient(timeout=60) as client:
        if method == 'POST':
            resp = await client.post(url, json=payload)
        elif method == 'GET':
            resp = await client.get(url, params=payload)
        else:
            raise ValueError(f"Unsupported method {method}")
        resp.raise_for_status()
        return resp.json()

async def execute_task(task):
    async with semaphore:
        try:
            tool_res = supabase.table("tools").select("*").eq("name", task["tool_name"]).execute()
            if not tool_res.data:
                raise Exception(f"Tool {task['tool_name']} not found")
            tool = tool_res.data[0]
            logger.info(f"Scheduler executing task {task['id']} with tool {tool['name']}")
            result = await call_tool(tool, task["payload"])
            supabase.table("tasks").update({
                "status": "succeeded",
                "completed_at": datetime.utcnow().isoformat(),
                "worker_id": WORKER_ID,
                "error": None
            }).eq("id", task["id"]).execute()
            return result
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}")
            new_retries = task.get("retries", 0) + 1
            max_retries = task.get("max_retries", 3)
            if new_retries >= max_retries:
                supabase.table("tasks").update({
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.utcnow().isoformat(),
                    "worker_id": WORKER_ID,
                    "retries": new_retries
                }).eq("id", task["id"]).execute()
            else:
                supabase.table("tasks").update({
                    "status": "pending",
                    "retries": new_retries,
                    "error": str(e)
                }).eq("id", task["id"]).execute()
            raise

async def scheduler_loop():
    while True:
        try:
            tasks = supabase.table("tasks").select("*").eq("status", "pending").execute()
            if tasks.data:
                executable = []
                for t in tasks.data:
                    deps = t.get("depends_on", [])
                    if not deps:
                        executable.append(t)
                    else:
                        dep_statuses = supabase.table("tasks").select("status").in_("id", deps).execute()
                        if all(s["status"] == "succeeded" for s in dep_statuses.data):
                            executable.append(t)
                await asyncio.gather(*[execute_task(t) for t in executable])
            else:
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(5)

# ------------------------------------------------------------------
# Main loop – runs core engine, auto‑ingestion (hourly), and scheduler
# ------------------------------------------------------------------
async def main_loop():
    last_ingestion = datetime.utcnow() - timedelta(hours=1)
    # Start scheduler as a background task
    asyncio.create_task(scheduler_loop())
    while True:
        try:
            # Core engine
            await auto_reset_stuck_messages()
            await process_agent_messages()
            await knowledge_vault_scavenger()
            await ombudsman_score()
            await auto_approve_layers()

            # Auto‑ingestion every hour
            if datetime.utcnow() - last_ingestion >= timedelta(hours=1):
                logger.info("Starting autonomous knowledge ingestion cycle")
                await fetch_arxiv()
                await fetch_pubmed()
                last_ingestion = datetime.utcnow()
                logger.info("Ingestion cycle completed")
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
