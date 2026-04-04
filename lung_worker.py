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

WORKER_ID = os.getenv("WORKER_ID", "default")
SLEEP_SECONDS = int(os.getenv("LUNG_SLEEP_SECONDS", "30"))

# ---------- AI providers ----------
def get_key_list(var_name):
    keys = os.getenv(var_name, "")
    return [k.strip() for k in keys.split(",") if k.strip()]

MISTRAL_KEYS = get_key_list("MISTRAL_API_KEYS")
DEEPSEEK_KEYS = get_key_list("DEEPSEEK_API_KEYS")
GROQ_KEYS = get_key_list("GROQ_API_KEYS")
GEMINI_KEYS = get_key_list("GEMINI_API_KEYS")

# Simple round‑robin indices (stored in closure)
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
    # Try providers in order
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
    # Final fallback
    logger.error("All AI providers failed – using mock response")
    return f"[MOCK] Simulated response to: {prompt[:100]}"

async def main_loop():
    while True:
        try:
            result = supabase.table("agent_messages").select("*").eq("status", "pending").limit(1).execute()
            if result.data:
                msg = result.data[0]
                supabase.table("agent_messages").update({"status": "processing", "processed_by": WORKER_ID}).eq("id", msg["id"]).execute()
                logger.info(f"Worker {WORKER_ID} processing message {msg['id']}")
                prompt = f"Respond to: {msg['message']}"
                response = await call_ai(prompt)
                # Generate a score (optional: ask AI to rate itself, but random is fine for evolution)
                score = random.randint(50, 100)
                supabase.table("mutations").insert({
                    "content": response,
                    "source": "lung_worker",
                    "score": score,
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
