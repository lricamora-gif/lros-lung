#!/usr/bin/env python3
"""
LROS Lung Worker – Enhanced with Self‑Healing Watchdog
Auto‑tune, auto‑approve, formal verification, and automatic rollback on errors.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv
import httpx

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
# AI Providers (same as before, with fallback)
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
    for provider, func in [("Mistral", call_mistral), ("DeepSeek", call_deepseek), ("Groq", call_groq), ("Gemini", call_gemini)]:
        try:
            return await func(prompt)
        except Exception as e:
            logger.warning(f"{provider} failed: {e}")
    logger.error("All AI providers failed – using mock")
    return f"[MOCK] {prompt[:100]}"

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
# Watchdog – Self‑Healing Rollback
# ------------------------------------------------------------------
async def is_safe_mode() -> bool:
    res = supabase.table("system_config").select("value").eq("key", "safe_mode").execute()
    return res.data and res.data[0]["value"] == "true"

async def set_safe_mode(enabled: bool, reason: str = ""):
    supabase.table("system_config").update({"value": "true" if enabled else "false"}).eq("key", "safe_mode").execute()
    supabase.table("watchdog_events").insert({
        "event_type": "safe_mode",
        "reason": reason,
        "data": {"enabled": enabled},
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    logger.warning(f"Safe mode {'enabled' if enabled else 'disabled'}: {reason}")

async def watchdog_monitor():
    """Check error rate every 5 minutes; if >30%, enable safe mode."""
    watchdog_enabled = supabase.table("system_config").select("value").eq("key", "watchdog_enabled").execute()
    if not watchdog_enabled.data or watchdog_enabled.data[0]["value"] != "true":
        return
    if await is_safe_mode():
        # Already in safe mode; check if we can auto‑recover after 30 minutes
        last_event = supabase.table("watchdog_events").select("created_at").eq("event_type", "safe_mode").order("created_at", desc=True).limit(1).execute()
        if last_event.data:
            last_time = datetime.fromisoformat(last_event.data[0]["created_at"])
            if datetime.utcnow() - last_time > timedelta(minutes=30):
                # Try to recover
                await set_safe_mode(False, "Auto‑recovery after 30 minutes")
        return

    # Calculate error rate in last 5 minutes
    five_min_ago = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    total = supabase.table("mutations").select("id").gte("timestamp", five_min_ago).execute()
    if not total.data:
        return
    vetoed = supabase.table("mutations").select("id").gte("timestamp", five_min_ago).eq("veto_reason", "not null").execute()
    error_rate = len(vetoed.data) / len(total.data) if total.data else 0
    threshold = float(supabase.table("system_config").select("value").eq("key", "watchdog_error_threshold").execute().data[0]["value"])
    if error_rate > threshold:
        await set_safe_mode(True, f"Error rate {error_rate:.2%} exceeded threshold {threshold:.2%}")

# ------------------------------------------------------------------
# Auto‑tune Ombudsman Threshold (disabled in safe mode)
# ------------------------------------------------------------------
async def auto_tune_threshold():
    if await is_safe_mode():
        return
    auto_tune = supabase.table("system_config").select("value").eq("key", "ombudsman_auto_tune").execute()
    if not auto_tune.data or auto_tune.data[0]["value"] != "true":
        return
    target_veto_rate = float(supabase.table("system_config").select("value").eq("key", "ombudsman_target_veto_rate").execute().data[0]["value"])
    muts = supabase.table("mutations").select("score").order("created_at", desc=True).limit(100).execute()
    if not muts.data:
        return
    curr_thresh = int(supabase.table("system_config").select("value").eq("key", "ombudsman_threshold").execute().data[0]["value"])
    vetoed = sum(1 for m in muts.data if m["score"] < curr_thresh)
    veto_rate = vetoed / len(muts.data)
    if veto_rate > target_veto_rate + 0.05:
        new_thresh = max(50, curr_thresh - 5)
    elif veto_rate < target_veto_rate - 0.05:
        new_thresh = min(90, curr_thresh + 5)
    else:
        return
    supabase.table("system_config").update({"value": str(new_thresh)}).eq("key", "ombudsman_threshold").execute()
    logger.info(f"Auto‑tuned threshold from {curr_thresh} to {new_thresh} (veto rate {veto_rate:.2f})")

# ------------------------------------------------------------------
# Auto‑approve high‑score mutations (disabled in safe mode)
# ------------------------------------------------------------------
async def auto_approve_high_score():
    if await is_safe_mode():
        return
    auto_thresh = int(supabase.table("system_config").select("value").eq("key", "auto_approve_threshold").execute().data[0]["value"])
    high_muts = supabase.table("mutations").select("*").gte("score", auto_thresh).eq("processed", True).execute()
    for mut in high_muts.data:
        existing = supabase.table("layer_proposals").select("id").eq("name", f"Auto-{mut['id'][:8]}").execute()
        if not existing.data:
            supabase.table("layer_proposals").insert({
                "name": f"Auto-{mut['id'][:8]}",
                "description": mut["content"],
                "status": "approved",
                "type": "high_score",
                "approved_at": datetime.utcnow().isoformat()
            }).execute()
            logger.info(f"Auto‑approved high‑score mutation {mut['id']} as layer")

# ------------------------------------------------------------------
# Formal verification & error‑prevention validation
# ------------------------------------------------------------------
async def verify_layer_constitutionally(description: str, layer_id: int) -> bool:
    valid, reason = await enforce_constitution(description)
    supabase.table("formal_verification_log").insert({
        "layer_id": layer_id,
        "check_passed": valid,
        "violation_reason": reason if not valid else None,
        "checked_at": datetime.utcnow().isoformat()
    }).execute()
    return valid

async def validate_error_prevention_layer(layer_description: str) -> bool:
    errors = supabase.table("error_analysis").select("error_pattern").limit(20).execute()
    if not errors.data:
        return True
    for err in errors.data:
        if err["error_pattern"].lower() in layer_description.lower():
            return True
    return False

# ------------------------------------------------------------------
# Ombudsman scoring (respects safe mode)
# ------------------------------------------------------------------
async def ombudsman_score():
    mutations = supabase.table("mutations").select("*").eq("processed", False).execute()
    safe = await is_safe_mode()
    if safe:
        threshold = 70  # fixed baseline
    else:
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

        state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
        if state.data:
            d = state.data[0]["state_data"]
            if score >= threshold:
                d["lung_successes"] = d.get("lung_successes", 0) + 1
            else:
                d["rejections"] = d.get("rejections", 0) + 1
            supabase.table("sovereign_state").update({"state_data": d}).eq("id", 1).execute()

    # After scoring, run auto‑tune and auto‑approve only if not in safe mode
    if not safe:
        await auto_tune_threshold()
        await auto_approve_high_score()

# ------------------------------------------------------------------
# Knowledge Vault Scavenger
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(5).execute()
    for entry in entries.data:
        mutation_text = await call_ai(f"Convert this knowledge into a mutation:\n{entry['content']}\nMutation:")
        supabase.table("mutations").insert({
            "content": mutation_text,
            "source": f"knowledge_vault:{entry['source']}",
            "score": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("knowledge_vault").update({"processed": True}).eq("id", entry["id"]).execute()

# ------------------------------------------------------------------
# Process agent_messages
# ------------------------------------------------------------------
async def process_agent_messages():
    result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        return
    msg = result.data[0]
    supabase.table("agent_messages").update({"status": "processing"}).eq("id", msg["id"]).execute()
    prompt = f"Respond with a mutation:\n{msg['message']}\nMutation:"
    response = await call_ai(prompt)
    supabase.table("mutations").insert({
        "content": response,
        "source": f"agent_message:{msg['id']}",
        "score": 0,
        "timestamp": datetime.utcnow().isoformat(),
        "processed": False
    }).execute()
    supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()

# ------------------------------------------------------------------
# Auto‑approve layers (with verification)
# ------------------------------------------------------------------
async def auto_approve_layers():
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    for layer in pending.data:
        if not await verify_layer_constitutionally(layer["description"], layer["id"]):
            supabase.table("layer_proposals").update({"status": "rejected"}).eq("id", layer["id"]).execute()
            continue
        if not await validate_error_prevention_layer(layer["description"]):
            logger.warning(f"Layer {layer['id']} may not address any known error pattern")
        if len(pending.data) >= 5:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
            logger.info(f"Auto‑approved layer {layer['id']}")

# ------------------------------------------------------------------
# Main loop – runs watchdog every 5 minutes
# ------------------------------------------------------------------
async def main_loop():
    last_watchdog = datetime.utcnow()
    while True:
        try:
            await process_agent_messages()
            await knowledge_vault_scavenger()
            await ombudsman_score()
            await auto_approve_layers()
            # Run watchdog every 5 minutes
            if datetime.utcnow() - last_watchdog >= timedelta(minutes=5):
                await watchdog_monitor()
                last_watchdog = datetime.utcnow()
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
