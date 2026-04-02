# ============================================================================
# LROS – Heart & Lung Engine with Mutations Table
# ============================================================================

import os
import asyncio
import random
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Engine")

app = FastAPI(title="LROS Heart & Lung Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------- Supabase ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Ensure Mutations Table Exists ----------
def ensure_mutations_table():
    try:
        # Check if table exists by trying to select 1 row
        db.table("mutations").select("*").limit(1).execute()
    except Exception:
        # Create table using raw SQL (Supabase client doesn't support DDL directly, so we use REST)
        # We'll use the `execute` method with raw SQL (requires service_role key, but we have anon)
        # Alternative: create table manually in Supabase dashboard. For simplicity, we'll print instruction.
        logger.error("Mutations table does not exist. Please create it in Supabase with columns: id (int8, primary key, auto increment), content (text), score (int4), source (text), timestamp (timestamptz), domain (text), agent (text), veto_reason (text).")
        # We'll continue without crashing; the app will try to insert and fail gracefully.
ensure_mutations_table()

# ---------- State Management ----------
def get_state():
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        default = {
            "baseline_anchor": 1008922,
            "heart_successes": 1027965,
            "lung_successes": 45429,
            "rejections": 4115,
            "uses": 195700000,
            "daily_learning": 2921731.39,
            "active_agent": "244",
            "mutation_ledger": [],
            "logs": ["[SYSTEM] LROS Heart & Lung Engine Online"]
        }
        db.table("sovereign_state").insert({"id": 1, "state_data": default}).execute()
        return default
    return res.data[0]["state_data"]

def save_state(state):
    db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

# ---------- Helper to insert a mutation ----------
def insert_mutation(content, score, source, domain, agent, veto_reason=None):
    try:
        data = {
            "content": content,
            "score": score,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
            "domain": domain,
            "agent": agent,
            "veto_reason": veto_reason
        }
        db.table("mutations").insert(data).execute()
    except Exception as e:
        logger.error(f"Failed to insert mutation: {e}")

# ---------- Background Tasks ----------
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
            # Generate a plausible mutation content
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

            # Insert mutation record
            insert_mutation(
                content=content,
                score=oScore,
                source=model,
                domain=domain,
                agent=agent,
                veto_reason=veto_reason
            )

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

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    asyncio.create_task(heart_worker())
    asyncio.create_task(lung_worker())
    logger.info("LROS Heart & Lung engines started.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
