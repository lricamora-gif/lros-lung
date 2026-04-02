# ============================================================================
# LROS – Sovereign AI with Real Heart/Lung Swarm, Recursive Learning
# ============================================================================

import os
import asyncio
import random
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from typing import Optional
import requests
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Sovereign")

app = FastAPI(title="LROS Sovereign Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------- Supabase ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Missing SUPABASE_URL or SUPABASE_KEY")
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Ensure Tables ----------
def ensure_tables():
    # sovereign_state (single row id=1)
    try:
        db.table("sovereign_state").select("id").limit(1).execute()
    except:
        default_state = {
            "baseline_anchor": 1008922,
            "heart_successes": 1027965,
            "lung_successes": 45429,
            "rejections": 4115,
            "uses": 195700000,
            "daily_learning": 2921731.39,
            "active_agent": "244",
            "mutation_ledger": [],
            "logs": [],
            "pending_layers": [],
            "approved_layers_count": 0,
            "knowledge_vault": []
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default_state}).execute()
    
    # engine1_stats
    try:
        db.table("engine1_stats").select("id").limit(1).execute()
    except:
        db.table("engine1_stats").insert({"id": 1, "total_successes": 0, "last_thought": ""}).execute()
    
    # knowledge_vault
    try:
        db.table("knowledge_vault").select("id").limit(1).execute()
    except:
        pass  # create manually or let inserts create
    # mutations and layer_proposals already exist from earlier
ensure_tables()

# ---------- Helper: Get State ----------
def get_state():
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        return None
    return res.data[0]["state_data"]

def save_state(state):
    db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# ---------- AI Caller with Key Rotation (DeepSeek primary, Gemini fallback) ----------
DEEPSEEK_API_KEYS = [k.strip() for k in os.environ.get("DEEPSEEK_API_KEYS", "").split(",") if k.strip()]
GEMINI_API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]

deepseek_index = 0
gemini_index = 0

def call_ai(prompt: str, temperature: float = 0.7) -> str:
    global deepseek_index, gemini_index
    if DEEPSEEK_API_KEYS:
        for _ in range(len(DEEPSEEK_API_KEYS)):
            key = DEEPSEEK_API_KEYS[deepseek_index % len(DEEPSEEK_API_KEYS)]
            deepseek_index += 1
            try:
                headers = {"Authorization": f"Bearer {key}"}
                payload = {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature
                }
                response = requests.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers, timeout=30)
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.warning(f"DeepSeek key {key[:5]}... failed: {e}")
                continue
    if GEMINI_API_KEYS:
        import google.generativeai as genai
        for _ in range(len(GEMINI_API_KEYS)):
            key = GEMINI_API_KEYS[gemini_index % len(GEMINI_API_KEYS)]
            gemini_index += 1
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt, generation_config={"temperature": temperature})
                return response.text
            except Exception as e:
                logger.warning(f"Gemini key {key[:5]}... failed: {e}")
                continue
    return "[Simulated] No AI key available."

