import os
import asyncio
import random
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

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

async def call_ai(prompt: str, timeout=120) -> str:
    """Optional AI call – if key missing, returns None."""
    if not MISTRAL_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        return None

# ------------------------------------------------------------------
# 1. Extrapolation Swarm (API‑free, runs every 30 min)
# ------------------------------------------------------------------
async def extrapolation_swarm():
    """Rule‑based synthetic mutations from recent knowledge_vault entries."""
    entries = supabase.table("knowledge_vault").select("content").order("created_at", desc=True).limit(10).execute()
    if not entries.data:
        return
    for e in entries.data:
        # Simple extrapolation: take first sentence, add "Implement in LROS."
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

# ------------------------------------------------------------------
# 2. Knowledge Vault Scavenger (AI preferred, fallback to keyword)
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(5).execute()
    for entry in entries.data:
        mutation_text = None
        if MISTRAL_API_KEY:
            prompt = f"Convert the following knowledge into a specific, actionable mutation:\n\n{entry['content']}\n\nMutation:"
            mutation_text = await call_ai(prompt)
        if not mutation_text:
            # Fallback: extract first 100 chars as mutation
            mutation_text = f"From {entry['source']}: {entry['content'][:150]}..."
        supabase.table("mutations").insert({
            "content": mutation_text,
            "source": f"knowledge_vault:{entry['source']}",
            "score": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("knowledge_vault").update({"processed": True}).eq("id", entry["id"]).execute()
        # Create agent message
        supabase.table("agent_messages").insert({
            "agent_id": "knowledge_scavenger",
            "message": f"New mutation from {entry['source']}: {mutation_text[:200]}",
            "sent_at": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
    if entries.data:
        logger.info(f"Processed {len(entries.data)} knowledge vault entries")

# ------------------------------------------------------------------
# 3. Memory Scavenger (agent_messages + error patterns)
# ------------------------------------------------------------------
async def memory_scavenger():
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

# ------------------------------------------------------------------
# 4. Medical Scavenger (API‑free, keyword tagging)
# ------------------------------------------------------------------
async def medical_scavenger():
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

# ------------------------------------------------------------------
# 5. Ombudsman Scoring & Veto (API‑free, rule‑based)
# ------------------------------------------------------------------
async def ombudsman_score():
    mutations = supabase.table("mutations").select("*").eq("processed", False).execute()
    threshold = 70  # can be read from system_config
    for mut in mutations.data:
        # Simple scoring: length bonus, keyword bonus
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
        # Agent message about outcome
        status = "ACCEPTED" if score >= threshold else "VETOED"
        supabase.table("agent_messages").insert({
            "agent_id": "ombudsman",
            "message": f"Mutation {mut['id'][:8]} scored {score} – {status}",
            "sent_at": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        # Update lung successes/rejections in sovereign_state
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
# 6. Retrospective Analysis (AI preferred, fallback to template)
# ------------------------------------------------------------------
async def retrospective_analysis():
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

# ------------------------------------------------------------------
# 7. Discussion‑to‑Layer Worker
# ------------------------------------------------------------------
async def discussion_to_layer():
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

# ------------------------------------------------------------------
# 8. Police Agents (anomaly detection, auto‑remediation)
# ------------------------------------------------------------------
async def police_agent():
    # Check for stuck pending layers (> 1 hour)
    hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    stuck = supabase.table("layer_proposals").select("*").eq("status", "pending").lt("created_at", hour_ago).execute()
    if stuck.data:
        logger.warning(f"Auto-approving {len(stuck.data)} stuck layers")
        for layer in stuck.data:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
    # Check for no new mutations in last 30 minutes
    thirty_ago = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    recent = supabase.table("mutations").select("id").gte("timestamp", thirty_ago).limit(1).execute()
    if not recent.data:
        logger.warning("No new mutations in 30 min – triggering emergency extrapolation")
        await extrapolation_swarm()  # force run
    # Check veto rate
    state = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if state.data:
        d = state.data[0]["state_data"]
        rejections = d.get("rejections", 0)
        successes = d.get("lung_successes", 0)
        if rejections > successes * 2 and successes > 10:
            alert = f"High veto rate: {rejections} vs {successes}"
            supabase.table("agent_messages").insert({
                "agent_id": "police",
                "message": alert,
                "sent_at": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
            logger.warning(alert)

# ------------------------------------------------------------------
# 9. Auto‑Approve Layers (by backlog threshold)
# ------------------------------------------------------------------
async def auto_approve_layers():
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    if len(pending.data) >= 5:
        for layer in pending.data:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
        logger.info(f"Auto-approved {len(pending.data)} layers")

# ------------------------------------------------------------------
# 10. Daily Digest
# ------------------------------------------------------------------
async def daily_digest():
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

# ------------------------------------------------------------------
# Main Loop – Coordinated, Efficient
# ------------------------------------------------------------------
async def main_loop():
    # Ensure config defaults
    supabase.table("system_config").upsert({"key": "last_retrospective", "value": "2000-01-01"}).execute()
    supabase.table("system_config").upsert({"key": "last_digest", "value": "2000-01-01"}).execute()

    while True:
        try:
            # Run every 30 seconds
            await knowledge_vault_scavenger()
            await memory_scavenger()
            await ombudsman_score()
            await police_agent()
            await auto_approve_layers()

            # Run every 5 minutes (based on minute)
            if datetime.utcnow().minute % 5 == 0:
                await medical_scavenger()
                await extrapolation_swarm()
                await discussion_to_layer()

            # Run daily tasks
            await retrospective_analysis()
            await daily_digest()

        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
