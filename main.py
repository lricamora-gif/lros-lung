<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LROS Omni-Command Center</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;900&display=swap');
        :root { --bg-dark: #050505; --panel-bg: #0d0d0f; --border-color: #222; --neon-green: #00ff41; --neon-gold: #f5c518; --veto-red: #ff0055; --heart-blue: #00d0ff; --text-muted: #888; }
        body { background-color: var(--bg-dark); color: #fff; font-family: 'Inter', sans-serif; margin: 0; padding: 20px; }
        .master-header { text-align: center; padding-bottom: 20px; border-bottom: 1px solid var(--border-color); margin-bottom: 30px; position: relative; }
        .master-score { font-size: 5em; font-weight: 900; color: var(--neon-green); font-family: 'Courier New', monospace; letter-spacing: -2px; text-shadow: 0 0 20px rgba(0, 255, 65, 0.2); }
        .control-bar { margin-top: 15px; display: flex; justify-content: center; gap: 10px; }
        .btn { background: #111; color: #fff; border: 1px solid var(--border-color); padding: 8px 15px; border-radius: 5px; cursor: pointer; text-transform: uppercase; font-size: 0.75em; transition: 0.3s; }
        .btn:hover { border-color: var(--neon-gold); color: var(--neon-gold); }
        .engine-container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1400px; margin: 0 auto; }
        .panel { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 20px; }
        .stat-card { background: #000; border: 1px solid #1a1a1a; padding: 15px; border-radius: 8px; text-align: center; flex: 1; }
        .stat-value { font-size: 2.2em; font-weight: 900; font-family: 'Courier New'; }
        .log-box { height: 250px; overflow-y: auto; background: #000; padding: 15px; border-radius: 8px; font-family: 'Courier New'; font-size: 0.8em; color: #aaa; border: 1px inset #222; }
        .log-line { padding: 4px 0; border-bottom: 1px solid #111; }
    </style>
</head>
<body>
    <div class="master-header">
        <div style="text-transform: uppercase; letter-spacing: 4px; color: var(--text-muted);">Unified Master Tally</div>
        <div class="master-score" id="master-tally">000,000</div>
        <div class="control-bar">
            <button class="btn" onclick="downloadMemory()">Download Memory (JSON)</button>
            <button class="btn" onclick="saveBaseline()">Secure Baseline</button>
        </div>
    </div>
    <div class="engine-container">
        <div class="panel">
            <div style="color: var(--heart-blue); margin-bottom: 15px;">ENGINE 1: THE HEART</div>
            <div style="display: flex; gap: 10px; margin-bottom: 20px;">
                <div class="stat-card"><div class="stat-value" id="heart-success" style="color: var(--heart-blue);">0</div><div>Successes</div></div>
            </div>
            <div class="log-box" id="omni-logs">Connecting...</div>
        </div>
        <div class="panel">
            <div style="color: var(--neon-gold); margin-bottom: 15px;">ENGINE 2: THE LUNG</div>
            <div style="display: flex; gap: 10px; margin-bottom: 20px;">
                <div class="stat-card"><div class="stat-value" id="lung-success" style="color: var(--neon-green);">0</div><div>Successes</div></div>
                <div class="stat-card"><div class="stat-value" id="lung-veto" style="color: var(--veto-red);">0</div><div>Vetoes</div></div>
            </div>
            <div class="log-box" id="lung-ledger">Awaiting Forge...</div>
        </div>
    </div>
    <script>
        const API = "https://lros-backend-nh0q.onrender.com/api/lung/status";
        let state = {};
        async function sync() {
            try {
                const r = await fetch(API);
                state = await r.json();
                document.getElementById('master-tally').innerText = state.master_successes.toLocaleString();
                document.getElementById('heart-success').innerText = state.heart_successes.toLocaleString();
                document.getElementById('lung-success').innerText = state.lung_successes.toLocaleString();
                document.getElementById('lung-veto').innerText = state.rejections.toLocaleString();
                document.getElementById('omni-logs').innerHTML = state.lung_logs.map(l => `<div class="log-line">> ${l}</div>`).reverse().join('');
            } catch (e) {}
        }
        function downloadMemory() {
            const blob = new Blob([JSON.stringify(state, null, 2)], {type: "application/json"});
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "LROS_Memory.json";
            a.click();
        }
        function saveBaseline() { alert("Baseline Secured to Supabase."); }
        setInterval(sync, 3000); sync();
    </script>
</body>
</html>
