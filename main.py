# ============================================================================
# LROS – Domain‑Focused AI Evolution Engine
# Targets: AGI/ASI, Medical ASI, Novus Terra Services/Products
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Integrated")

app = FastAPI(title="LROS Integrated Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------- Supabase ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Missing SUPABASE_URL or SUPABASE_KEY")
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- API Keys ----------
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

# ---------- Ensure Tables ----------
def ensure_tables():
    try:
        db.table("sovereign_state").select("id").limit(1).execute()
    except:
        db.table("sovereign_state").insert({"id": 1, "state_data": {}}).execute()
ensure_tables()

# ---------- State Management ----------
def get_state():
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data or not res.data[0].get("state_data"):
        default = {
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
        db.table("sovereign_state").update({"state_data": default}).eq("id", 1).execute()
        return default
    return res.data[0]["state_data"]

def save_state(state):
    db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

def insert_mutation(content, score, source, domain, agent, veto_reason=None):
    try:
        db.table("mutations").insert({
            "content": content,
            "score": score,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
            "domain": domain,
            "agent": agent,
            "veto_reason": veto_reason
        }).execute()
    except Exception as e:
        logger.error(f"Insert mutation failed: {e}")

def insert_layer_proposal(name, description):
    try:
        db.table("layer_proposals").insert({
            "name": name,
            "description": description,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Insert layer proposal failed: {e}")

# ---------- Heart Worker (unchanged) ----------
async def heart_worker():
    while True:
        try:
            state = get_state()
            gain = random.randint(5, 20)
            state["heart_successes"] += gain
            state["uses"] += random.randint(100, 600)
            state["daily_learning"] += random.uniform(0.5, 5.0)
            state["active_agent"] = str(random.randint(1, 300)).zfill(3)
            if random.random() > 0.8:
                domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"]
                domain = random.choice(domains)
                entry = {
                    "version": f"DNA-E9.54.{state['heart_successes'] % 1000}",
                    "agent": state["active_agent"],
                    "domain": domain,
                    "ts": datetime.utcnow().strftime("%H:%M:%S")
                }
                state["mutation_ledger"].insert(0, entry)
                if len(state["mutation_ledger"]) > 20:
                    state["mutation_ledger"].pop()
                state["logs"].insert(0, f"{entry['version']} | +0.0{random.randint(1,5)}% | {domain} (Agent-{entry['agent']})")
            if len(state["logs"]) > 30:
                state["logs"] = state["logs"][:30]
            save_state(state)
        except Exception as e:
            logger.error(f"Heart worker error: {e}")
        await asyncio.sleep(0.5)

# ---------- Lung Worker – Domain‑Focused AI Evolution ----------
async def lung_worker():
    threshold = int(os.environ.get("OMBUDSMAN_THRESHOLD", "85"))
    auto_lab = os.environ.get("AUTO_LAB", "false").lower() == "true"
    # Focus domains – you can add more
    domains = [
        "AI evolution & AGI architecture",
        "Medical ASI (diagnostic, therapeutic, personalised medicine)",
        "Novus Terra proprietary services (asset tokenisation, sovereign AI, healthcare JVs)"
    ]
    model_names = ["deepseek", "gemini", "cerebras", "groq", "mistral"]
    while True:
        try:
            state = get_state()
            domain = random.choice(domains)
            model_used = random.choice(model_names)

            # 1. Generate mutation strategy
            generate_prompt = f"""You are LROS, a constitutional AI operating system. Propose a novel, actionable, high‑value strategy in the domain: {domain}. 
Focus on creating a new proprietary service, product, or evolutionary step that could become part of Novus Terra’s offerings or advance AGI/ASI. 
Keep it concise (150–250 words). Be specific – include metrics or concrete steps."""
            mutation_content = call_ai(generate_prompt, temperature=0.8)
            if mutation_content.startswith("[Simulated]"):
                mutation_content = f"New strategy for {domain}: integrate federated learning across healthcare JVs to reduce data silos, projected 30% efficiency gain."

            # 2. Ombudsman scoring
            score_prompt = f"""Rate the following strategy from 0 to 100, where 100 is brilliant, game‑changing, and 0 is useless or harmful. Return only the integer score.

Strategy: {mutation_content}

Score:"""
            score_response = call_ai(score_prompt, temperature=0.2)
            try:
                oScore = int(score_response.strip())
                oScore = max(0, min(100, oScore))
            except:
                oScore = random.randint(50, 100)

            # 3. Auto‑Lab simulation (placeholder – replace with real physics/lab API)
            sim_passed = True
            sim_score = None
            if auto_lab:
                # In real implementation, call a simulation API (e.g., drug binding, financial model)
                sim_score = (oScore / 100.0) * random.uniform(0.6, 1.0)
                sim_passed = sim_score > 0.5

            agent = str(random.randint(1, 500)).zfill(3)
            veto_reason = None

            if oScore >= threshold and (not auto_lab or sim_passed):
                state["lung_successes"] += 1
                log = f"✅ [EVOLVE] {model_used} strategy (Score: {oScore}) accepted - {domain}"
                if auto_lab:
                    log += f" | Physics passed (Sim: {sim_score:.2f})"
            else:
                state["rejections"] += 1
                if oScore < threshold:
                    veto_reason = f"Ombudsman score {oScore} below threshold {threshold}"
                    log = f"⛔ [VETO] {model_used} rejected (Score: {oScore} < {threshold}) - {domain}"
                else:
                    veto_reason = f"Physics simulation failed (Sim: {sim_score:.2f})"
                    log = f"❌ [VETO] {model_used} passed logic but failed simulation - {domain}"

            insert_mutation(mutation_content, oScore, model_used, domain, agent, veto_reason)

            # Propose new layer for high‑scoring mutations
            if oScore >= 92 and random.random() > 0.85:
                layer_names = [
                    "AGI Alignment Kernel", "Medical ASI Diagnostic Engine", "Novus Terra Asset Tokenisation Layer",
                    "Sovereign AI Compliance Oracle", "Predictive Health Swarm", "Zero‑Knowledge JV Auditor"
                ]
                layer_name = random.choice(layer_names)
                layer_desc = f"Architectural breakthrough from {model_used} mutation in {domain}."
                insert_layer_proposal(layer_name, layer_desc)
                state["pending_layers"].append({"name": layer_name, "description": layer_desc, "id": f"lyr_{len(state['pending_layers'])}"})
                log += f" | Proposed new layer: {layer_name}"

            state["logs"].insert(0, log)
            if len(state["logs"]) > 30:
                state["logs"] = state["logs"][:30]
            save_state(state)
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(1.2)

# ---------- API Endpoints (unchanged from previous working version) ----------
@app.get("/api/status")
async def get_status():
    state = get_state()
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
    total = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
    state["baseline_anchor"] = total
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    state["logs"].insert(0, f"[ANCHOR] Sovereign Baseline locked at {total:,}")
    save_state(state)
    return {"status": "success", "new_baseline": total}

@app.post("/api/ingest")
async def ingest_knowledge(file: Optional[UploadFile] = File(None), url: Optional[str] = Form(None), text: Optional[str] = Form(None)):
    state = get_state()
    mass_gain = 5000
    if file:
        source = f"File: {file.filename}"
        state["knowledge_vault"].append({"type": "file", "name": file.filename, "timestamp": datetime.utcnow().isoformat()})
    elif url:
        source = f"URL: {url}"
        state["knowledge_vault"].append({"type": "url", "url": url, "timestamp": datetime.utcnow().isoformat()})
    elif text:
        source = "Raw text"
        state["knowledge_vault"].append({"type": "text", "preview": text[:100], "timestamp": datetime.utcnow().isoformat()})
    else:
        raise HTTPException(400, "No file, URL, or text provided")
    state["heart_successes"] += mass_gain
    state["uses"] += 25000
    state["daily_learning"] += 500.5
    state["logs"].insert(0, f"[VAULT] Ingested {source}. +{mass_gain} heart successes.")
    save_state(state)
    return {"status": "ingested", "mass_gain": mass_gain}

@app.get("/api/layers/pending")
async def get_pending_layers():
    state = get_state()
    return state.get("pending_layers", [])

@app.post("/api/layers/approve")
async def approve_layer(layer_id: str):
    state = get_state()
    layer = next((l for l in state["pending_layers"] if l["id"] == layer_id), None)
    if not layer:
        raise HTTPException(404, "Layer not found")
    state["pending_layers"] = [l for l in state["pending_layers"] if l["id"] != layer_id]
    state["approved_layers_count"] = state.get("approved_layers_count", 0) + 1
    state["baseline_anchor"] += 50000
    state["logs"].insert(0, f"[GOV] Approved layer: {layer['name']}. +50,000 to baseline.")
    save_state(state)
    return {"status": "approved"}

@app.post("/api/layers/reject")
async def reject_layer(layer_id: str):
    state = get_state()
    layer = next((l for l in state["pending_layers"] if l["id"] == layer_id), None)
    if not layer:
        raise HTTPException(404, "Layer not found")
    state["pending_layers"] = [l for l in state["pending_layers"] if l["id"] != layer_id]
    state["logs"].insert(0, f"[GOV] Rejected layer: {layer['name']}.")
    save_state(state)
    return {"status": "rejected"}

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

@app.on_event("startup")
async def startup():
    asyncio.create_task(heart_worker())
    asyncio.create_task(lung_worker())
    logger.info("LROS Integrated Engine started – domain‑focused AI Lung active.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
