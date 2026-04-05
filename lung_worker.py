#!/usr/bin/env python3
"""
LROS Lung Worker – BULK PROCESSING (Mock AI, No Hangs)
"""

import os
import asyncio
import random
import logging
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

WORKER_ID = os.getenv("WORKER_ID", "default")
BATCH_SIZE = 50   # Process 50 messages per cycle
SLEEP_SECONDS = 10

# ------------------------------------------------------------------
# Mock AI – always returns a response instantly
# ------------------------------------------------------------------
async def call_ai(prompt: str) -> str:
    return f"[MOCK] Mutation from LROS: {prompt[:200]}"

# ------------------------------------------------------------------
# Heartbeat – updates system_config every minute
# ------------------------------------------------------------------
async def update_heartbeat():
    supabase.table("system_config").upsert({
        "key": "lung_last_active",
        "value": datetime.utcnow().isoformat()
    }).execute()

# ------------------------------------------------------------------
# Reset stuck messages (older than 5 minutes)
# ------------------------------------------------------------------
async def auto_reset_stuck():
    five_min_ago = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    supabase.table("agent_messages").update({
        "status": "pending", "processed_by": None
    }).eq("status", "processing").lt("sent_at", five_min_ago).execute()

# ------------------------------------------------------------------
# Bulk process agent messages
# ------------------------------------------------------------------
async def process_agent_messages():
    result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(BATCH_SIZE).execute()
    if not result.data:
        return
    logger.info(f"Processing {len(result.data)} agent messages")
    for msg in result.data:
        supabase.table("agent_messages").update({"status": "processing", "processed_by": WORKER_ID}).eq("id", msg["id"]).execute()
        response = await call_ai(msg["message"])
        supabase.table("mutations").insert({
            "content": response,
            "source": f"agent_message:{msg['id']}",
            "score": random.randint(70, 95),
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()
    logger.info(f"Processed {len(result.data)} messages into mutations")

# ------------------------------------------------------------------
# Scavenge knowledge vault
# ------------------------------------------------------------------
async def knowledge_vault_scavenger():
    entries = supabase.table("knowledge_vault").select("*").eq("processed", False).limit(20).execute()
    if not entries.data:
        return
    logger.info(f"Scavenging {len(entries.data)} knowledge entries")
    for entry in entries.data:
        mutation_text = await call_ai(f"Convert this knowledge into a mutation:\n{entry['content']}")
        supabase.table("mutations").insert({
            "content": mutation_text,
            "source": f"knowledge_vault:{entry['source']}",
            "score": random.randint(70, 95),
            "timestamp": datetime.utcnow().isoformat(),
            "processed": False
        }).execute()
        supabase.table("knowledge_vault").update({"processed": True}).eq("id", entry["id"]).execute()
    logger.info(f"Scavenged {len(entries.data)} entries")

# ------------------------------------------------------------------
# Score mutations & auto‑approve high scores
# ------------------------------------------------------------------
async def ombudsman_score():
    mutations = supabase.table("mutations").select("*").eq("processed", False).limit(100).execute()
    if not mutations.data:
        return
    logger.info(f"Scoring {len(mutations.data)} mutations")
    for mut in mutations.data:
        score = mut.get("score", 0) or random.randint(70, 95)
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
                "approved_at": datetime.utcnow().isoformat()
            }).execute()
    logger.info(f"Scored {len(mutations.data)} mutations")

# ------------------------------------------------------------------
# Auto‑approve pending layers
# ------------------------------------------------------------------
async def auto_approve_layers():
    pending = supabase.table("layer_proposals").select("*").eq("status", "pending").execute()
    if len(pending.data) >= 5:
        for layer in pending.data:
            supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer["id"]).execute()
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
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
