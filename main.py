import os
import asyncio
import random
import logging
import signal
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from supabase import create_client
from dotenv import load_dotenv
import httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-lung")

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise Exception("Missing Supabase credentials")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")  # optional

# Circuit breaker for AI
AI_FAILURE_COUNT = 0
AI_FAILURE_RESET_TIME = 300  # 5 minutes
LAST_AI_FAILURE = 0

# Heartbeat endpoint (Heart must be running)
HEART_URL = os.getenv("HEART_URL", "http://localhost:8000")  # override in production

# ------------------------------------------------------------------
# Helper: Exponential backoff for Supabase queries
# ------------------------------------------------------------------
async def supabase_retry(func, *args, **kwargs):
    for attempt in range(5):
        try:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=30)
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"Supabase error (attempt {attempt+1}): {e}. Retrying in {wait}s")
            await asyncio.sleep(wait)
    raise Exception("Supabase operation failed after 5 retries")

# ------------------------------------------------------------------
# AI Call with circuit breaker and timeout
# ------------------------------------------------------------------
async def call_ai(prompt: str, timeout=90) -> Optional[str]:
    global AI_FAILURE_COUNT, LAST_AI_FAILURE
    if not MISTRAL_API_KEY:
        return None
    # Circuit breaker: if too many failures recently, skip
    now = time.time()
    if AI_FAILURE_COUNT >= 3 and (now - LAST_AI_FAILURE) < AI_FAILURE_RESET_TIME:
        logger.warning("AI circuit breaker open – skipping call")
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
            )
            r.raise_for_status()
            result = r.json()["choices"][0]["message"]["content"]
            # Reset failure count on success
            AI_FAILURE_COUNT = 0
            return result
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        AI_FAILURE_COUNT += 1
        LAST_AI_FAILURE = now
        return None

# ------------------------------------------------------------------
# Send Slack alert (optional)
# ------------------------------------------------------------------
async def send_alert(message: str):
    if SLACK_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(SLACK_WEBHOOK_URL, json={"text": f"🚨 LROS Alert: {message}"})
        except Exception as e:
            logger.error(f"Slack alert failed: {e}")

# ------------------------------------------------------------------
# Update Lung heartbeat in Heart (and also in Supabase)
# ------------------------------------------------------------------
async def update_heartbeat():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{HEART_URL}/lung/heartbeat")
    except Exception:
        # Fallback: store in Supabase directly
        supabase.table("system_config").upsert({"key": "lung_last_active", "value": datetime.utcnow().isoformat()}).execute()

