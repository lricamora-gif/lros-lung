import os
import asyncio
import logging
from datetime import datetime
from supabase import create_client
from dotenv import load_dotenv
import httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lros-scheduler")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise Exception("Missing Supabase credentials")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

HEART_URL = os.getenv("HEART_URL", "http://localhost:8000")
WORKER_ID = os.getenv("SCHEDULER_WORKER_ID", "scheduler-1")
MAX_CONCURRENT = int(os.getenv("SCHEDULER_CONCURRENT", "5"))
SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP", "5"))

semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def call_tool(tool: dict, payload: dict) -> dict:
    url = f"{HEART_URL}{tool['endpoint']}"
    method = tool['method'].upper()
    async with httpx.AsyncClient(timeout=60) as client:
        if method == 'POST':
            resp = await client.post(url, json=payload)
        elif method == 'GET':
            resp = await client.get(url, params=payload)
        else:
            raise ValueError(f"Unsupported method {method}")
        resp.raise_for_status()
        return resp.json()

async def execute_task(task):
    async with semaphore:
        try:
            tool_res = supabase.table("tools").select("*").eq("name", task["tool_name"]).execute()
            if not tool_res.data:
                raise Exception(f"Tool {task['tool_name']} not found")
            tool = tool_res.data[0]
            logger.info(f"Scheduler {WORKER_ID} executing task {task['id']} with tool {tool['name']}")
            result = await call_tool(tool, task["payload"])
            supabase.table("tasks").update({
                "status": "succeeded",
                "completed_at": datetime.utcnow().isoformat(),
                "worker_id": WORKER_ID,
                "error": None
            }).eq("id", task["id"]).execute()
            return result
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}")
            new_retries = task.get("retries", 0) + 1
            max_retries = task.get("max_retries", 3)
            if new_retries >= max_retries:
                supabase.table("tasks").update({
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.utcnow().isoformat(),
                    "worker_id": WORKER_ID,
                    "retries": new_retries
                }).eq("id", task["id"]).execute()
            else:
                supabase.table("tasks").update({
                    "status": "pending",
                    "retries": new_retries,
                    "error": str(e)
                }).eq("id", task["id"]).execute()
            raise

async def main_loop():
    while True:
        try:
            tasks = supabase.table("tasks").select("*").eq("status", "pending").execute()
            if tasks.data:
                executable = []
                for t in tasks.data:
                    deps = t.get("depends_on", [])
                    if not deps:
                        executable.append(t)
                    else:
                        dep_statuses = supabase.table("tasks").select("status").in_("id", deps).execute()
                        if all(s["status"] == "succeeded" for s in dep_statuses.data):
                            executable.append(t)
                await asyncio.gather(*[execute_task(t) for t in executable])
            else:
                await asyncio.sleep(SLEEP_SECONDS)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    asyncio.run(main_loop())
