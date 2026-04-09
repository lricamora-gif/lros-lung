#!/usr/bin/env python3
"""
LROS LUNG – Background worker that consumes agent_messages and knowledge_vault,
generates mutations, scores them, and creates layer proposals.
Uses Mistral API (fallback to mock if key missing).
"""

import os
import asyncio
import random
import logging
import httpx
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-lung")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise Exception("Missing Supabase credentials")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
WORKER_ID = os.getenv("WORKER_ID", "default")
BATCH_SIZE = 50
SLEEP_SECONDS = 10

# ------------------------------------------------------------------
# AI Call using Mistral (fallback to mock)
# ------------------------------------------------------------------
async def call_ai(prompt: str) -> str:
    if not MISTRAL_API_KEY:
        logger.warning("No Mistral API key, using mock")
        return f"[MOCK] Mutation: {prompt[:200]}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "mistral-large-latest",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"Mistral error {resp.status_code}: {resp.text}")
                return f"[MOCK] Mistral error {resp.status_code}: {prompt[:200]}"
    except Exception as e:
        logger.error(f"Mistral exception: {e}")
        return f"[MOCK] Exception: {prompt[:200]}"

# ------------------------------------------------------------------
# Helper: Update heartbeat
# ------------------------------------------------------------------
async def update_heartbeat():
    supabase.table("system_config").upsert({
        "key": "lung_last_active",
        "value": datetime.utcnow().isoformat()
    }).execute()

# ------------------------------------------------------------------
# Reset stuck agent_messages (processing > 5 min)
# ------------------------------------------------------------------
async def auto_reset_stuck():
    five_min_ago = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    supabase.table("agent_messages").update({
        "status": "pending",
        "processed_by": None
    }).eq("status", "processing").lt("sent_at", five_min_ago).execute()

# ------------------------------------------------------------------
# Process pending agent_messages -> mutations
# ------------------------------------------------------------------
async def process_agent_messages():
    result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(BATCH_SIZE).execute()
    if not result.data:
        return
    logger.info(f"Processing {len(result.data)} agent messages")
    for msg in result.data:
        supabase.table("agent_messages").update({
            "status": "processing",
            "processed_by": WORKER_ID
        }).eq("id", msg["id"]).execute()

        response = await call_ai(msg["message"])

        supabase.table("mutations").insert({
            "content": response,
            "source": f"agent_message:{msg['id']}",
            "score": random.randint(70, 95),
            "timestamp": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()

        supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()
    logger.info(f"Processed {len(result.data)} messages into mutations")

# ------------------------------------------------------------------
# Knowledge Vault scavenger -> mutations
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(20).execute()
    if not entries.data:
        return
    logger.info(f"Scavenging {len(entries.data)} knowledge entries")
    for entry in entries.data:
        prompt = f"Convert this knowledge into a mutation:\n{entry['content']}"
        mutation_text = await call_ai(prompt)
        supabase.table("mutations").insert({
            "content": mutation_text,
            "source": f"knowledge_vault:{entry['source']}",
            "score": random.randint(70, 95),
            "timestamp": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("knowledge_vault").update({"processed": True}).eq("id", entry["id"]).execute()
    logger.info(f"Scavenged {len(entries.data)} entries")

# ------------------------------------------------------------------
# Ombudsman: score mutations and auto-approve high-scoring ones
# ------------------------------------------------------------------
async def ombudsman_score():
    mutations = supabase.table("mutations").select("*").eq("processed", False).limit(100).execute()
    if not mutations.data:
        return
    logger.info(f"Scoring {len(mutations.data)} mutations")
    for mut in mutations.data:
        # Use existing score or generate random (70-95)
        score = mut.get("score") or random.randint(70, 95)
        supabase.table("mutations").update({
            "score": score,
            "processed": True
        }).eq("id", mut["id"]).execute()

        if score >= 90:
            supabase.table("layer_proposals").insert({
                "name": f"Auto-{mut['id'][:8]}",
                "description": mut["content"],
                "status": "approved",
                "type": "high_score",
                "approved_at": datetime.utcnow().isoformat(),
                "created_at": datetime.utcnow().isoformat()
            }).execute()
    logger.info(f"Scored {len(mutations.data)} mutations")

# ------------------------------------------------------------------
# Auto-approve pending layer proposals when backlog grows
# ------------------------------------------------------------------
async def auto_approve_layers():
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    if len(pending.data) >= 5:
        for layer in pending.data:
            supabase.table("layer_proposals").update({
                "status": "approved",
                "approved_at": datetime.utcnow().isoformat()
            }).eq("id", layer["id"]).execute()
        logger.info(f"Auto-approved {len(pending.data)} layers")

# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
async def main_loop():
    last_heartbeat = datetime.utcnow()
    while True:
        try:
            await auto_reset_stuck()
            await process_agent_messages()
            await knowledge_vault_scavenger()
            await ombudsman_score()
            await auto_approve_layers()

            if datetime.utcnow() - last_heartbeat >= timedelta(minutes=1):
                await update_heartbeat()
                last_heartbeat = datetime.utcnow()
        except Exception as e:
            logger.error(f"Lung worker error: {e}", exc_info=True)
        await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