# ------------------------------------------------------------------
# 1. Extrapolation Swarm (API‑free)
# ------------------------------------------------------------------
async def extrapolation_swarm():
    try:
        entries = supabase.table("knowledge_vault").select("content").order("created_at", desc=True).limit(10).execute()
        if not entries.data:
            return
        for e in entries.data:
            first_sentence = e["content"].split(".")[0][:200]
            synthetic = f"{first_sentence}. Implement this as a LROS capability."
            supabase.table("mutations").insert({
                "content": synthetic,
                "source": "extrapolation_swarm",
                "score": random.randint(60, 85),
                "timestamp": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
        logger.info("Extrapolation swarm generated synthetic mutations")
    except Exception as e:
        logger.error(f"Extrapolation swarm error: {e}")

# ------------------------------------------------------------------
# 2. Knowledge Vault Scavenger
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    try:
        entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(5).execute()
        for entry in entries.data:
            mutation_text = None
            if MISTRAL_API_KEY:
                prompt = f"Convert the following knowledge into a specific, actionable mutation:\n\n{entry['content']}\n\nMutation:"
                mutation_text = await call_ai(prompt)
            if not mutation_text:
                mutation_text = f"From {entry['source']}: {entry['content'][:150]}..."
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
                "sent_at": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
        if entries.data:
            logger.info(f"Processed {len(entries.data)} knowledge vault entries")
    except Exception as e:
        logger.error(f"Knowledge vault scavenger error: {e}")

# ------------------------------------------------------------------
# 3. Memory Scavenger
# ------------------------------------------------------------------
async def memory_scavenger():
    try:
        msgs = supabase.table("agent_messages").select("*").eq("processed", False).limit(10).execute()
        for msg in msgs.data:
            correction = None
            if MISTRAL_API_KEY:
                prompt = f"Analyze this message and suggest a corrective mutation:\n\n{msg['message']}\n\nMutation:"
                correction = await call_ai(prompt)
            if not correction:
                correction = f"Memory scavenger suggests addressing: {msg['message'][:100]}"
            supabase.table("mutations").insert({
                "content": correction,
                "source": f"memory_scavenger:msg_{msg['id']}",
                "score": 0,
                "timestamp": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
            supabase.table("agent_messages").update({"processed": True}).eq("id", msg["id"]).execute()
        if msgs.data:
            logger.info(f"Processed {len(msgs.data)} agent messages")
    except Exception as e:
        logger.error(f"Memory scavenger error: {e}")

# ------------------------------------------------------------------
# 4. Medical Scavenger (API‑free)
# ------------------------------------------------------------------
async def medical_scavenger():
    try:
        keywords = ["cancer", "therapy", "patient", "clinical", "hyperthermia", "longevity", "CAR-T", "oncology", "health"]
        entries = supabase.table("knowledge_vault").select("*").eq("processed", True).order("created_at", desc=True).limit(20).execute()
        for entry in entries.data:
            content_lower = entry["content"].lower()
            if any(kw in content_lower for kw in keywords):
                supabase.table("agent_messages").insert({
                    "agent_id": "medical_scavenger",
                    "message": f"MEDICAL TAG: {entry['source']}\n{entry['content'][:500]}",
                    "sent_at": datetime.utcnow().isoformat(),
                    "processed": False
                }).execute()
    except Exception as e:
        logger.error(f"Medical scavenger error: {e}")

# ------------------------------------------------------------------
# 5. Ombudsman Scoring & Veto (dynamic threshold)
# ------------------------------------------------------------------
async def ombudsman_score():
    try:
        mutations = supabase.table("mutations").select("*").eq("processed", False).execute()
        # Read current threshold from system_config (or default 70)
        thresh_res = supabase.table("system_config").select("value").eq("key", "ombudsman_threshold").execute()
        threshold = int(thresh_res.data[0]["value"]) if thresh_res.data else 70
        for mut in mutations.data:
            score = 50
            if len(mut["content"]) > 50:
                score += 20
            if any(word in mut["content"].lower() for word in ["safety", "patient", "protocol", "improve"]):
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
            supabase.table("agent_messages").insert({
                "agent_id": "ombudsman",
                "message": f"Mutation {mut['id'][:8]} scored {score} – {'ACCEPTED' if score >= threshold else 'VETOED'}",
                "sent_at": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
            # Update counters
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
    except Exception as e:
        logger.error(f"Ombudsman error: {e}")

# ------------------------------------------------------------------
# 6. Elite Pattern Refiner (populates pattern_library)
# ------------------------------------------------------------------
async def elite_pattern_refiner():
    try:
        # Take high‑score mutations (score >= 85) and store as patterns
        high_muts = supabase.table("mutations").select("*").gte("score", 85).order("created_at", desc=True).limit(10).execute()
        for mut in high_muts.data:
            # Avoid duplicates: check if similar pattern already exists
            existing = supabase.table("pattern_library").select("id").ilike("content", mut["content"][:100]).limit(1).execute()
            if not existing.data:
                supabase.table("pattern_library").insert({
                    "content": mut["content"],
                    "domain": "general",
                    "score": mut["score"],
                    "source": "elite_refiner",
                    "uses": 0,
                    "created_at": datetime.utcnow().isoformat(),
                    "last_used": datetime.utcnow().isoformat()
                }).execute()
        # Also refine patterns: take top 3 patterns, combine them
        top_patterns = supabase.table("pattern_library").select("*").order("score", desc=True).limit(3).execute()
        if len(top_patterns.data) >= 2:
            combined = f"Combine: {top_patterns.data[0]['content']} and {top_patterns.data[1]['content']}"
            supabase.table("mutations").insert({
                "content": combined,
                "source": "elite_refiner",
                "score": 90,
                "timestamp": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
        logger.info("Elite pattern refiner completed")
    except Exception as e:
        logger.error(f"Elite pattern refiner error: {e}")

# ------------------------------------------------------------------
# 7. Discussion‑to‑Layer Worker
# ------------------------------------------------------------------
async def discussion_to_layer():
    try:
        msgs = supabase.table("agent_messages").select("*").eq("processed", False).limit(5).execute()
        for msg in msgs.data:
            layer_desc = None
            if MISTRAL_API_KEY:
                prompt = f"Convert this discussion into a constitutional layer:\n\n{msg['message']}\n\nLayer:"
                layer_desc = await call_ai(prompt)
            if not layer_desc:
                layer_desc = f"Layer from discussion: {msg['message'][:100]}"
            supabase.table("layer_proposals").insert({
                "name": f"Discuss-{msg['id']}",
                "description": layer_desc,
                "status": "pending",
                "type": "discussion"
            }).execute()
            supabase.table("agent_messages").update({"processed": True}).eq("id", msg["id"]).execute()
        if msgs.data:
            logger.info(f"Discussion-to-layer processed {len(msgs.data)} messages")
    except Exception as e:
        logger.error(f"Discussion-to-layer error: {e}")

# ------------------------------------------------------------------
# 8. Police Agents (anomaly detection, auto‑remediation)
# ------------------------------------------------------------------
async def police_agent():
    try:
        # Auto‑approve stuck pending layers (> 1 hour)
        hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        stuck = supabase.table("layer_proposals").select("*").eq("status", "pending").lt("created_at", hour_ago).execute()
        if stuck.data:
            logger.warning(f"Auto-approving {len(stuck.data)} stuck layers")
            for layer in stuck.data:
                supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
        # Emergency extrapolation if no new mutations in 30 minutes
        thirty_ago = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        recent = supabase.table("mutations").select("id").gte("timestamp", thirty_ago).limit(1).execute()
        if not recent.data:
            logger.warning("No new mutations in 30 min – triggering emergency extrapolation")
            await extrapolation_swarm()
        # Adjust ombudsman threshold dynamically if veto rate is too high
        state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
        if state.data:
            d = state.data[0]["state_data"]
            rejections = d.get("rejections", 0)
            successes = d.get("lung_successes", 0)
            if successes > 50:
                veto_rate = rejections / (rejections + successes)
                if veto_rate > 0.6:
                    new_threshold = max(50, int(70 * (1 - (veto_rate - 0.6))))
                    supabase.table("system_config").upsert({"key": "ombudsman_threshold", "value": str(new_threshold)}).execute()
                    await send_alert(f"High veto rate ({veto_rate:.0%}), lowered threshold to {new_threshold}")
                elif veto_rate < 0.2 and successes > 100:
                    new_threshold = min(90, 70 + 10)
                    supabase.table("system_config").upsert({"key": "ombudsman_threshold", "value": str(new_threshold)}).execute()
    except Exception as e:
        logger.error(f"Police agent error: {e}")

# ------------------------------------------------------------------
# 9. Auto‑Approve Layers (by backlog threshold)
# ------------------------------------------------------------------
async def auto_approve_layers():
    try:
        pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
        if len(pending.data) >= 5:
            for layer in pending.data:
                supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
            logger.info(f"Auto-approved {len(pending.data)} layers")
    except Exception as e:
        logger.error(f"Auto-approve error: {e}")

# ------------------------------------------------------------------
# 10. Daily Digest
# ------------------------------------------------------------------
async def daily_digest():
    try:
        last_digest = supabase.table("system_config").select("value").eq("key", "last_digest").execute()
        last_date = last_digest.data[0]["value"] if last_digest.data else "2000-01-01"
        if datetime.utcnow() - datetime.fromisoformat(last_date) < timedelta(days=1):
            return
        state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
        if state.data:
            d = state.data[0]["state_data"]
            total = d.get("baseline_anchor", 0) + d.get("heart_successes", 0) + d.get("lung_successes", 0)
            summary = f"Daily: Total {total}, Heart +{d.get('heart_successes',0)}, Lung +{d.get('lung_successes',0)}, Rejections {d.get('rejections',0)}"
            supabase.table("audit_log").insert({
                "event_type": "daily_digest",
                "description": summary,
                "source": "lung_worker",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            supabase.table("agent_messages").insert({
                "agent_id": "digest",
                "message": summary,
                "sent_at": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
        supabase.table("system_config").upsert({"key": "last_digest", "value": datetime.utcnow().isoformat()}).execute()
    except Exception as e:
        logger.error(f"Daily digest error: {e}")

# ------------------------------------------------------------------
# 11. Retrospective Analysis
# ------------------------------------------------------------------
async def retrospective_analysis():
    try:
        last_run = supabase.table("system_config").select("value").eq("key", "last_retrospective").execute()
        last_date = last_run.data[0]["value"] if last_run.data else "2000-01-01"
        if datetime.utcnow() - datetime.fromisoformat(last_date) < timedelta(days=1):
            return
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        errors = supabase.table("error_analysis").select("error_pattern").gte("created_at", week_ago).execute()
        if not errors.data:
            return
        patterns = list(set([e["error_pattern"] for e in errors.data]))
        layers_text = None
        if MISTRAL_API_KEY:
            prompt = f"Based on these error patterns, generate 5 new constitutional layers:\n" + "\n".join(patterns[:10])
            layers_text = await call_ai(prompt)
        if not layers_text:
            layers_text = "\n".join([f"Layer to prevent: {p}" for p in patterns[:5]])
        for line in layers_text.split("\n"):
            if line.strip():
                supabase.table("layer_proposals").insert({
                    "name": f"Retro-{datetime.utcnow().strftime('%Y%m%d')}",
                    "description": line[:200],
                    "status": "pending",
                    "type": "retrospective"
                }).execute()
        supabase.table("system_config").upsert({"key": "last_retrospective", "value": datetime.utcnow().isoformat()}).execute()
        logger.info("Retrospective analysis completed")
    except Exception as e:
        logger.error(f"Retrospective error: {e}")

# ------------------------------------------------------------------
# Main Loop – Parallel execution with graceful shutdown
# ------------------------------------------------------------------
shutdown_event = asyncio.Event()

def signal_handler():
    logger.info("Shutdown signal received")
    shutdown_event.set()

async def worker_task(worker_func, interval_seconds):
    """Run a worker periodically, with individual error isolation."""
    while not shutdown_event.is_set():
        try:
            await worker_func()
        except Exception as e:
            logger.error(f"Worker {worker_func.__name__} crashed: {e}")
        await asyncio.sleep(interval_seconds)

async def main_loop():
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start heartbeat updater (every 60 seconds)
    asyncio.create_task(worker_task(update_heartbeat, 60))

    # Frequent workers (every 30 seconds)
    frequent = [
        (knowledge_vault_scavenger, 30),
        (memory_scavenger, 30),
        (ombudsman_score, 30),
        (police_agent, 30),
        (auto_approve_layers, 30),
    ]
    # Periodic workers (every 5 minutes)
    periodic = [
        (medical_scavenger, 300),
        (extrapolation_swarm, 300),
        (discussion_to_layer, 300),
        (elite_pattern_refiner, 300),
    ]
    # Daily workers (handled separately with their own intervals)
    daily = [
        (retrospective_analysis, 86400),
        (daily_digest, 86400),
    ]

    all_workers = frequent + periodic + daily
    tasks = [asyncio.create_task(worker_task(w, i)) for w, i in all_workers]

    # Wait for shutdown signal
    await shutdown_event.wait()
    logger.info("Cancelling all worker tasks...")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Lung worker shutdown complete")

if __name__ == "__main__":
    asyncio.run(main_loop())
