import os
import asyncio
import uuid
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import httpx

load_dotenv()

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-backend")

# ------------------------------------------------------------------
# Supabase Client
# ------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service role for writes
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("Supabase credentials missing – database features disabled")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------------------------------------------------------
# AI Configuration (Mistral first, then fallbacks)
# ------------------------------------------------------------------
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ------------------------------------------------------------------
# Pydantic Models
# ------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    domain: str = "general"

class ChatResponse(BaseModel):
    response: str
    session_id: str

# ------------------------------------------------------------------
# AI Call Functions (Mistral primary, fallbacks)
# ------------------------------------------------------------------
async def call_mistral(prompt: str, temperature: float = 0.7) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "mistral-large-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def call_openai(prompt: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def call_deepseek(prompt: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def call_groq(prompt: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": "mixtral-8x7b-32768", "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def call_gemini(prompt: str, temperature: float) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

async def call_ai(prompt: str, temperature: float = 0.7) -> str:
    """Try Mistral first, then fallback to others."""
    if MISTRAL_API_KEY:
        try:
            return await call_mistral(prompt, temperature)
        except Exception as e:
            logger.error(f"Mistral failed: {e}")
    if OPENAI_API_KEY:
        try:
            return await call_openai(prompt, temperature)
        except Exception as e:
            logger.error(f"OpenAI failed: {e}")
    if DEEPSEEK_API_KEY:
        try:
            return await call_deepseek(prompt, temperature)
        except Exception as e:
            logger.error(f"DeepSeek failed: {e}")
    if GROQ_API_KEY:
        try:
            return await call_groq(prompt, temperature)
        except Exception as e:
            logger.error(f"Groq failed: {e}")
    if GEMINI_API_KEY:
        try:
            return await call_gemini(prompt, temperature)
        except Exception as e:
            logger.error(f"Gemini failed: {e}")
    return "[MOCK] No AI key available. Please set MISTRAL_API_KEY or another provider."

# ------------------------------------------------------------------
# Background Swarm Worker (Self‑Evolution)
# ------------------------------------------------------------------
async def swarm_worker():
    """Periodically processes unprocessed agent_messages and mutations."""
    while True:
        await asyncio.sleep(60)  # Run every minute
        if not supabase:
            continue
        try:
            # 1. Process unprocessed agent messages
            result = supabase.table("agent_messages").select("*").eq("processed", False).limit(5).execute()
            for msg in result.data:
                logger.info(f"Swarm processing message {msg['id']} from {msg['agent_id']}")
                prompt = f"You are LROS swarm. Respond helpfully to: {msg['message']}"
                response = await call_ai(prompt, temperature=0.6)
                # Store response
                supabase.table("agent_messages").insert({
                    "agent_id": "swarm_worker",
                    "message": f"RESPONSE: {response}",
                    "round": msg.get("round", 0) + 1,
                    "sent_at": datetime.utcnow().isoformat(),
                    "processed": False
                }).execute()
                supabase.table("agent_messages").update({"processed": True}).eq("id", msg["id"]).execute()
                # Audit log
                supabase.table("audit_log").insert({
                    "event_type": "swarm_response",
                    "description": f"Responded to {msg['agent_id']}",
                    "source": "swarm_worker",
                    "created_at": datetime.utcnow().isoformat()
                }).execute()

            # 2. Process high‑score mutations (auto layer proposals)
            muts = supabase.table("mutations").select("*").eq("processed", False).execute()
            for mut in muts.data:
                if mut.get("score", 0) >= 70:
                    supabase.table("layer_proposals").insert({
                        "name": f"Auto-{mut['id'][:8]}",
                        "description": mut["content"],
                        "status": "pending",
                        "type": "mutation"
                    }).execute()
                supabase.table("mutations").update({"processed": True}).eq("id", mut["id"]).execute()
        except Exception as e:
            logger.error(f"Swarm worker error: {e}")

# ------------------------------------------------------------------
# FastAPI App with Lifespan
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background swarm worker
    asyncio.create_task(swarm_worker())
    logger.info("LROS backend started with swarm worker")
    yield
    # Cleanup if needed

app = FastAPI(title="LROS Chat API", version="3.0", lifespan=lifespan)

