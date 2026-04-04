import os
import asyncio
import random
import logging
from datetime import datetime
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
WORKER_ID = os.getenv("WORKER_ID", "default")
SLEEP_SECONDS = int(os.getenv("LUNG_SLEEP_SECONDS", "30"))

async def call_ai(prompt: str) -> str:
    if not MISTRAL_API_KEY:
        return f"[MOCK] Simulated response to: {prompt[:100]}"
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
                json={"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
            )
            if r.status_code == 401:
                logger.error("Mistral API key invalid – using mock response")
                return f"[MOCK] Invalid API key. Response to: {prompt[:100]}"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Mistral call failed: {e}")
            return f"[MOCK] Fallback response to: {prompt[:100]}"

async def main_loop():
    while True:
        try:
            result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(1).execute()
            if result.data:
                msg = result.data[0]
                supabase.table("agent_messages").update({"status": "processing", "processed_by": WORKER_ID}).eq("id", msg["id"]).execute()
                prompt = f"Respond to: {msg['message']}"
                response = await call_ai(prompt)
                supabase.table("mutations").insert({
                    "content": response,
                    "source": "lung_worker",
                    "score": random.randint(50, 100),
                    "timestamp": datetime.utcnow().isoformat()
                }).execute()
                supabase.table("agent_messages").update({"status": "done"}).eq("id", msg["id"]).execute()
            else:
                await asyncio.sleep(SLEEP_SECONDS)
        except Exception as e:
            logger.error(f"Worker {WORKER_ID} error: {e}")
            await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
