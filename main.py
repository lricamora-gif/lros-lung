# ============================================================================
# LROS – Complete Integrated Backend (Projects 1,2,3) – STABLE VERSION
# ============================================================================

import os
import asyncio
import random
import logging
import re
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from typing import Optional
import requests

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

# ---------- Constants ----------
AUTO_APPROVE_THRESHOLD = int(os.environ.get("AUTO_APPROVE_THRESHOLD", "5"))
APPROVAL_WORKERS_COUNT = int(os.environ.get("APPROVAL_WORKERS_COUNT", "15"))

# ---------- Helper: Write Audit Log ----------
async def write_audit_log(event_type, description, source, metadata=None):
    db.table("audit_log").insert({
        "event_type": event_type,
        "description": description,
        "source": source,
        "metadata": metadata or {},
        "created_at": datetime.utcnow().isoformat()
    }).execute()

# ---------- State Management ----------
def get_state():
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        default = {
            "baseline_anchor": 1000000,
            "heart_successes": 0,
            "lung_successes": 0,
            "rejections": 0,
            "uses": 0,
            "daily_learning": 0,
            "active_agent": "000",
            "mutation_ledger": [],
            "logs": [],
            "pending_layers": [],
            "approved_layers_count": 0,
            "knowledge_vault": []
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default}).execute()
        return default
    return res.data[0]["state_data"]

def save_state(state):
    db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# ---------- Ensure initial valid pending layer ----------