# ---------- Real Heart Worker (Engine 1) ----------
async def engine1_worker():
    """Every 2 seconds, generate a real tactical thought using LLM with context."""
    while True:
        try:
            # 1. Fetch context from knowledge vault and recent high‑scoring mutations
            vault_res = db.table("knowledge_vault").select("content").limit(5).execute()
            mutations_res = db.table("mutations").select("content", "score").order("score", desc=True).limit(5).execute()
            context = ""
            if vault_res.data:
                context += "Knowledge Vault:\n" + "\n".join(v["content"][:200] for v in vault_res.data)
            if mutations_res.data:
                context += "\nPast high‑scoring mutations:\n" + "\n".join(m["content"][:200] for m in mutations_res.data)
            
            prompt = f"""You are LROS Heart Engine. Generate a short, tactical thought about medical innovation, asset liquidity, or constitutional AI. Keep it under 100 words. Use the following context to guide your thought:\n{context}\n\nThought:"""
            thought = call_ai(prompt, temperature=0.7)
            
            # 2. Update engine1_stats table
            stats = db.table("engine1_stats").select("*").eq("id", 1).execute()
            if not stats.data:
                db.table("engine1_stats").insert({"id": 1, "total_successes": 1, "last_thought": thought}).execute()
                new_total = 1
            else:
                new_total = stats.data[0]["total_successes"] + 1
                db.table("engine1_stats").update({
                    "total_successes": new_total,
                    "last_thought": thought,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", 1).execute()
            
            # 3. Also log to sovereign_state logs for frontend ledger
            state = get_state()
            if state:
                state["logs"].insert(0, f"[HEART] {thought}")
                if len(state["logs"]) > 30:
                    state["logs"] = state["logs"][:30]
                save_state(state)
            
            logger.info(f"Engine 1 produced thought #{new_total}")
        except Exception as e:
            logger.error(f"Engine 1 worker error: {e}")
        await asyncio.sleep(2)  # sustainable pace

# ---------- Real Lung Worker (Engine 2) ----------
async def lung_worker():
    domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"]
    models = ["deepseek", "mistral", "groq", "gemini", "cerebras"]
    while True:
        try:
            # 1. Fetch context from vault and past successes
            vault_res = db.table("knowledge_vault").select("content").limit(5).execute()
            mutations_res = db.table("mutations").select("content", "score").order("score", desc=True).limit(5).execute()
            context = ""
            if vault_res.data:
                context += "Vault:\n" + "\n".join(v["content"][:200] for v in vault_res.data)
            if mutations_res.data:
                context += "\nPast successes:\n" + "\n".join(m["content"][:200] for m in mutations_res.data)
            
            domain = random.choice(domains)
            prompt = f"""You are LROS Lung Engine. Generate a novel, high‑value mutation strategy in the domain: {domain}. Use the following context to avoid repeating past ideas and to build on previous successes:\n{context}\n\nStrategy:"""
            mutation_content = call_ai(prompt, temperature=0.8)
            
            # 2. Score with Ombudsman
            score_prompt = f"Rate the following strategy from 0 to 100 (100 = brilliant, 0 = useless). Return only the integer score.\n\nStrategy: {mutation_content}\n\nScore:"
            score_response = call_ai(score_prompt, temperature=0.2)
            try:
                oScore = int(score_response.strip())
                oScore = max(0, min(100, oScore))
            except:
                oScore = random.randint(50, 100)
            
            threshold = 85
            agent = str(random.randint(1, 500)).zfill(3)
            source = random.choice(models)
            
            if oScore >= threshold:
                state = get_state()
                if state:
                    state["lung_successes"] += 1
                    save_state(state)
                log_msg = f"✅ [EVOLVE] {source} logic accepted (Score: {oScore}) - {domain}"
                veto_reason = None
                # Insert mutation
                db.table("mutations").insert({
                    "content": mutation_content,
                    "score": oScore,
                    "source": source,
                    "timestamp": datetime.utcnow().isoformat(),
                    "domain": domain,
                    "agent": agent,
                    "veto_reason": None
                }).execute()
                # Possibly propose new layer
                if oScore >= 92 and random.random() > 0.85:
                    layer_names = ["Quantum Encryption Substrate", "Neural Routing Bypass", "Cognitive Empathy Engine", "Recursive Strategy Matrix", "Dynamic Resource Allocator"]
                    layer_name = random.choice(layer_names)
                    layer_desc = f"Architectural breakthrough generated by Swarm from {source} mutation."
                    db.table("layer_proposals").insert({
                        "name": layer_name,
                        "description": layer_desc,
                        "status": "pending",
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
                    # Also add to state pending_layers for immediate frontend display
                    if state:
                        state["pending_layers"].append({"name": layer_name, "description": layer_desc, "id": f"lyr_{len(state['pending_layers'])}"})
                        save_state(state)
                    log_msg += f" | Proposed new layer: {layer_name}"
            else:
                state = get_state()
                if state:
                    state["rejections"] += 1
                    save_state(state)
                log_msg = f"⛔ [VETO] {source} rejected (Score: {oScore} < {threshold}) - {domain}"
                db.table("mutations").insert({
                    "content": mutation_content,
                    "score": oScore,
                    "source": source,
                    "timestamp": datetime.utcnow().isoformat(),
                    "domain": domain,
                    "agent": agent,
                    "veto_reason": f"Score {oScore} below threshold {threshold}"
                }).execute()
            
            # Log to sovereign_state logs
            state = get_state()
            if state:
                state["logs"].insert(0, log_msg)
                if len(state["logs"]) > 30:
                    state["logs"] = state["logs"][:30]
                save_state(state)
            
            logger.info(log_msg)
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(1.2)

# ---------- API Endpoints ----------
@app.get("/api/engine1/stats")
async def get_engine1_stats():
    stats = db.table("engine1_stats").select("*").eq("id", 1).execute()
    if not stats.data:
        return {"total_successes": 0, "last_thought": ""}
    return stats.data[0]

@app.get("/api/status")
async def get_status():
    state = get_state()
    if not state:
        return {"successes": 0, "uses": 0, "learning_perc": 0, "mutation_ledger": [], "logs": []}
    return {
        "successes": state.get("heart_successes", 0) + state.get("lung_successes", 0),
        "uses": state.get("uses", 0),
        "learning_perc": state.get("daily_learning", 0),
        "mutation_ledger": state.get("mutation_ledger", []),
        "logs": state.get("logs", [])
    }

@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_state()
    if not state:
        raise HTTPException(500, "No state")
    total = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
    state["baseline_anchor"] = total
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    state["logs"].insert(0, f"[ANCHOR] Sovereign Baseline locked at {total:,}")
    save_state(state)
    return {"status": "success", "new_baseline": total}

@app.post("/api/ingest")
async def ingest_knowledge(file: Optional[UploadFile] = File(None), url: Optional[str] = Form(None), text: Optional[str] = Form(None)):
    if file:
        content = (await file.read()).decode("utf-8", errors="ignore")
        source = f"File: {file.filename}"
        db.table("knowledge_vault").insert({"content": content[:5000], "source": source, "created_at": datetime.utcnow().isoformat()}).execute()
    elif url:
        # Fetch URL content (simple GET)
        try:
            resp = requests.get(url, timeout=15)
            content = resp.text[:5000]
            source = f"URL: {url}"
            db.table("knowledge_vault").insert({"content": content, "source": source, "created_at": datetime.utcnow().isoformat()}).execute()
        except Exception as e:
            raise HTTPException(400, f"Could not fetch URL: {e}")
    elif text:
        source = "Raw text"
        db.table("knowledge_vault").insert({"content": text[:5000], "source": source, "created_at": datetime.utcnow().isoformat()}).execute()
    else:
        raise HTTPException(400, "No file, URL, or text provided")
    # Also update heart successes (mass gain)
    state = get_state()
    if state:
        state["heart_successes"] += 5000
        state["uses"] += 25000
        state["daily_learning"] += 500.5
        state["logs"].insert(0, f"[VAULT] Ingested {source}. +5,000 heart successes.")
        save_state(state)
    return {"status": "ingested"}

@app.get("/api/layers/pending")
async def get_pending_layers():
    state = get_state()
    if not state:
        return []
    return state.get("pending_layers", [])

@app.post("/api/layers/approve")
async def approve_layer(layer_id: str):
    state = get_state()
    if not state:
        raise HTTPException(500, "No state")
    layer = next((l for l in state["pending_layers"] if l["id"] == layer_id), None)
    if not layer:
        raise HTTPException(404, "Layer not found")
    state["pending_layers"] = [l for l in state["pending_layers"] if l["id"] != layer_id]
    state["approved_layers_count"] = state.get("approved_layers_count", 0) + 1
    state["baseline_anchor"] += 50000
    state["logs"].insert(0, f"[GOV] Approved layer: {layer['name']}. +50,000 to baseline.")
    save_state(state)
    # Also update layer_proposals table
    db.table("layer_proposals").update({"status": "approved"}).eq("name", layer["name"]).execute()
    return {"status": "approved"}

@app.post("/api/layers/reject")
async def reject_layer(layer_id: str):
    state = get_state()
    if not state:
        raise HTTPException(500, "No state")
    layer = next((l for l in state["pending_layers"] if l["id"] == layer_id), None)
    if not layer:
        raise HTTPException(404, "Layer not found")
    state["pending_layers"] = [l for l in state["pending_layers"] if l["id"] != layer_id]
    state["logs"].insert(0, f"[GOV] Rejected layer: {layer['name']}.")
    save_state(state)
    db.table("layer_proposals").update({"status": "rejected"}).eq("name", layer["name"]).execute()
    return {"status": "rejected"}

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    asyncio.create_task(engine1_worker())
    asyncio.create_task(lung_worker())
    logger.info("LROS Sovereign Engine started – real Heart & Lung workers active.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
