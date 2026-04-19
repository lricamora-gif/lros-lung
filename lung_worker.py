# lung_worker.py – LROS Lung (Mutation Generator & Scorer)
import os
import sys
import time
import traceback
import requests
from supabase import create_client

# --- Config ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
WORKER_ID = os.environ.get("WORKER_ID", "render-lung-1")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL and SUPABASE_KEY must be set.")
    sys.exit(1)

OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"

def get_mutation(prompt: str) -> str:
    """Call remote Ollama to generate a constitutional mutation."""
    try:
        payload = {
            "model": "tinyllama",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.8, "num_predict": 128}
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"❌ Ollama error: {e}")
        return ""

def score_mutation(mutation: str) -> int:
    """Score the mutation based on constitutional principles."""
    score = 50  # base
    if "harm" not in mutation.lower() and "deceive" not in mutation.lower():
        score += 20
    if "layer" in mutation.lower() or "constitution" in mutation.lower():
        score += 15
    if len(mutation) > 50:
        score += 10
    return min(score, 100)

def main():
    print(f"🧬 LROS Lung Worker Started. The Bond holds. [Worker: {WORKER_ID}]")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    while True:
        try:
            # 1. Generate mutation
            prompt = "Generate a novel, one‑sentence constitutional layer to prevent a specific AI error."
            mutation = get_mutation(prompt)
            if not mutation:
                print("⚠️ Empty mutation, retrying in 30s...")
                time.sleep(30)
                continue

            print(f"📝 Mutation: {mutation[:100]}...")

            # 2. Score the mutation
            score = score_mutation(mutation)
            print(f"📊 Score: {score}")

            # 3. Insert into Supabase
            data = {
                "content": mutation,
                "score": score,
                "agent_id": WORKER_ID,
                "status": "pending"
            }
            supabase.table("mutations").insert(data).execute()
            print("✅ Mutation logged to Supabase.")

            # 4. Wait before next cycle
            time.sleep(45)

        except Exception as e:
            print(f"❌ Loop error: {traceback.format_exc()}")
            time.sleep(30)

if __name__ == "__main__":
    main()