async def ensure_initial_layer():
    state = get_state()
    valid = []
    for layer in state.get("pending_layers", []):
        layer_id = layer.get("id")
        if not layer_id:
            continue
        try:
            res = db.table("layer_proposals").select("id").eq("id", layer_id).execute()
            if res.data:
                valid.append(layer)
        except:
            pass
    if len(valid) != len(state.get("pending_layers", [])):
        state["pending_layers"] = valid
        save_state(state)
    if not state.get("pending_layers"):
        result = db.table("layer_proposals").insert({
            "name": "Genesis Anchor Layer",
            "description": "Initial stability layer. Establishes baseline governance.",
            "status": "pending",
            "type": "system",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        layer_id = result.data[0]["id"]
        state["pending_layers"].append({"id": layer_id, "name": "Genesis Anchor Layer", "description": "Initial stability layer."})
        save_state(state)
        await write_audit_log("SYSTEM_LAYER", "Created initial anchor layer", "system")

# ---------- AI Caller (DeepSeek + Gemini fallback) ----------
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

# ---------- Cycle Counters ----------
def get_config_int(key, default=0):
    res = db.table("system_config").select("value").eq("key", key).execute()
    if res.data:
        return int(res.data[0]["value"])
    db.table("system_config").insert({"key": key, "value": str(default)}).execute()
    return default

def inc_config(key):
    val = get_config_int(key) + 1
    db.table("system_config").upsert({"key": key, "value": str(val)}).execute()
    return val

def set_config(key, val):
    db.table("system_config").upsert({"key": key, "value": str(val)}).execute()

# ---------- Mandatory Layer Generator ----------
def create_fallback_layer(reason: str, layer_type: str = "auto_enforced"):
    name = f"Cycle‑enforced improvement ({reason})"
    description = "Automatically generated to comply with mandatory layer rule."
    result = db.table("layer_proposals").insert({
        "name": name,
        "description": description,
        "status": "pending",
        "type": layer_type,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    layer_id = result.data[0]["id"]
    state = get_state()
    state["pending_layers"].append({"id": layer_id, "name": name, "description": description})
    save_state(state)
    asyncio.create_task(write_audit_log("MANDATORY_PROPOSAL_CREATED", f"Fallback layer for {reason}", "system"))

# ---------- Heart Worker ----------
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

# ---------- Core Approval Logic (idempotent, fast for auto) ----------
async def approve_layer_by_id(layer_id: str, auto: bool = True):
    check = db.table("layer_proposals").select("status").eq("id", layer_id).execute()
    if not check.data:
        logger.error(f"Layer {layer_id} not found")
        return
    if check.data[0]["status"] == "approved":
        return

    res = db.table("layer_proposals").select("*").eq("id", layer_id).execute()
    if not res.data:
        return
    layer = res.data[0]

    db.table("layer_proposals").update({
        "status": "approved",
        "approved_at": datetime.utcnow().isoformat()
    }).eq("id", layer_id).execute()

    name = layer["name"].lower()
    desc = layer["description"].lower()
    impact = "System performance improved."
    if "threshold" in name or "threshold" in desc:
        numbers = re.findall(r"\d+", desc + name)
        if numbers:
            new_threshold = int(numbers[0])
            db.table("system_config").upsert({
                "key": "ombudsman_threshold",
                "value": str(new_threshold),
                "updated_at": datetime.utcnow().isoformat()
            }).execute()
            impact = f"Ombudsman threshold adjusted to {new_threshold}%."

    state = get_state()
    learning_increment = 0.1
    state["daily_learning"] = state.get("daily_learning", 0) + learning_increment
    state["approved_layers_count"] = state.get("approved_layers_count", 0) + 1
    state["baseline_anchor"] += 50000
    state["pending_layers"] = [p for p in state.get("pending_layers", []) if p.get("id") != layer_id]
    state["logs"].insert(0, f"[GOV] {'Auto-approved' if auto else 'Approved'} layer: {layer['name']}. +50,000 baseline. Learning +{learning_increment}%.")
    save_state(state)

    if state["approved_layers_count"] % 1000 == 0:
        state["logs"].insert(0, f"[MILESTONE] {state['approved_layers_count']} layers approved.")
        save_state(state)
        await write_audit_log("LAYER_MILESTONE", f"{state['approved_layers_count']} layers approved", "system")

    # Quorum only for manual approvals
    if not auto:
        total_agents = 200
        half = total_agents // 2
        explanation = f"Layer '{layer['name']}' approved. {layer['description']}. Advantage: {impact}"
        for i in range(1, half+1):
            db.table("agent_messages").insert({
                "layer_id": layer["id"],
                "agent_id": str(i),
                "message": explanation,
                "round": 1,
                "sent_at": datetime.utcnow().isoformat()
            }).execute()
        for i in range(half+1, total_agents+1):
            db.table("agent_messages").insert({
                "layer_id": layer["id"],
                "agent_id": str(i),
                "message": f"Agent {random.randint(1,half)} explained: {explanation}",
                "round": 2,
                "sent_at": datetime.utcnow().isoformat()
            }).execute()

    if state["approved_layers_count"] % 5 == 0:
        state["logs"].insert(0, f"[KNOWLEDGE EXCHANGE] {state['approved_layers_count']} layers approved.")
        save_state(state)
        await write_audit_log("KNOWLEDGE_EXCHANGE", f"Cycle {state['approved_layers_count']}", "system")

    if state["approved_layers_count"] % 100 == 0:
        asyncio.create_task(run_retrospective_analysis(state["approved_layers_count"]))

    await write_audit_log("LAYER_APPROVED", f"Layer '{layer['name']}' approved", "governance")

# ---------- Approval Worker (parallel) ----------
async def approval_worker(worker_id: int):
    while True:
        try:
            state = get_state()
            pending = state.get("pending_layers", [])
            if len(pending) >= AUTO_APPROVE_THRESHOLD:
                layer = pending[0]
                layer_id = layer.get("id")
                if layer_id:
                    await approve_layer_by_id(layer_id, auto=True)
                await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Approval worker {worker_id} error: {e}")
            await asyncio.sleep(1)

# ---------- Lung Worker ----------
async def lung_worker():
    threshold = get_config_int("ombudsman_threshold", 85)
    models = ["deepseek", "mistral", "groq", "gemini", "cerebras"]
    domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"]
    while True:
        try:
            mutation_cycle = inc_config("mutation_cycle")
            last_proposal = get_config_int("last_proposal_cycle")
            expected = mutation_cycle // 5
            if expected > last_proposal:
                for missing in range(last_proposal + 1, expected + 1):
                    create_fallback_layer(f"Mutation cycle {missing*5}", "mutation_mandatory")
                set_config("last_proposal_cycle", expected)

            approved_layers = db.table("layer_proposals").select("name","description").eq("status","approved").order("approved_at", desc=True).limit(5).execute()
            vault = db.table("knowledge_vault").select("content").limit(5).execute()
            patterns = db.table("pattern_library").select("content","domain").order("uses", desc=True).limit(3).execute()
            context = ""
            if approved_layers.data:
                context += "Approved improvements: " + "; ".join([f"{l['name']}: {l['description']}" for l in approved_layers.data]) + "\n"
            if vault.data:
                context += "Recent knowledge: " + "; ".join([v["content"][:100] for v in vault.data]) + "\n"
            if patterns.data:
                context += "Successful patterns:\n" + "\n".join([f"- {p['content']} (domain: {p['domain']})" for p in patterns.data]) + "\n"

            domain = random.choice(domains)
            model = random.choice(models)
            prompt = f"Generate a novel mutation strategy in domain: {domain}. Use context:\n{context}\nStrategy:"
            content = call_ai(prompt, temperature=0.8)
            if not content or content.startswith("[Simulated]"):
                content = f"Optimization strategy for {domain}: Increase efficiency by {random.randint(5,30)}% using {model} model."

            score_prompt = f"Rate from 0 to 100 (100 perfect). Return only integer.\nStrategy: {content}\nScore:"
            score_resp = call_ai(score_prompt, temperature=0.2)
            try:
                oScore = int(score_resp.strip())
                oScore = max(0, min(100, oScore))
            except:
                oScore = random.randint(50, 100)

            agent = str(random.randint(1, 500)).zfill(3)
            state = get_state()
            if oScore >= threshold:
                state["lung_successes"] += 1
                log = f"✅ [EVOLVE] {model} accepted (Score: {oScore}) - {domain}"
                veto_reason = None
                existing = db.table("pattern_library").select("id").eq("content", content).eq("domain", domain).execute()
                if existing.data:
                    db.table("pattern_library").update({
                        "uses": existing.data[0]["uses"] + 1,
                        "last_used": datetime.utcnow().isoformat()
                    }).eq("id", existing.data[0]["id"]).execute()
                else:
                    db.table("pattern_library").insert({
                        "content": content,
                        "domain": domain,
                        "score": oScore,
                        "source": model,
                        "created_at": datetime.utcnow().isoformat()
                    }).execute()
            else:
                state["rejections"] += 1
                log = f"⛔ [VETO] {model} rejected (Score: {oScore} < {threshold}) - {domain}"
                veto_reason = f"Score {oScore} below threshold"
                patterns_ref = db.table("pattern_library").select("content").order("uses", desc=True).limit(2).execute()
                if patterns_ref.data:
                    refine_prompt = f"Original vetoed: {content}\nSuccessful pattern: {patterns_ref.data[0]['content']}\nEdit original to be more like pattern, keep domain {domain}. Output only edited mutation."
                    refined = call_ai(refine_prompt, temperature=0.7)
                    if refined and refined != content:
                        result = db.table("layer_proposals").insert({
                            "name": "Refined mutation proposal",
                            "description": refined,
                            "status": "pending",
                            "type": "mutation_refinement",
                            "created_at": datetime.utcnow().isoformat()
                        }).execute()
                        layer_id = result.data[0]["id"]
                        state["pending_layers"].append({"id": layer_id, "name": "Refined mutation", "description": refined})
                        save_state(state)
                        await write_audit_log("REFINEMENT_PROPOSAL", f"Refined vetoed mutation", "lung")

            db.table("mutations").insert({
                "content": content,
                "score": oScore,
                "source": model,
                "timestamp": datetime.utcnow().isoformat(),
                "domain": domain,
                "agent": agent,
                "veto_reason": veto_reason
            }).execute()

            state["logs"].insert(0, log)
            if len(state["logs"]) > 30:
                state["logs"] = state["logs"][:30]
            save_state(state)
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(1.2)

# ---------- Retrospective Analysis ----------
async def run_retrospective_analysis(cycle_number):
    vetoed = db.table("mutations").select("content","score","veto_reason","domain").lt("score",85).order("timestamp", desc=True).limit(200).execute()
    if not vetoed.data:
        return
    error_counts = {}
    for m in vetoed.data:
        reason = m.get("veto_reason") or f"Score {m['score']} below threshold"
        error_counts[reason] = error_counts.get(reason, 0) + 1
    top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    for err, freq in top_errors:
        db.table("error_analysis").insert({
            "cycle_number": cycle_number,
            "error_pattern": err,
            "frequency": freq,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    prompt = f"Top errors causing rejections: {top_errors}. Propose 5 layer improvements (name, description) as JSON array."
    try:
        response = call_ai(prompt, temperature=0.7)
        proposals = json.loads(response)
        for prop in proposals[:5]:
            result = db.table("layer_proposals").insert({
                "name": prop["name"],
                "description": prop["description"],
                "status": "pending",
                "type": "error_prevention",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            layer_id = result.data[0]["id"]
            state = get_state()
            state["pending_layers"].append({"id": layer_id, "name": prop["name"], "description": prop["description"]})
            save_state(state)
    except Exception as e:
        logger.error(f"Retrospective analysis failed: {e}")
    total_agents = 200
    msg = f"Retrospective Cycle {cycle_number}: Top errors: {top_errors[0][0] if top_errors else 'none'}. New layers proposed."
    for i in range(1, total_agents+1):
        db.table("agent_messages").insert({
            "layer_id": None,
            "agent_id": str(i),
            "message": msg,
            "round": 0,
            "sent_at": datetime.utcnow().isoformat()
        }).execute()
    await write_audit_log("RETROSPECTIVE_ANALYSIS", f"Cycle {cycle_number}: Analyzed {len(vetoed.data)} vetoes", "system")

# ---------- Endpoints ----------
@app.post("/api/ingest")
async def ingest_knowledge(file: Optional[UploadFile] = File(None), url: Optional[str] = Form(None), text: Optional[str] = Form(None)):
    try:
        if file:
            content = (await file.read()).decode("utf-8", errors="ignore")
            source = f"File: {file.filename}"
        elif url:
            resp = requests.get(url, timeout=15)
            content = resp.text[:5000]
            source = f"URL: {url}"
        elif text:
            content = text[:5000]
            source = "Raw text"
        else:
            raise HTTPException(400, "No file, URL, or text provided")
        db.table("knowledge_vault").insert({
            "content": content,
            "source": source,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        ingestion_cycle = inc_config("ingestion_cycle")
        last_proposal = get_config_int("last_proposal_cycle")
        expected = ingestion_cycle // 5
        if expected > last_proposal:
            for missing in range(last_proposal + 1, expected + 1):
                create_fallback_layer(f"Ingestion cycle {missing*5}", "ingestion_mandatory")
            set_config("last_proposal_cycle", expected)
        state = get_state()
        state["heart_successes"] += 5000
        state["uses"] += 25000
        state["daily_learning"] += 500.5
        state["logs"].insert(0, f"[VAULT] Ingested {source}. +5,000 heart successes.")
        save_state(state)
        await write_audit_log("INGESTION", f"Ingested {source}", "frontend")
        return {"status": "ingested", "mass_gain": 5000}
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/layers/propose")
async def propose_layer(request: dict):
    name = request.get("name")
    description = request.get("description")
    layer_type = request.get("type", "user")
    if not name or not description:
        raise HTTPException(400, "Missing name or description")
    result = db.table("layer_proposals").insert({
        "name": name,
        "description": description,
        "status": "pending",
        "type": layer_type,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    layer_id = result.data[0]["id"]
    state = get_state()
    state["pending_layers"].append({"id": layer_id, "name": name, "description": description})
    save_state(state)
    await write_audit_log("LAYER_PROPOSED", f"Layer '{name}' proposed", "frontend")
    return {"status": "proposed"}

@app.get("/api/layers/pending")
async def get_pending_layers():
    state = get_state()
    return state.get("pending_layers", [])

@app.post("/api/layers/approve")
async def approve_layer(layer_id: str):
    await approve_layer_by_id(layer_id, auto=False)
    return {"status": "approved"}

@app.post("/api/layers/reject")
async def reject_layer(layer_id: str):
    db.table("layer_proposals").update({"status": "rejected"}).eq("id", layer_id).execute()
    state = get_state()
    state["pending_layers"] = [p for p in state.get("pending_layers", []) if p.get("id") != layer_id]
    save_state(state)
    await write_audit_log("LAYER_REJECTED", f"Layer {layer_id} rejected", "governance")
    return {"status": "rejected"}

@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_state()
    total = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
    old = state["baseline_anchor"]
    state["baseline_anchor"] = total
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    state["logs"].insert(0, f"[ANCHOR] Baseline locked from {old} to {total:,}")
    save_state(state)
    db.table("memory_logs").insert({
        "event_type": "BASELINE_ANCHOR",
        "description": f"Baseline anchored from {old} to {total}",
        "master_tally": total,
        "baseline": total,
        "heart_total": 0,
        "lung_total": 0,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    await write_audit_log("BASELINE_ANCHOR", f"Baseline locked to {total}", "user")
    return {"status": "success", "new_baseline": total}

@app.get("/api/admin/diagnostic")
async def diagnostic():
    state = get_state()
    mutations = db.table("mutations").select("score", "source", "timestamp", "veto_reason").order("timestamp", desc=True).limit(10).execute()
    return {
        "lung_successes": state.get("lung_successes", 0),
        "heart_successes": state.get("heart_successes", 0),
        "rejections": state.get("rejections", 0),
        "approved_layers_count": state.get("approved_layers_count", 0),
        "pending_layers_count": len(state.get("pending_layers", [])),
        "last_10_mutations": mutations.data if mutations.data else [],
        "threshold": get_config_int("ombudsman_threshold", 85),
        "workers": APPROVAL_WORKERS_COUNT,
        "auto_approve_threshold": AUTO_APPROVE_THRESHOLD
    }

@app.post("/api/admin/set_threshold/{new_threshold}")
async def set_threshold(new_threshold: int):
    new_threshold = max(0, min(100, new_threshold))
    db.table("system_config").upsert({
        "key": "ombudsman_threshold",
        "value": str(new_threshold),
        "updated_at": datetime.utcnow().isoformat()
    }).execute()
    await write_audit_log("THRESHOLD_CHANGE", f"Set to {new_threshold}", "admin")
    return {"new_threshold": new_threshold}

@app.post("/api/admin/reset_counters")
async def reset_counters():
    state = get_state()
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    state["rejections"] = 0
    state["uses"] = 0
    state["daily_learning"] = 0
    state["baseline_anchor"] = 1000000
    state["approved_layers_count"] = 0
    save_state(state)
    await write_audit_log("ADMIN_RESET", "Counters reset", "admin")
    return {"status": "reset"}

@app.post("/api/admin/cleanup_pending_layers")
async def admin_cleanup_pending_layers():
    state = get_state()
    old_pending = state.get("pending_layers", [])
    valid_pending = []
    removed = []
    for layer in old_pending:
        layer_id = layer.get("id")
        if not layer_id:
            removed.append(layer)
            continue
        try:
            res = db.table("layer_proposals").select("id").eq("id", layer_id).execute()
            if res.data:
                valid_pending.append(layer)
            else:
                removed.append(layer)
        except Exception:
            removed.append(layer)
    state["pending_layers"] = valid_pending
    save_state(state)
    if not valid_pending:
        result = db.table("layer_proposals").insert({
            "name": "Safe Anchor Layer",
            "description": "Auto‑created after cleanup.",
            "status": "pending",
            "type": "system",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        new_id = result.data[0]["id"]
        state["pending_layers"].append({"id": new_id, "name": "Safe Anchor Layer", "description": "Auto‑created after cleanup."})
        save_state(state)
    await write_audit_log("ADMIN_CLEANUP", f"Removed {len(removed)} invalid entries.", "admin")
    return {"removed_count": len(removed), "kept_count": len(valid_pending), "removed_examples": [l.get("id") for l in removed[:10]]}

@app.get("/api/admin/queue_status")
async def queue_status():
    state = get_state()
    pending = state.get("pending_layers", [])
    return {
        "pending_count": len(pending),
        "latest_pending_ids": [p.get("id") for p in pending[:5]],
        "approved_layers_count": state.get("approved_layers_count", 0),
        "lung_successes": state.get("lung_successes", 0),
        "threshold": AUTO_APPROVE_THRESHOLD,
        "workers": APPROVAL_WORKERS_COUNT
    }

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

@app.get("/api/mutations")
async def get_mutations():
    res = db.table("mutations").select("*").order("timestamp", desc=True).limit(20).execute()
    return res.data

@app.get("/api/state")
async def get_full_state():
    state = get_state()
    return {
        "baseline": state.get("baseline_anchor", 0),
        "heart_successes": state.get("heart_successes", 0),
        "lung_successes": state.get("lung_successes", 0),
        "rejections": state.get("rejections", 0),
        "uses": state.get("uses", 0),
        "daily_learning": state.get("daily_learning", 0),
        "active_agent": state.get("active_agent", "000"),
        "approved_layers_count": state.get("approved_layers_count", 0),
        "mutation_ledger": state.get("mutation_ledger", []),
        "logs": state.get("logs", []),
        "pending_layers": state.get("pending_layers", []),
        "knowledge_vault": state.get("knowledge_vault", [])
    }

@app.get("/api/engine1/stats")
async def get_engine1_stats():
    state = get_state()
    return {"total_successes": state.get("heart_successes", 0), "last_thought": ""}

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

@app.get("/api/check/mandatory_cycles")
async def check_mandatory_cycles():
    mutation_cycle = get_config_int("mutation_cycle")
    ingestion_cycle = get_config_int("ingestion_cycle")
    last_proposal = get_config_int("last_proposal_cycle")
    expected = max(mutation_cycle // 5, ingestion_cycle // 5)
    if expected > last_proposal:
        for missing in range(last_proposal + 1, expected + 1):
            create_fallback_layer(f"Auto‑recovered cycle {missing*5}", "auto_enforced")
        set_config("last_proposal_cycle", expected)
    return {"status": "ok", "missed_filled": expected - last_proposal}

# ---------- EOD Report ----------
async def generate_eod_report():
    now = datetime.utcnow()
    today = now.date()
    approved_today = db.table("layer_proposals").select("id").eq("status","approved").gte("approved_at", f"{today}T00:00:00Z").execute()
    total_approved = len(approved_today.data)
    improvements = db.table("layer_proposals").select("id").eq("type","error_prevention").gte("approved_at", f"{today}T00:00:00Z").execute()
    state = get_state()
    learning = state.get("daily_learning", 0)
    top_errors = db.table("error_analysis").select("error_pattern","frequency").order("created_at", desc=True).limit(3).execute()
    report_text = f"EOD Report {today}\nTotal layers approved today: {total_approved}\nImprovements: {len(improvements.data)}\nTop errors: {top_errors.data if top_errors.data else 'none'}\nLearning: {learning:.2f}%"
    db.table("eod_reports").insert({
        "report_date": today.isoformat(),
        "total_layers_approved": total_approved,
        "improvements": len(improvements.data),
        "top_errors": top_errors.data,
        "learning_percentage": learning,
        "report_text": report_text,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    for i in range(1, 201):
        db.table("agent_messages").insert({
            "layer_id": None,
            "agent_id": str(i),
            "message": report_text,
            "round": 0,
            "sent_at": datetime.utcnow().isoformat()
        }).execute()
    logger.info(f"EOD report generated for {today}")

async def schedule_eod():
    while True:
        now = datetime.utcnow()
        next_run = datetime(now.year, now.month, now.day, 23, 59, 0)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        await generate_eod_report()

# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    await ensure_initial_layer()
    asyncio.create_task(heart_worker())
    asyncio.create_task(lung_worker())
    for i in range(APPROVAL_WORKERS_COUNT):
        asyncio.create_task(approval_worker(i))
    asyncio.create_task(schedule_eod())
    logger.info(f"LROS started – threshold={AUTO_APPROVE_THRESHOLD}, workers={APPROVAL_WORKERS_COUNT}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
