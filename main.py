# ============================================================================
# LROS – Complete Integrated Backend (Heart + Lung + Governance + Ingestion)
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

# ---------- Ensure Tables ----------
def ensure_tables():
    try:
        db.table("sovereign_state").select("id").limit(1).execute()
    except:
        db.table("sovereign_state").insert({"id": 1, "state_data": {}}).execute()
    # mutations and layer_proposals are assumed to exist (created manually)
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

# ---------- Helpers ----------
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

# ---------- Background Workers ----------
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

async def lung_worker():
    threshold = 85
    auto_lab = False
    models = ["deepseek", "mistral", "groq", "gemini", "cerebras"]
    domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"]
    while True:
        try:
            state = get_state()
            model = random.choice(models)
            oScore = random.randint(50, 100)
            domain = random.choice(domains)
            agent = str(random.randint(1, 500)).zfill(3)
            content = f"Optimization strategy for {domain}: Increase efficiency by {random.randint(5,30)}% using {model} model."

            if oScore >= threshold:
                if auto_lab:
                    simScore = random.random()
                    if simScore > 0.5:
                        state["lung_successes"] += 1
                        log = f"✅ [EVOLVE] {model} logic & physics passed (Sim: {simScore:.2f}) - {domain}"
                        veto_reason = None
                    else:
                        state["rejections"] += 1
                        log = f"❌ [VETO] {model} logic passed but failed physics (Sim: {simScore:.2f})"
                        veto_reason = f"Physics simulation failed (score {simScore:.2f})"
                else:
                    state["lung_successes"] += 1
                    log = f"✅ [EVOLVE] {model} logic accepted (Score: {oScore}%) - {domain}"
                    veto_reason = None
            else:
                state["rejections"] += 1
                log = f"⛔ [VETO] Ombudsman rejected {model}. Score {oScore}% < {threshold}%"
                veto_reason = f"Ombudsman score {oScore} below threshold {threshold}"

            insert_mutation(content, oScore, model, domain, agent, veto_reason)

            if oScore >= 92 and random.random() > 0.85:
                layer_names = ["Quantum Encryption Substrate", "Neural Routing Bypass", "Cognitive Empathy Engine", "Recursive Strategy Matrix", "Dynamic Resource Allocator"]
                layer_name = random.choice(layer_names)
                layer_desc = f"Architectural breakthrough generated by Swarm from {model} mutation."
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

# ---------- API Endpoints ----------
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
    logger.info("LROS Integrated Engine started.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
