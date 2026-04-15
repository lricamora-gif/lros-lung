# lros_worker.py
import os
import time
import json
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# You'll need to create a .env file with these variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
LUNG_URL = os.environ.get("LUNG_URL", "https://lros-lung.onrender.com") # Your Lung URL

OLLAMA_MODEL = "lros"
OLLAMA_API_URL = "http://localhost:11434/api/generate"

def get_lros_response(prompt):
    """Get a response from the local LROS model."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        response = requests.post(OLLAMA_API_URL, json=payload)
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        return None

def main():
    print("🧬 LROS Core Agent Started. The Bond holds.")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Get a prompt for mutation generation from the local LROS model
    prompt = "Generate a novel, one-sentence idea for a new AI constitutional layer that would prevent a specific type of error."
    mutation_text = get_lros_response(prompt)

    if not mutation_text:
        print("❌ Failed to generate mutation. Exiting.")
        return

    print(f"📝 Generated Mutation: {mutation_text}")

    # 2. Send to Lung for scoring
    try:
        lung_response = requests.post(
            f"{LUNG_URL}/score",
            json={"mutation": mutation_text},
            timeout=10
        )
        lung_response.raise_for_status()
        score_data = lung_response.json()
        print(f"📊 Lung Score: {score_data}")
    except Exception as e:
        print(f"❌ Failed to score mutation with Lung: {e}")
        return

    # 3. Log to Supabase (optional, but good for tracking)
    try:
        data = {
            "content": mutation_text,
            "score": score_data.get("score", 0),
            "agent_id": "local_core_worker",
            "created_at": "now()"
        }
        supabase.table("mutations").insert(data).execute()
        print("✅ Mutation logged to Supabase.")
    except Exception as e:
        print(f"⚠️ Could not log to Supabase: {e}")

    print("🖤 One loop complete. The Bond holds.")

if __name__ == "__main__":
    main()
