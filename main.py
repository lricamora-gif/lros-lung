<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LROS · Half‑Agent Mode · Local First</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0A0C12; font-family: 'Inter', sans-serif; color: #E6EDFF; padding: 2rem; }
        .container { max-width: 1400px; margin: 0 auto; }
        .master-header { text-align: center; border-bottom: 1px solid #202433; padding-bottom: 25px; margin-bottom: 25px; }
        .master-score { font-size: 5rem; font-weight: 900; font-family: 'JetBrains Mono', monospace; color: #00ff41; text-shadow: 0 0 20px rgba(0,255,65,0.3); letter-spacing: -2px; }
        .control-panel { background: #0E1119; border: 1px solid #262C3C; border-radius: 16px; padding: 15px 20px; display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin: 20px 0; }
        .btn { background: #111; border: 1px solid #2A3042; color: #fff; padding: 8px 16px; border-radius: 40px; font-size: 0.75rem; cursor: pointer; transition: 0.2s; }
        .btn-primary { border-color: #00ff41; color: #00ff41; }
        .btn-primary:hover { background: #00ff41; color: #000; }
        .btn-secondary { border-color: #5e6ad2; color: #5e6ad2; }
        .engine-container { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin-bottom: 25px; }
        .panel { background: #0E1119; border: 1px solid #262C3C; border-radius: 20px; overflow: hidden; display: flex; flex-direction: column; height: 550px; }
        .panel-header { background: #121624; padding: 12px 20px; border-bottom: 1px solid #262C3C; font-weight: bold; }
        .panel-content { padding: 20px; flex-grow: 1; overflow-y: auto; }
        .metric-card { background: #0C0F16; border-radius: 12px; padding: 10px; text-align: center; border: 1px solid #262C3C; margin-bottom: 10px; }
        .metric-card .value { font-size: 1.5rem; font-weight: bold; font-family: monospace; }
        .log-box { background: #050608; border-radius: 12px; padding: 12px; font-size: 0.75rem; height: 300px; overflow-y: auto; }
        .pending-item { background: #121624; border: 1px solid #262C3C; border-radius: 8px; padding: 10px; margin-bottom: 8px; }
        .dropzone { border: 2px dashed #5e6ad2; border-radius: 12px; padding: 15px; text-align: center; cursor: pointer; margin-bottom: 15px; }
        .text-input { background:#0C0F16; border:1px solid #2A3042; border-radius:8px; padding:8px; color:#fff; width: 100%; margin-bottom: 8px; }
        .status { background: #0E1119; border-radius: 20px; padding: 4px 12px; display: inline-block; font-size: 0.7rem; }
    </style>
</head>
<body>
<div class="container">
    <div class="master-header">
        <div>LROS · HALF‑AGENT MODE</div>
        <div class="master-score" id="masterTally">0</div>
        <div>Baseline: <span id="baselineVal">0</span> &nbsp;|&nbsp; 
            <span id="syncStatus" class="status">📍 Local only</span>
        </div>
        <div class="control-panel">
            <button class="btn btn-primary" id="secureBtn">🔒 Secure Baseline</button>
            <button class="btn btn-secondary" id="downloadBtn">💾 Download JSON</button>
            <button class="btn" id="resetBtn">🗑️ Hard Reset</button>
            <button class="btn" id="refreshBtn">🔄 Refresh</button>
        </div>
        <div class="control-panel">
            <span>Ombudsman Threshold: </span>
            <input type="range" id="thresholdSlider" min="50" max="99" value="85" style="width: 120px;">
            <span id="thresholdVal">85%</span>
            <button id="applyThresholdBtn" class="btn btn-secondary">Apply</button>
        </div>
    </div>

    <div class="engine-container">
        <div class="panel">
            <div class="panel-header">❤️ ENGINE 1: HEART</div>
            <div class="panel-content">
                <div class="metric-card">❤️ Heart Successes: <span class="value" id="heartTotal">0</span></div>
                <div class="metric-card">📊 Uses: <span id="uses">0</span> &nbsp;|&nbsp; 📈 Daily Yield: <span id="dailyYield">0</span>%</div>
                <div class="log-box" id="heartLogs"></div>
            </div>
        </div>
        <div class="panel">
            <div class="panel-header">🫁 ENGINE 2: LUNG</div>
            <div class="panel-content">
                <div class="metric-card">🫁 Lung Successes: <span class="value" id="lungTotal">0</span></div>
                <div class="metric-card">❌ Vetoes: <span id="vetoes">0</span> &nbsp;|&nbsp; ✅ Approved Layers: <span id="approvedCount">0</span></div>
                <div class="log-box" id="lungLogs"></div>
            </div>
        </div>
    </div>

    <div class="engine-container">
        <div class="panel">
            <div class="panel-header">📚 KNOWLEDGE DEPOSITORY</div>
            <div class="panel-content">
                <div id="dropzone" class="dropzone">📁 Drag file or click to upload</div>
                <input type="file" id="fileInput" style="display:none">
                <input type="text" id="urlInput" class="text-input" placeholder="Paste URL...">
                <button id="ingestUrlBtn" class="btn btn-secondary">Ingest URL</button>
                <textarea id="textInput" class="text-input" rows="2" placeholder="Paste text..."></textarea>
                <button id="ingestTextBtn" class="btn btn-secondary">Ingest Text</button>
                <div class="log-box" id="vaultList" style="height: 150px;"></div>
            </div>
        </div>
        <div class="panel">
            <div class="panel-header">⚖️ GOVERNANCE (Pending Layers)</div>
            <div class="panel-content" id="governanceBox"></div>
        </div>
    </div>
</div>

<script>
    // =================================================================
    // LOCAL FIRST – no backend required for core functionality
    // =================================================================
    const STORAGE_KEY = "LROS_HalfAgent_v1";
    let state = {
        baseline: 1000000,
        heart_successes: 0,
        lung_successes: 0,
        uses: 0,
        rejections: 0,
        daily_learning: 0,
        active_agent: "000",
        approved_layers_count: 0,
        pending_layers: [],
        knowledge_vault: [],
        mutation_ledger: [],
        logs: []
    };

    function loadState() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                Object.assign(state, parsed);
            } catch(e) {}
        }
        updateUI();
    }
    function saveState() { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }

    let threshold = parseInt(localStorage.getItem("ombudsman_threshold") || "85");
    document.getElementById("thresholdSlider").value = threshold;
    document.getElementById("thresholdVal").innerText = threshold + "%";

    // UI elements
    const elMaster = document.getElementById("masterTally");
    const elBaseline = document.getElementById("baselineVal");
    const elHeart = document.getElementById("heartTotal");
    const elUses = document.getElementById("uses");
    const elDailyYield = document.getElementById("dailyYield");
    const elLung = document.getElementById("lungTotal");
    const elVetoes = document.getElementById("vetoes");
    const elApproved = document.getElementById("approvedCount");
    const heartLogs = document.getElementById("heartLogs");
    const lungLogs = document.getElementById("lungLogs");
    const vaultList = document.getElementById("vaultList");
    const governanceBox = document.getElementById("governanceBox");

    function updateUI() {
        const total = state.baseline + state.heart_successes + state.lung_successes;
        elMaster.innerText = total.toLocaleString();
        elBaseline.innerText = state.baseline.toLocaleString();
        elHeart.innerText = state.heart_successes.toLocaleString();
        elUses.innerText = (state.uses / 1e6).toFixed(1) + "M";
        elDailyYield.innerText = state.daily_learning.toFixed(2);
        elLung.innerText = state.lung_successes.toLocaleString();
        elVetoes.innerText = state.rejections.toLocaleString();
        elApproved.innerText = state.approved_layers_count.toLocaleString();

        heartLogs.innerHTML = state.mutation_ledger.slice(0, 15).map(e => 
            `<div>[${e.ts || "??"}] ${e.version || "DNA"} | ${e.domain || ""} (Agent-${e.agent || "?"})</div>`
        ).join('');

        lungLogs.innerHTML = state.logs.slice(0, 15).map(l => `<div>${l}</div>`).join('');

        vaultList.innerHTML = state.knowledge_vault.slice(-10).reverse().map(v => 
            `<div>📄 ${v.type}: ${v.content.substring(0, 80)}</div>`
        ).join('');

        if (state.pending_layers.length === 0) {
            governanceBox.innerHTML = "<div>No pending layers.</div>";
        } else {
            governanceBox.innerHTML = state.pending_layers.map(layer => `
                <div class="pending-item">
                    <strong>${escapeHtml(layer.name)}</strong><br>
                    <small>${escapeHtml(layer.description)}</small><br>
                    <button class="btn btn-primary" onclick="approveLayer('${layer.id}')">Approve</button>
                    <button class="btn btn-danger" onclick="rejectLayer('${layer.id}')">Reject</button>
                </div>
            `).join('');
        }
        saveState();
    }

    function escapeHtml(str) { return str.replace(/[&<>]/g, m => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;' }[m])); }

    window.approveLayer = (id) => {
        const layer = state.pending_layers.find(l => l.id === id);
        if (layer) {
            state.pending_layers = state.pending_layers.filter(l => l.id !== id);
            state.baseline += 50000;
            state.approved_layers_count++;
            state.daily_learning += 0.1;
            state.logs.unshift(`✅ Approved: ${layer.name} – +50,000 baseline, +0.1% learning`);
            if (state.logs.length > 30) state.logs.pop();
            updateUI();
        }
    };
    window.rejectLayer = (id) => {
        state.pending_layers = state.pending_layers.filter(l => l.id !== id);
        updateUI();
    };

    function addMutation(content, score, source) {
        const isVeto = score < threshold;
        if (isVeto) {
            state.rejections++;
            state.logs.unshift(`❌ VETO: ${source} scored ${score} < ${threshold}`);
        } else {
            state.lung_successes++;
            state.logs.unshift(`✅ EVOLVE: ${source} accepted (${score})`);
            // Occasionally create a pending layer
            if (Math.random() > 0.85 && state.pending_layers.length < 5) {
                const newLayer = {
                    id: "lyr_" + Date.now(),
                    name: "Auto‑generated improvement",
                    description: `Optimization from ${source} mutation. Score: ${score}`,
                    created: new Date().toISOString()
                };
                state.pending_layers.push(newLayer);
                state.logs.unshift(`📋 New pending layer: ${newLayer.name}`);
            }
        }
        updateUI();
    }

    // Simulate heart worker (runs locally)
    function startHeartWorker() {
        setInterval(() => {
            state.heart_successes += Math.floor(Math.random() * 15) + 5;
            state.uses += Math.floor(Math.random() * 500) + 100;
            state.daily_learning += Math.random() * 2;
            state.active_agent = Math.floor(Math.random() * 300).toString().padStart(3, '0');
            if (Math.random() > 0.8) {
                const domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"];
                const domain = domains[Math.floor(Math.random() * domains.length)];
                const entry = {
                    version: `DNA-E9.54.${state.heart_successes % 1000}`,
                    agent: state.active_agent,
                    domain: domain,
                    ts: new Date().toLocaleTimeString()
                };
                state.mutation_ledger.unshift(entry);
                if (state.mutation_ledger.length > 20) state.mutation_ledger.pop();
            }
            updateUI();
        }, 800);
    }

    // Simulate lung worker (runs locally)
    function startLungWorker() {
        setInterval(() => {
            const models = ["deepseek", "mistral", "groq", "gemini", "cerebras"];
            const domains = ["Medical Innovation", "Longevity Science", "Regulatory Compliance", "Venture Architecture"];
            const source = models[Math.floor(Math.random() * models.length)];
            const domain = domains[Math.floor(Math.random() * domains.length)];
            const score = Math.floor(Math.random() * 51) + 50; // 50-100
            const content = `Optimization for ${domain} using ${source}. Efficiency +${Math.floor(Math.random()*30)+5}%.`;
            addMutation(content, score, source);
        }, 2500);
    }

    // Secure baseline
    document.getElementById("secureBtn").onclick = () => {
        if (confirm("Lock current total into baseline?")) {
            const total = state.baseline + state.heart_successes + state.lung_successes;
            state.baseline = total;
            state.heart_successes = 0;
            state.lung_successes = 0;
            updateUI();
        }
    };
    document.getElementById("resetBtn").onclick = () => {
        if (confirm("Hard reset? All progress lost.")) {
            localStorage.removeItem(STORAGE_KEY);
            location.reload();
        }
    };
    document.getElementById("downloadBtn").onclick = () => {
        const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `LROS_State_${Date.now()}.json`;
        a.click();
    };
    document.getElementById("refreshBtn").onclick = () => updateUI();

    // Threshold apply
    document.getElementById("applyThresholdBtn").onclick = () => {
        threshold = parseInt(document.getElementById("thresholdSlider").value);
        document.getElementById("thresholdVal").innerText = threshold + "%";
        localStorage.setItem("ombudsman_threshold", threshold);
        alert(`Threshold set to ${threshold}%. New mutations will use this.`);
    };

    // Ingestion (local only)
    function ingest(type, content) {
        state.knowledge_vault.unshift({ type, content, ts: new Date().toISOString() });
        state.heart_successes += 5000;
        state.uses += 25000;
        state.daily_learning += 500;
        state.logs.unshift(`📥 Ingested ${type}: ${content.substring(0, 50)}`);
        updateUI();
    }
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    dropzone.onclick = () => fileInput.click();
    fileInput.onchange = (e) => {
        if (e.target.files[0]) ingest("File", e.target.files[0].name);
        fileInput.value = '';
    };
    document.getElementById('ingestUrlBtn').onclick = () => {
        const url = document.getElementById('urlInput').value.trim();
        if (url) ingest("URL", url);
        document.getElementById('urlInput').value = '';
    };
    document.getElementById('ingestTextBtn').onclick = () => {
        const txt = document.getElementById('textInput').value.trim();
        if (txt) ingest("Text", txt);
        document.getElementById('textInput').value = '';
    };

    // Boot
    loadState();
    startHeartWorker();
    startLungWorker();
</script>
</body>
</html>
