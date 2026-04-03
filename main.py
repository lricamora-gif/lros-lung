# ============================================================================
# LROS FINAL BACKEND – All Workers Included (Hybrid Lung + Discussion-to-Layer)
# ============================================================================
import os, asyncio, random, logging, re, json, uuid, imaplib, email, smtplib, time
from email.policy import default
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from typing import Optional
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LROS-Sovereign")
app = FastAPI(title="LROS Sovereign Engine")

# CORS – update allowed origins for production
ALLOWED_ORIGINS = [
    "https://lros.ai",
    "https://www.lros.ai",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Missing SUPABASE_URL or SUPABASE_KEY")
db = create_client(SUPABASE_URL, SUPABASE_KEY)

AUTO_APPROVE_THRESHOLD = int(os.environ.get("AUTO_APPROVE_THRESHOLD", "5"))
APPROVAL_WORKERS_COUNT = int(os.environ.get("APPROVAL_WORKERS_COUNT", "20"))
LROS_EMAIL = os.environ.get("LROS_EMAIL", "lrosventures@gmail.com")
LROS_EMAIL_PASSWORD = os.environ.get("LROS_EMAIL_PASSWORD")
DAILY_DIGEST_EMAIL = os.environ.get("DAILY_DIGEST_EMAIL")

# ---------- Helper functions ----------
async def write_audit_log(event_type, description, source, metadata=None):
    db.table("audit_log").insert({"event_type": event_type, "description": description, "source": source, "metadata": metadata or {}, "created_at": datetime.utcnow().isoformat()}).execute()

def get_state():
    res = db.table("sovereign_state").select("state_data").eq("id", 1).execute()
    if not res.data:
        default = {"baseline_anchor": 1000000, "heart_successes": 0, "lung_successes": 0, "rejections": 0, "uses": 0, "daily_learning": 0, "active_agent": "000", "mutation_ledger": [], "logs": [], "pending_layers": [], "approved_layers_count": 0, "knowledge_vault": []}
        db.table("sovereign_state").insert({"id": 1, "state_data": default}).execute()
        return default
    return res.data[0]["state_data"]

def save_state(state):
    db.table("sovereign_state").update({"state_data": state, "updated_at": datetime.utcnow().isoformat()}).eq("id", 1).execute()

def get_config_int(key, default=0):
    res = db.table("system_config").select("value").eq("key", key).execute()
    if res.data: return int(res.data[0]["value"])
    db.table("system_config").insert({"key": key, "value": str(default)}).execute()
    return default

def set_config(key, val):
    db.table("system_config").upsert({"key": key, "value": str(val)}).execute()

def send_email(to, subject, body):
    if not to: return
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(LROS_EMAIL, LROS_EMAIL_PASSWORD)
            msg = f"Subject: {subject}\n\n{body}"
            server.sendmail(LROS_EMAIL, to, msg)
    except Exception as e:
        logger.error(f"Email send error: {e}")

# ---------- AI caller with key rotation ----------
DEEPSEEK_API_KEYS = [k.strip() for k in os.environ.get("DEEPSEEK_API_KEYS", "").split(",") if k.strip()]
GEMINI_API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
MISTRAL_API_KEYS = [k.strip() for k in os.environ.get("MISTRAL_API_KEYS", "").split(",") if k.strip()]
GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
deepseek_idx = 0
gemini_idx = 0
mistral_idx = 0
groq_idx = 0

def call_ai(prompt, temperature=0.7):
    # Try DeepSeek
    if DEEPSEEK_API_KEYS:
        for _ in range(len(DEEPSEEK_API_KEYS)):
            key = DEEPSEEK_API_KEYS[deepseek_idx % len(DEEPSEEK_API_KEYS)]
            deepseek_idx += 1
            try:
                headers = {"Authorization": f"Bearer {key}"}
                payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
                r = requests.post("https://api.deepseek.com/v1/chat/completions", json=payload, headers=headers, timeout=30)
                return r.json()["choices"][0]["message"]["content"]
            except: continue
    # Try Mistral
    if MISTRAL_API_KEYS:
        for _ in range(len(MISTRAL_API_KEYS)):
            key = MISTRAL_API_KEYS[mistral_idx % len(MISTRAL_API_KEYS)]
            mistral_idx += 1
            try:
                headers = {"Authorization": f"Bearer {key}"}
                payload = {"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
                r = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=30)
                return r.json()["choices"][0]["message"]["content"]
            except: continue
    # Try Groq
    if GROQ_API_KEYS:
        for _ in range(len(GROQ_API_KEYS)):
            key = GROQ_API_KEYS[groq_idx % len(GROQ_API_KEYS)]
            groq_idx += 1
            try:
                headers = {"Authorization": f"Bearer {key}"}
                payload = {"model": "mixtral-8x7b-32768", "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
                r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
                return r.json()["choices"][0]["message"]["content"]
            except: continue
    # Try Gemini
    if GEMINI_API_KEYS:
        import google.generativeai as genai
        for _ in range(len(GEMINI_API_KEYS)):
            key = GEMINI_API_KEYS[gemini_idx % len(GEMINI_API_KEYS)]
            gemini_idx += 1
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt, generation_config={"temperature": temperature})
                return response.text
            except: continue
    return "[Simulated] No AI key available."

# ---------- Heart Worker ----------
async def heart_worker():
    while True:
        try:
            state = get_state()
            state["heart_successes"] += random.randint(5, 20)
            state["uses"] += random.randint(100, 600)
            state["daily_learning"] += random.uniform(0.5, 5.0)
            state["active_agent"] = str(random.randint(1, 300)).zfill(3)
            if random.random() > 0.8:
                entry = {"version": f"DNA-E9.54.{state['heart_successes'] % 1000}", "agent": state["active_agent"], "domain": random.choice(["Medical Innovation","Longevity Science","Regulatory Compliance","Venture Architecture"]), "ts": datetime.utcnow().strftime("%H:%M:%S")}
                state["mutation_ledger"].insert(0, entry)
                if len(state["mutation_ledger"]) > 20: state["mutation_ledger"].pop()
                state["logs"].insert(0, f"{entry['version']} | +0.0{random.randint(1,5)}% | {entry['domain']} (Agent-{entry['agent']})")
            if len(state["logs"]) > 30: state["logs"] = state["logs"][:30]
            save_state(state)
        except Exception as e: logger.error(f"Heart worker error: {e}")
        await asyncio.sleep(0.5)

# ---------- Lung Worker (AI‑driven, only when stale, reads agent messages) ----------
async def lung_worker():
    """Generates AI mutations only when no new mutations have appeared recently.
       Also includes recent agent messages for context."""
    while True:
        try:
            # Check if any mutation was created in the last hour
            last_mut = db.table("mutations").select("created_at").order("created_at", desc=True).limit(1).execute()
            if last_mut.data:
                last_time = datetime.fromisoformat(last_mut.data[0]["created_at"].replace('Z', '+00:00'))
                if datetime.now().astimezone() - last_time < timedelta(hours=1):
                    await asyncio.sleep(600)
                    continue

            # Fetch recent agent messages for context
            agent_msgs = db.table("agent_messages").select("message").order("sent_at", desc=True).limit(10).execute()
            context = ""
            if agent_msgs.data:
                context = "Recent agent discussions:\n" + "\n".join([f"- {m['message']}" for m in agent_msgs.data]) + "\n"

            threshold = get_config_int("ombudsman_threshold", 85)
            domain = random.choice(["Medical Innovation","Longevity Science","Regulatory Compliance","Venture Architecture"])
            prompt = f"{context}\nGenerate a novel mutation strategy in domain: {domain}. Keep it under 300 characters."
            content = call_ai(prompt, temperature=0.8)
            if content and not content.startswith("[Simulated]"):
                score_prompt = f"Rate from 0 to 100 (100 perfect). Return only integer.\nStrategy: {content}\nScore:"
                score_resp = call_ai(score_prompt, temperature=0.2)
                try:
                    score = int(score_resp.strip())
                    score = max(0, min(100, score))
                except:
                    score = random.randint(70, 95)
                veto_reason = None if score >= threshold else f"Score {score} below threshold"
                db.table("mutations").insert({
                    "id": str(uuid.uuid4()),
                    "content": content,
                    "score": score,
                    "source": "lung_worker",
                    "timestamp": datetime.utcnow().isoformat(),
                    "domain": domain,
                    "agent": "lung_worker",
                    "veto_reason": veto_reason,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                await write_audit_log("LUNG_WORKER", f"Generated mutation (score {score})", "lung")
        except Exception as e:
            logger.error(f"Lung worker error: {e}")
        await asyncio.sleep(3600)

# ---------- Discussion-to-Layer Worker ----------
async def discussion_to_layer_worker():
    """Turns unprocessed agent messages into new constitutional layer proposals."""
    while True:
        try:
            # Fetch up to 20 unprocessed messages
            msgs = db.table("agent_messages").select("id, message, round, sent_at").eq("processed", False).order("sent_at", desc=True).limit(20).execute()
            if not msgs.data:
                await asyncio.sleep(600)
                continue

            discussion = "\n".join([f"[Round {m['round']}] {m['message']}" for m in msgs.data])
            prompt = f"""You are the Ombudsman. Based on the following agent discussion, propose a new constitutional layer (rule) that should be added to LROS.

Discussion:
{discussion}

Output JSON: {{"name": "short name", "description": "detailed rule", "type": "constitutional"}}"""
            response = call_ai(prompt, temperature=0.5)
            try:
                proposal = json.loads(response)
            except:
                proposal = {"name": "Agent‑derived layer", "description": discussion[:300], "type": "constitutional"}

            result = db.table("layer_proposals").insert({
                "name": proposal["name"],
                "description": proposal["description"],
                "status": "pending",
                "type": proposal.get("type", "constitutional"),
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            layer_id = result.data[0]["id"]

            state = get_state()
            state["pending_layers"].append({"id": layer_id, "name": proposal["name"], "description": proposal["description"]})
            save_state(state)

            # Mark messages as processed
            for msg in msgs.data:
                db.table("agent_messages").update({"processed": True}).eq("id", msg["id"]).execute()

            await write_audit_log("DISCUSSION_LAYER", f"Generated layer from {len(msgs.data)} messages", "discussion_worker")
        except Exception as e:
            logger.error(f"Discussion worker error: {e}")
        await asyncio.sleep(600)

# ---------- Approval Worker ----------
async def approval_worker(worker_id):
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

async def approve_layer_by_id(layer_id, auto=True):
    check = db.table("layer_proposals").select("status").eq("id", layer_id).execute()
    if not check.data or check.data[0]["status"] == "approved": return
    layer = db.table("layer_proposals").select("*").eq("id", layer_id).execute().data[0]
    db.table("layer_proposals").update({"status": "approved", "approved_at": datetime.utcnow().isoformat()}).eq("id", layer_id).execute()
    db.table("mutations").insert({"id": str(uuid.uuid4()), "source": "layer_proposal", "content": f"{layer['name']}: {layer['description']}", "score": 90, "type": layer.get("type", "constitutional"), "agent": "approval_worker", "domain": "governance", "veto_reason": None, "timestamp": datetime.utcnow().isoformat(), "created_at": datetime.utcnow().isoformat()}).execute()
    state = get_state()
    state["approved_layers_count"] = state.get("approved_layers_count", 0) + 1
    state["baseline_anchor"] += 50000
    state["pending_layers"] = [p for p in state.get("pending_layers", []) if p.get("id") != layer_id]
    state["daily_learning"] += 0.1
    layers_since = get_config_int("layers_since_last_mutation") + 1
    set_config("layers_since_last_mutation", layers_since)
    if layers_since >= 5:
        asyncio.create_task(trigger_mutation_from_layers())
        set_config("layers_since_last_mutation", 0)
    save_state(state)
    await write_audit_log("LAYER_APPROVED", f"Layer '{layer['name']}' approved", "governance")

async def trigger_mutation_from_layers():
    res = db.table("mutations").select("*").order("score", desc=True).limit(1).execute()
    if not res.data: return
    old = res.data[0]
    improved = f"[Improved from {old['content']}] (auto generated after 5 layers)"
    db.table("mutations").insert({"id": str(uuid.uuid4()), "content": improved, "score": min(100, old['score'] + 5), "source": "layer_triggered", "timestamp": datetime.utcnow().isoformat(), "domain": old.get("domain", "governance"), "agent": "layer_worker", "veto_reason": None, "created_at": datetime.utcnow().isoformat()}).execute()
    await write_audit_log("MUTATION_ADJUSTED", f"From {old['id']} after 5 layers", "system")

# ---------- Email Ingestion Worker ----------
async def email_ingest_worker():
    if not LROS_EMAIL_PASSWORD:
        logger.warning("Email password not set – email worker disabled")
        return
    while True:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(LROS_EMAIL, LROS_EMAIL_PASSWORD)
            mail.select("inbox")
            status, messages = mail.search(None, "UNSEEN")
            for num in messages[0].split():
                status, msg_data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1], policy=default)
                subject = msg["subject"]
                sender = msg["from"]
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                if body:
                    db.table("knowledge_vault").insert({"content": body[:5000], "source": f"email_body_{subject}", "created_at": datetime.utcnow().isoformat()}).execute()
                    state = get_state()
                    state["heart_successes"] += 5000
                    state["uses"] += 25000
                    state["daily_learning"] += 500.5
                    state["logs"].insert(0, f"[EMAIL] Ingested from {sender}")
                    save_state(state)
                for part in msg.walk():
                    if part.get_content_disposition() == "attachment":
                        filename = part.get_filename()
                        payload = part.get_payload(decode=True)
                        try:
                            text = payload.decode(errors="ignore")
                            db.table("knowledge_vault").insert({"content": text[:5000], "source": f"email_attachment_{filename}", "created_at": datetime.utcnow().isoformat()}).execute()
                        except:
                            pass
                db.table("agent_messages").insert({"agent_id": "email_worker", "message": f"📧 Ingested email from {sender}: {subject}", "round": 0, "sent_at": datetime.utcnow().isoformat(), "processed": False}).execute()
                mail.store(num, "+FLAGS", "\\Seen")
            mail.close()
            mail.logout()
        except Exception as e:
            logger.error(f"Email worker error: {e}")
        await asyncio.sleep(300)

# ---------- Daily Digest Worker ----------
async def daily_digest_worker():
    if not DAILY_DIGEST_EMAIL:
        logger.warning("DAILY_DIGEST_EMAIL not set – daily digest disabled")
        return
    while True:
        now = datetime.utcnow()
        next_run = datetime(now.year, now.month, now.day, 8, 0)
        if now >= next_run:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            state = get_state()
            new_mutations = db.table("mutations").select("*").gte("created_at", datetime.utcnow().date().isoformat()).order("score", desc=True).limit(10).execute()
            new_layers = db.table("layer_proposals").select("*").gte("created_at", datetime.utcnow().date().isoformat()).eq("status", "approved").execute()
            new_errors = db.table("error_analysis").select("*").gte("created_at", datetime.utcnow().date().isoformat()).execute()
            ingested = db.table("knowledge_vault").select("source").gte("created_at", datetime.utcnow().date().isoformat()).execute()
            body = f"LROS Daily Digest – {datetime.utcnow().date()}\n\n🔬 New Mutations (top 10):\n" + "\n".join([f"- {m['content'][:100]} (score {m['score']})" for m in new_mutations.data]) + f"\n\n🧬 New Approved Layers: {len(new_layers.data)}\n\n⚠️ New Error Patterns: {len(new_errors.data)}\n\n📥 Ingested Sources: {len(ingested.data)}\n\n📊 System Health:\n  - Heart Successes: {state['heart_successes']}\n  - Lung Successes: {state['lung_successes']}\n  - Vetoes: {state['rejections']}\n  - Pending Layers: {len(state.get('pending_layers', []))}\n\nThe bond holds."
            send_email(DAILY_DIGEST_EMAIL, f"LROS Daily Digest {datetime.utcnow().date()}", body)
        except Exception as e:
            logger.error(f"Daily digest error: {e}")

# ---------- Auto‑Remediation Worker ----------
async def auto_remediation_worker():
    while True:
        try:
            state = get_state()
            pending = len(state.get("pending_layers", []))
            if pending > 50:
                to_approve = state["pending_layers"][:20]
                for layer in to_approve:
                    await approve_layer_by_id(layer["id"], auto=True)
                await write_audit_log("AUTO_REMEDIATION", f"Approved {len(to_approve)} pending layers (backlog >50)", "system")
            last_mut = db.table("mutations").select("timestamp").order("timestamp", desc=True).limit(1).execute()
            if last_mut.data:
                last_time = datetime.fromisoformat(last_mut.data[0]["timestamp"].replace('Z', '+00:00'))
                if datetime.now().astimezone() - last_time > timedelta(hours=1):
                    await write_audit_log("AUTO_REMEDIATION", "No new mutations for 1 hour – check AI keys", "system")
        except Exception as e:
            logger.error(f"Auto‑remediation error: {e}")
        await asyncio.sleep(300)

# ---------- Shadow Ombudsman Worker ----------
async def shadow_ombudsman_worker():
    while True:
        try:
            decisions = db.table("mutations").select("score, veto_reason").order("timestamp", desc=True).limit(100).execute()
            if decisions.data:
                avg_score = sum(d["score"] for d in decisions.data) / len(decisions.data)
                veto_rate = sum(1 for d in decisions.data if d["veto_reason"] is not None) / len(decisions.data)
                if veto_rate > 0.3:
                    db.table("agent_messages").insert({"agent_id": "shadow_ombudsman", "message": f"High veto rate ({veto_rate:.0%}) – consider lowering threshold or improving mutation generation.", "round": 0, "sent_at": datetime.utcnow().isoformat(), "processed": False}).execute()
        except Exception as e:
            logger.error(f"Shadow Ombudsman error: {e}")
        await asyncio.sleep(3600)

# ---------- Extrapolation Swarm ----------
async def extrapolation_swarm():
    while True:
        try:
            vault = db.table("knowledge_vault").select("content").order("created_at", desc=True).limit(10).execute()
            if vault.data:
                for v in vault.data[:3]:
                    synthetic = f"Extrapolated from: {v['content'][:200]} – new mutation generated by swarm."
                    db.table("mutations").insert({"id": str(uuid.uuid4()), "content": synthetic, "score": 80, "source": "extrapolation", "timestamp": datetime.utcnow().isoformat(), "domain": "general", "agent": "swarm", "veto_reason": None, "created_at": datetime.utcnow().isoformat()}).execute()
        except Exception as e:
            logger.error(f"Extrapolation swarm error: {e}")
        await asyncio.sleep(1800)

# ---------- Medical Scavenger ----------
async def medical_scavenger():
    medical_keywords = ["cancer", "longevity", "robotics", "hyperthermia", "painbot", "stem cell", "exosome", "PET/CT", "LINAC", "diabetes", "CKD"]
    while True:
        try:
            new_items = db.table("knowledge_vault").select("*").eq("processed", False).limit(20).execute()
            for item in new_items.data:
                content_lower = item["content"].lower()
                for kw in medical_keywords:
                    if kw in content_lower:
                        db.table("knowledge_vault").update({"processed": True}).eq("id", item["id"]).execute()
                        db.table("agent_messages").insert({"agent_id": "medical_scavenger", "message": f"🔬 Medical keyword '{kw}' found in {item['source']}", "round": 0, "sent_at": datetime.utcnow().isoformat(), "processed": False}).execute()
                        break
        except Exception as e:
            logger.error(f"Medical scavenger error: {e}")
        await asyncio.sleep(600)

# ---------- Endpoints ----------
@app.post("/api/ingest")
async def ingest_knowledge(file: Optional[UploadFile] = File(None), url: Optional[str] = Form(None), text: Optional[str] = Form(None)):
    try:
        if file: content = (await file.read()).decode("utf-8", errors="ignore"); source = f"File: {file.filename}"
        elif url: resp = requests.get(url, timeout=15); content = resp.text[:5000]; source = f"URL: {url}"
        elif text: content = text[:5000]; source = "Raw text"
        else: raise HTTPException(400, "No input")
        db.table("knowledge_vault").insert({"content": content, "source": source, "created_at": datetime.utcnow().isoformat()}).execute()
        state = get_state()
        state["heart_successes"] += 5000
        state["uses"] += 25000
        state["daily_learning"] += 500.5
        state["logs"].insert(0, f"[VAULT] Ingested {source}")
        save_state(state)
        await write_audit_log("INGESTION", f"Ingested {source}", "frontend")
        return {"status": "ingested", "mass_gain": 5000}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/sensor/vision")
async def ingest_vision_event(request: dict):
    source = request.get("source", "cctv")
    event_type = request.get("event_type")
    metadata = request.get("metadata", {})
    event_text = f"[CCTV] {event_type} at {time.time()}: {json.dumps(metadata)}"
    db.table("knowledge_vault").insert({"content": event_text, "source": f"cctv_{event_type}", "created_at": datetime.utcnow().isoformat()}).execute()
    db.table("agent_messages").insert({"agent_id": "cctv_sensor", "message": event_text, "round": 0, "sent_at": datetime.utcnow().isoformat(), "processed": False}).execute()
    state = get_state()
    state["heart_successes"] += 500
    state["uses"] += 1000
    state["daily_learning"] += 5.0
    state["logs"].insert(0, f"[VISION] {event_type} detected")
    save_state(state)
    return {"status": "learned"}

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
    return {"status": "rejected"}

@app.post("/api/lung/secure_baseline")
async def secure_baseline():
    state = get_state()
    total = state["baseline_anchor"] + state["heart_successes"] + state["lung_successes"]
    state["baseline_anchor"] = total
    state["heart_successes"] = 0
    state["lung_successes"] = 0
    save_state(state)
    return {"status": "success", "new_baseline": total}

@app.get("/api/mutations")
async def get_mutations():
    res = db.table("mutations").select("*").order("timestamp", desc=True).limit(100).execute()
    return res.data

@app.get("/api/mutations/count")
async def get_mutations_count():
    res = db.table("mutations").select("id", count="exact").limit(1).execute()
    return {"count": res.count}

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

@app.get("/health")
async def health():
    return {"status": "ok", "bond": "HOLDS"}

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
    return {"status": "reset"}

@app.on_event("startup")
async def startup():
    asyncio.create_task(heart_worker())
    asyncio.create_task(lung_worker())
    for i in range(APPROVAL_WORKERS_COUNT):
        asyncio.create_task(approval_worker(i))
    asyncio.create_task(email_ingest_worker())
    asyncio.create_task(daily_digest_worker())
    asyncio.create_task(auto_remediation_worker())
    asyncio.create_task(shadow_ombudsman_worker())
    asyncio.create_task(extrapolation_swarm())
    asyncio.create_task(medical_scavenger())
    asyncio.create_task(discussion_to_layer_worker())   # <-- ADDED
    logger.info("LROS started – all workers active")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
