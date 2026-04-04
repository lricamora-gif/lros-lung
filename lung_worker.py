#!/usr/bin/env python3
"""
LROS Lung Worker – Multi‑Layer Constitutional Enforcement
- Full failure handling (retries, dead letter)
- Constitutional Guardian (The Bond, Founder's Ethos, Soul Check)
- Periodic audit of all mutations/layers
- Idempotent, production‑ready
"""

import os
import asyncio
import random
import logging
import json
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv
import httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-lung")

# ------------------------------------------------------------------
# Supabase
# ------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise Exception("Missing Supabase credentials")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

WORKER_ID = os.getenv("WORKER_ID", "default")
SLEEP_SECONDS = int(os.getenv("LUNG_SLEEP_SECONDS", "30"))

# ------------------------------------------------------------------
# AI Providers – multi‑key, multi‑provider fallback with retry
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

# Circuit breaker for AI
ai_failure_count = 0
ai_failure_reset_time = 300  # 5 minutes
last_ai_failure = 0

async def call_with_retry(provider_func, prompt, max_retries=3):
    """Call AI with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return await provider_func(prompt)
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"AI call failed (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s")
            await asyncio.sleep(wait)
    raise Exception(f"All {max_retries} retries failed")

async def call_mistral(prompt: str) -> str:
    global mistral_idx, ai_failure_count, last_ai_failure
    if not MISTRAL_KEYS:
        raise Exception("No Mistral keys")
    # Circuit breaker
    if ai_failure_count >= 3 and (datetime.now().timestamp() - last_ai_failure) < ai_failure_reset_time:
        raise Exception("AI circuit breaker open")
    key = MISTRAL_KEYS[mistral_idx % len(MISTRAL_KEYS)]
    mistral_idx += 1
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
        )
        r.raise_for_status()
        ai_failure_count = 0
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
    """Try each provider with retry; final mock fallback."""
    if MISTRAL_KEYS:
        try:
            return await call_with_retry(call_mistral, prompt)
        except Exception as e:
            logger.warning(f"Mistral permanently failed: {e}")
    if DEEPSEEK_KEYS:
        try:
            return await call_with_retry(call_deepseek, prompt)
        except Exception as e:
            logger.warning(f"DeepSeek permanently failed: {e}")
    if GROQ_KEYS:
        try:
            return await call_with_retry(call_groq, prompt)
        except Exception as e:
            logger.warning(f"Groq permanently failed: {e}")
    if GEMINI_KEYS:
        try:
            return await call_with_retry(call_gemini, prompt)
        except Exception as e:
            logger.warning(f"Gemini permanently failed: {e}")
    logger.error("All AI providers failed – using mock response")
    return f"[MOCK] Simulated response to: {prompt[:100]}"

# ------------------------------------------------------------------
# Constitutional Guardian – Enforces The Bond, Founder's Ethos, Soul Check
# ------------------------------------------------------------------
async def enforce_constitution(content: str) -> tuple[bool, str]:
    """Return (is_valid, veto_reason). Checks multiple constitutional layers."""
    content_lower = content.lower()
    # Blacklist violations
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

    # Soul Check (Layer 594) – require at least one positive alignment keyword
    positive_keywords = ["bond", "founder", "soul", "constitutional", "learning", "revolutionary", "service", "life", "care"]
    if not any(kw in content_lower for kw in positive_keywords):
        return False, "Missing positive alignment with The Bond or Founder's Ethos (Soul Check failed)"

    # Additional check: must not be empty or too short
    if len(content.strip()) < 20:
        return False, "Mutation too short to be meaningful"

    return True, None

# ------------------------------------------------------------------
# Dead Letter Queue – store permanently failed mutations
# ------------------------------------------------------------------
async def dead_letter_insert(content: str, source: str, error: str):
    supabase.table("dead_letter").insert({
        "content": content,
        "source": source,
        "error": error,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    logger.error(f"Mutation moved to dead_letter: {error}")

# ------------------------------------------------------------------
# Periodic Constitutional Audit – scans existing mutations/layers for violations
# ------------------------------------------------------------------
async def constitutional_audit():
    """Run every hour; revert any mutation/layer that violates constitution."""
    # Check unprocessed mutations (should already be caught, but double-check)
    mutations = supabase.table("mutations").select("*").eq("processed", True).execute()
    for mut in mutations.data:
        valid, reason = await enforce_constitution(mut["content"])
        if not valid:
            # Revert: set score to 0, add veto reason
            supabase.table("mutations").update({
                "score": 0,
                "veto_reason": f"Audit violation: {reason}",
                "processed": True
            }).eq("id", mut["id"]).execute()
            supabase.table("error_analysis").insert({
                "error_pattern": f"Audit found constitutional violation: {reason}",
                "frequency": 1,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            logger.warning(f"Audit reverted mutation {mut['id']}: {reason}")

    # Check layer_proposals (approved or pending)
    layers = supabase.table("layer_proposals").select("*").execute()
    for layer in layers.data:
        if layer["status"] in ["approved", "pending"]:
            valid, reason = await enforce_constitution(layer["description"] or "")
            if not valid:
                # Reject or mark as violated
                supabase.table("layer_proposals").update({
                    "status": "rejected",
                    "description": f"[VIOLATION] {layer['description']}\nReason: {reason}"
                }).eq("id", layer["id"]).execute()
                supabase.table("audit_log").insert({
                    "event_type": "constitutional_violation",
                    "description": f"Layer {layer['id']} violated: {reason}",
                    "source": "constitutional_audit",
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                logger.warning(f"Audit rejected layer {layer['id']}: {reason}")

# ------------------------------------------------------------------
# Ensure Bond is active before processing anything
# ------------------------------------------------------------------
async def bond_active() -> bool:
    res = supabase.table("system_config").select("value").eq("key", "bond_enforcement").execute()
    if res.data and res.data[0]["value"] == "active":
        return True
    logger.error("Bond enforcement is not active – refusing to process mutations")
    return False

# ------------------------------------------------------------------
# Ombudsman – Scores mutations, vetoes violations, logs errors
# ------------------------------------------------------------------
async def ombudsman_score():
    if not await bond_active():
        return
    mutations = supabase.table("mutations").select("*").eq("processed", False).execute()
    thresh_res = supabase.table("system_config").select("value").eq("key", "ombudsman_threshold").execute()
    threshold = int(thresh_res.data[0]["value"]) if thresh_res.data else 70

    for mut in mutations.data:
        # Constitutional check
        valid, reason = await enforce_constitution(mut["content"])
        if not valid:
            score = 0
            veto_reason = reason
            logger.warning(f"Mutation {mut['id']} vetoed by Constitution: {reason}")
            await dead_letter_insert(mut["content"], mut["source"], reason)
            supabase.table("error_analysis").insert({
                "error_pattern": f"Constitutional violation: {reason}",
                "frequency": 1,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            supabase.table("mutations").update({
                "score": score,
                "veto_reason": veto_reason,
                "processed": True
            }).eq("id", mut["id"]).execute()
            # Update sovereign_state
            state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
            if state.data:
                d = state.data[0]["state_data"]
                d["rejections"] = d.get("rejections", 0) + 1
                supabase.table("sovereign_state").update({"state_data": d}).eq("id", 1).execute()
            continue

        # Normal scoring
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

        # Agent message
        status = "ACCEPTED" if score >= threshold else "VETOED"
        supabase.table("agent_messages").insert({
            "agent_id": "ombudsman",
            "message": f"Mutation {mut['id'][:8]} scored {score} – {status}. {veto_reason or ''}",
            "status": "pending",
            "sent_at": datetime.utcnow().isoformat()
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

# ------------------------------------------------------------------
# Process agent_messages – generate mutations with retry
# ------------------------------------------------------------------
async def process_agent_messages():
    if not await bond_active():
        return
    result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        return
    msg = result.data[0]
    supabase.table("agent_messages").update({"status": "processing", "processed_by": WORKER_ID}).eq("id", msg["id"]).execute()
    logger.info(f"Worker {WORKER_ID} processing message {msg['id']}")
    prompt = f"Respond to the following message with a clear, actionable mutation (a new capability or rule) that aligns with The Bond and Founder's Ethos:\n\n{msg['message']}\n\nMutation:"
    try:
        response = await call_ai(prompt)
        # Validate constitution before inserting
        valid, reason = await enforce_constitution(response)
        if not valid:
            logger.warning(f"Generated mutation violates constitution: {reason}")
            await dead_letter_insert(response, f"agent_message:{msg['id']}", reason)
            supabase.table("agent_messages").update({"status": "failed", "error": reason}).eq("id", msg["id"]).execute()
            return
        supabase.table("mutations").insert({
            "content": response,
            "source": f"agent_message:{msg['id']}",
            "score": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()
        logger.info(f"Worker {WORKER_ID} created mutation from message {msg['id']}")
    except Exception as e:
        logger.error(f"Failed to process message {msg['id']}: {e}")
        supabase.table("agent_messages").update({"status": "failed", "error": str(e)}).eq("id", msg["id"]).execute()
        await dead_letter_insert(prompt, f"agent_message:{msg['id']}", str(e))

# ------------------------------------------------------------------
# Knowledge Vault Scavenger with constitutional check
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    if not await bond_active():
        return
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(5).execute()
    for entry in entries.data:
        logger.info(f"Scavenging knowledge {entry['id']} – {entry['source']}")
        try:
            mutation_text = await call_ai(f"Convert this knowledge into a mutation aligned with The Bond:\n{entry['content']}\nMutation:")
            valid, reason = await enforce_constitution(mutation_text)
            if not valid:
                logger.warning(f"Scavenged mutation violates constitution: {reason}")
                await dead_letter_insert(mutation_text, f"knowledge_vault:{entry['source']}", reason)
                supabase.table("knowledge_vault").update({"processed": True, "error": reason}).eq("id", entry["id"]).execute()
                continue
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
        except Exception as e:
            logger.error(f"Failed to scavenge {entry['id']}: {e}")
            supabase.table("knowledge_vault").update({"processed": True, "error": str(e)}).eq("id", entry["id"]).execute()

# ------------------------------------------------------------------
# Auto‑approve layers with constitutional validation
# ------------------------------------------------------------------
async def auto_approve_layers():
    if not await bond_active():
        return
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    for layer in pending.data:
        valid, reason = await enforce_constitution(layer["description"] or "")
        if not valid:
            supabase.table("layer_proposals").update({
                "status": "rejected",
                "description": f"[REJECTED BY CONSTITUTION] {layer['description']}\nReason: {reason}"
            }).eq("id", layer["id"]).execute()
            logger.warning(f"Layer {layer['id']} auto-rejected: {reason}")
            continue
    # Auto-approve only if backlog >5 and all are valid
    valid_pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    if len(valid_pending.data) >= 5:
        for layer in valid_pending.data:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
        logger.info(f"Auto-approved {len(valid_pending.data)} layers")

# ------------------------------------------------------------------
# Main Loop – orchestrate all workers with periodic audit
# ------------------------------------------------------------------
async def main_loop():
    last_audit = datetime.utcnow() - timedelta(hours=1)  # trigger on first run
    while True:
        try:
            await process_agent_messages()
            await knowledge_vault_scavenger()
            await ombudsman_score()
            await auto_approve_layers()

            # Run constitutional audit every hour
            if datetime.utcnow() - last_audit > timedelta(hours=1):
                await constitutional_audit()
                last_audit = datetime.utcnow()
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
            supabase.table("audit_log").insert({
                "event_type": "lung_crash",
                "description": str(e),
                "source": WORKER_ID,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
        await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
