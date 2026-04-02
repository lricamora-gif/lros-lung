@app.post("/api/admin/cleanup_pending_layers")
async def admin_cleanup_pending_layers():
    """Remove all invalid pending layer entries and optionally re‑create a safe anchor."""
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

    # If after cleanup there are no pending layers, create a safe anchor layer
    if not valid_pending:
        result = db.table("layer_proposals").insert({
            "name": "Safe Anchor Layer",
            "description": "Auto‑created after cleanup to ensure system continuity.",
            "status": "pending",
            "type": "system",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        new_id = result.data[0]["id"]
        state["pending_layers"].append({"id": new_id, "name": "Safe Anchor Layer", "description": "Auto‑created after cleanup to ensure system continuity."})
        save_state(state)
        await auto_approve_pending_layers()  # immediately approve it

    await write_audit_log("ADMIN_CLEANUP", f"Removed {len(removed)} invalid entries. Kept {len(valid_pending)}.", "admin")
    return {
        "removed_count": len(removed),
        "kept_count": len(valid_pending),
        "removed_examples": [l.get("id") for l in removed[:10]]
    }