# ========== CORS: wildcard allowed only with credentials=False ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Chat Endpoint
# ------------------------------------------------------------------
@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    domain = req.domain.lower()
    system_prompt = (
        "You are LROS, a professional, serious, constitutional AI assistant. "
        "Answer business and medical questions with precision. Be safe and truthful.\n\n"
    )
    # Optional: fetch context from mutations (simplified)
    if supabase and domain in ["business", "medical"]:
        try:
            kw = "marketing" if domain == "business" else "patient"
            context = supabase.table("mutations").select("content").ilike("content", f"%{kw}%").limit(3).execute()
            if context.data:
                system_prompt += "Relevant LROS intelligence:\n" + "\n".join([c["content"] for c in context.data]) + "\n\n"
        except Exception as e:
            logger.error(f"Context fetch error: {e}")
    full_prompt = f"{system_prompt}User: {req.message}\nAssistant:"
    response_text = await call_ai(full_prompt, temperature=0.7)
    # Store in chat_logs and agent_messages
    if supabase:
        try:
            supabase.table("chat_logs").insert({
                "session_id": session_id,
                "user_message": req.message,
                "assistant_response": response_text,
                "domain": domain,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            supabase.table("agent_messages").insert({
                "agent_id": "chat_user",
                "message": f"User asked: {req.message}\nLROS answered: {response_text}",
                "round": 0,
                "sent_at": datetime.utcnow().isoformat(),
                "processed": False
            }).execute()
        except Exception as e:
            logger.error(f"DB insert error: {e}")
    return ChatResponse(response=response_text, session_id=session_id)

# ------------------------------------------------------------------
# Additional API Endpoints for Dashboard
# ------------------------------------------------------------------
@app.get("/api/state")
async def get_state():
    if not supabase:
        return {"error": "Supabase not configured"}
    res = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        return {}
    return res.data[0]["state_data"]

@app.get("/api/mutations")
async def get_mutations(limit: int = 100):
    if not supabase:
        return []
    res = supabase.table("mutations").select("*").order("timestamp", desc=True).limit(limit).execute()
    return res.data

@app.get("/api/mutations/count")
async def get_mutations_count():
    if not supabase:
        return {"count": 0}
    res = supabase.table("mutations").select("id", count="exact").execute()
    return {"count": res.count}

@app.post("/api/layers/approve")
async def approve_layer(layer_id: str):
    if not supabase:
        raise HTTPException(500, "Supabase not configured")
    # Check if exists
    check = supabase.table("layer_proposals").select("id").eq("id", layer_id).execute()
    if not check.data:
        raise HTTPException(404, "Layer not found")
    supabase.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer_id).execute()
    # Update sovereign_state: remove from pending_layers and increment approved count
    state_res = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if state_res.data:
        state = state_res.data[0]["state_data"]
        pending = state.get("pending_layers", [])
        new_pending = [p for p in pending if p.get("id") != layer_id]
        state["pending_layers"] = new_pending
        state["approved_layers_count"] = state.get("approved_layers_count", 0) + 1
        state["daily_learning"] = state.get("daily_learning", 0) + 0.1
        supabase.table("sovereign_state").update({"state_data": state}).eq("id", 1).execute()
    return {"status": "approved"}

@app.post("/api/layers/reject")
async def reject_layer(layer_id: str):
    if not supabase:
        raise HTTPException(500, "Supabase not configured")
    supabase.table("layer_proposals").update({"status": "rejected"}).eq("id", layer_id).execute()
    # Remove from pending_layers
    state_res = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if state_res.data:
        state = state_res.data[0]["state_data"]
        pending = state.get("pending_layers", [])
        new_pending = [p for p in pending if p.get("id") != layer_id]
        state["pending_layers"] = new_pending
        supabase.table("sovereign_state").update({"state_data": state}).eq("id", 1).execute()
    return {"status": "rejected"}

@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    if not supabase:
        raise HTTPException(500, "Supabase not configured")
    state_res = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not state_res.data:
        raise HTTPException(404, "State not found")
    state = state_res.data[0]["state_data"]
    total = state.get("baseline_anchor", 0) + state.get("heart_successes", 0) + state.get("lung_successes", 0)
    old = state.get("baseline_anchor", 0)
    state["baseline_anchor"] = total
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    supabase.table("sovereign_state").update({"state_data": state}).eq("id", 1).execute()
    # Log to memory_logs
    supabase.table("memory_logs").insert({
        "event_type": "BASELINE_ANCHOR",
        "description": f"Baseline anchored from {old} to {total}",
        "master_tally": total,
        "baseline": total,
        "heart_total": 0,
        "lung_total": 0,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    return {"new_baseline": total}

@app.post("/api/admin/reset_counters")
async def reset_counters():
    if not supabase:
        raise HTTPException(500, "Supabase not configured")
    state_res = supabase.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if state_res.data:
        state = state_res.data[0]["state_data"]
        state["heart_successes"] = 0
        state["lung_successes"] = 0
        state["rejections"] = 0
        state["uses"] = 0
        state["daily_learning"] = 0
        state["baseline_anchor"] = 1000000
        state["approved_layers_count"] = 0
        supabase.table("sovereign_state").update({"state_data": state}).eq("id", 1).execute()
    return {"status": "reset"}

@app.post("/api/ingest")
async def ingest_knowledge(file: Optional[UploadFile] = File(None), url: Optional[str] = Form(None), text: Optional[str] = Form(None)):
    # Simplified for demo; in production you'd handle file uploads
    return {"status": "ingested"}

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

@app.get("/", response_class=HTMLResponse)
async def serve_chat():
    # You'll serve index.html separately; but for completeness:
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

# ------------------------------------------------------------------
# Run with: uvicorn main:app --host 0.0.0.0 --port 8000
# ------------------------------------------------------------------
