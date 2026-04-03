#!/usr/bin/env python3
"""
MiBox4 Remote - Flask + androidtvremote2
Install: pip install flask androidtvremote2
Run:     python mibox_remote.py
Open:    http://localhost:5000
"""

import asyncio
import threading
import os
import json
import socket
import ipaddress
from flask import Flask, jsonify, request

app = Flask(__name__)

# State
_remote = None
_loop = None
_pairing_instance = None
_connected_ip = None
_connected_name = None
_pairing_lock = threading.Lock()

CERT_DIR = "."
PORT = 6466
CONFIG_FILE = "config.json"

def cert_path(ip): return os.path.join(CERT_DIR, f"cert_{ip.replace('.','_')}.pem")
def key_path(ip):  return os.path.join(CERT_DIR, f"key_{ip.replace('.','_')}.pem")
def has_certs(ip): return os.path.exists(cert_path(ip)) and os.path.exists(key_path(ip))

def load_config():
    global _connected_ip, _connected_name
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                _connected_ip = data.get("last_ip")
                _connected_name = data.get("last_name")
        except: pass

def save_config(ip, name):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"last_ip": ip, "last_name": name}, f)
    except: pass

def get_loop():
    global _loop
    if _loop is None or not _loop.is_running():
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop

def run_async(coro, timeout=15):
    return asyncio.run_coroutine_threadsafe(coro, get_loop()).result(timeout=timeout)

# ── Remote connection ────────────────────────────────────────────────────────

async def _get_remote():
    global _remote, _connected_ip
    from androidtvremote2 import AndroidTVRemote
    if _remote is None and _connected_ip:
        _remote = AndroidTVRemote("MiBoxRemote", cert_path(_connected_ip), key_path(_connected_ip), _connected_ip)
        await _remote.async_generate_cert_if_missing()
        await _remote.async_connect()
    return _remote

async def _reconnect():
    global _remote
    _remote = None
    return await _get_remote()

async def _start_pairing(ip):
    global _pairing_instance
    from androidtvremote2 import AndroidTVRemote
    for f in [cert_path(ip), key_path(ip)]:
        if os.path.exists(f): os.remove(f)
    _pairing_instance = AndroidTVRemote("MiBoxRemote", cert_path(ip), key_path(ip), ip)
    await _pairing_instance.async_generate_cert_if_missing()
    await _pairing_instance.async_start_pairing()

async def _finish_pairing(code):
    global _remote, _pairing_instance
    if _pairing_instance is None:
        raise Exception("Start pairing first")
    await _pairing_instance.async_finish_pairing(code)
    _remote = None
    _pairing_instance = None

async def _send(keycode):
    global _remote
    try:
        r = await _get_remote()
        r.send_key_command(keycode)
    except Exception:
        _remote = None
        r = await _get_remote()

# ── Network scanning ─────────────────────────────────────────────────────────

def check_ip(ip):
    try:
        # 1. Fast port check
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex((ip, PORT))
        s.close()
        if result != 0: return None
        
        # 2. Resolve name via Cast API
        import urllib.request
        with urllib.request.urlopen(f"http://{ip}:8008/setup/eureka_info", timeout=1.2) as r:
            data = json.loads(r.read())
            return data.get("name", "Android TV")
    except:
        return "Android TV"

def mdns_scan(timeout=5):
    """Fast scan: check first 30 IPs on local subnet in parallel - no extra libs."""
    import concurrent.futures
    results = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        base = ".".join(local_ip.split(".")[:3])
        ips = [f"{base}.{i}" for i in range(1, 41)]
    except:
        ips = [f"192.168.1.{i}" for i in range(1, 41)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_ip, ip): ip for ip in ips}
        for f in concurrent.futures.as_completed(futures):
            ip = futures[f]
            name = f.result()
            if name:
                results.append({"name": name, "ip": ip})
    return results

def deep_scan(progress_callback=None):
    """Scan full subnet concurrently, 10 IPs at a time."""
    import concurrent.futures
    results = []
    try:
        # Get local subnet
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        network = ipaddress.IPv4Network(local_ip + '/24', strict=False)
        ips = [str(h) for h in network.hosts()]
    except:
        ips = [f"192.168.1.{i}" for i in range(1, 255)]

    batch_size = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for i in range(0, len(ips), batch_size):
            batch = ips[i:i+batch_size]
            futures = {ex.submit(check_ip, ip): ip for ip in batch}
            for f in concurrent.futures.as_completed(futures):
                ip = futures[f]
                name = f.result()
                if name:
                    results.append({"name": name, "ip": ip})
                    if progress_callback: progress_callback(name)
    return results

# ── Flask routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index(): return HTML

@app.route("/state", methods=["GET"])
def state():
    return jsonify({
        "connected": _connected_ip is not None,
        "ip": _connected_ip,
        "name": _connected_name or "Unknown"
    })

@app.route("/scan/fast", methods=["POST"])
def scan_fast():
    results = mdns_scan(timeout=5)
    return jsonify({"ok": True, "results": results, "found": len(results) > 0})

@app.route("/scan/deep", methods=["POST"])
def scan_deep():
    results = deep_scan()
    return jsonify({"ok": True, "results": results})

@app.route("/connect", methods=["POST"])
def connect():
    global _connected_ip, _connected_name, _remote
    data = request.get_json()
    ip = data.get("ip", "").strip()
    name = data.get("name", ip)
    if not ip:
        return jsonify({"ok": False, "error": "No IP provided"})
    
    _connected_ip = ip
    _connected_name = name
    save_config(ip, name)
    
    if has_certs(ip):
        try:
            _remote = None
            run_async(_get_remote())
            return jsonify({"ok": True, "paired": True, "name": name})
        except Exception as e:
            # We keep the IP saved even if connection fails
            return jsonify({"ok": False, "error": str(e)})
    else:
        # Need pairing
        try:
            run_async(_start_pairing(ip))
            return jsonify({"ok": True, "paired": False, "needs_pairing": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

@app.route("/finish_pair", methods=["POST"])
def finish_pair():
    global _remote, _connected_ip, _connected_name
    code = request.get_json().get("code", "").strip()
    try:
        run_async(_finish_pairing(code))
        run_async(_get_remote())
        save_config(_connected_ip, _connected_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/reconnect", methods=["POST"])
def reconnect():
    global _connected_ip, _connected_name
    if not _connected_ip:
        load_config()
    if not _connected_ip:
        return jsonify({"ok": False, "error": "No TV selected"})
    try:
        run_async(_reconnect())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/disconnect", methods=["POST"])
def disconnect():
    global _remote, _connected_ip, _connected_name
    _remote = None
    _connected_ip = None
    _connected_name = None
    if os.path.exists(CONFIG_FILE):
        try: os.remove(CONFIG_FILE)
        except: pass
    return jsonify({"ok": True})

@app.route("/ping", methods=["POST"])
def ping():
    if not _connected_ip:
        return jsonify({"ok": False, "error": "No TV selected"})
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{_connected_ip}:8008/setup/eureka_info", timeout=3) as r:
            data = json.loads(r.read())
        return jsonify({"ok": True, "device": data.get("name", _connected_name or "TV")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

KEYS = {
    "up":"DPAD_UP","down":"DPAD_DOWN","left":"DPAD_LEFT","right":"DPAD_RIGHT",
    "select":"DPAD_CENTER","back":"BACK","home":"HOME","power":"POWER",
    "vol_up":"VOLUME_UP","vol_dn":"VOLUME_DOWN","mute":"VOLUME_MUTE",
}

@app.route("/key", methods=["POST"])
def key():
    k = request.get_json().get("key", "")
    keycode = KEYS.get(k)
    if not keycode: return jsonify({"ok": False, "error": "unknown key"})
    if not _connected_ip: return jsonify({"ok": False, "error": "not connected"})
    if not has_certs(_connected_ip): return jsonify({"ok": False, "error": "not paired"})
    try:
        run_async(_send(keycode))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ── HTML ─────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>TV Remote</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
:root{
  --bg:#080c10;--panel:#0d1520;--border:#1a3a5c;
  --accent:#00d4ff;--red:#ff4444;--green:#00e676;
  --btn:#0f2035;--bact:#00d4ff22;--text:#c8e6ff;--dim:#4a7a9b;
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:'Share Tech Mono',monospace;
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
  padding:24px 16px 32px;gap:28px;overflow-x:hidden}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,212,255,.012) 2px,rgba(0,212,255,.012) 4px)}

/* TOP BAR */
.topbar{display:flex;align-items:center;justify-content:space-between;width:100%;max-width:360px;position:relative;z-index:1}

/* Power button */
.power-btn{width:46px;height:46px;border-radius:50%;background:var(--btn);
  border:2px solid #ff444466;display:flex;align-items:center;justify-content:center;
  cursor:pointer;font-size:1.3rem;transition:all .15s;box-shadow:0 0 12px #ff444422;flex-shrink:0}
.power-btn:active{transform:scale(.88);border-color:var(--red);box-shadow:0 0 20px #ff444455}

/* Pair capsule */
.pair-capsule{background:var(--green);color:#000;font-family:'Share Tech Mono',monospace;
  font-size:.7rem;font-weight:700;letter-spacing:1px;padding:8px 18px;border-radius:999px;
  border:none;cursor:pointer;transition:all .2s;max-width:160px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;position:relative}
.pair-capsule.connected{background:var(--accent);color:#000}
.pair-capsule:active{transform:scale(.93)}

/* Reconnect button */
.reconnect-btn{width:46px;height:46px;border-radius:50%;background:var(--btn);
  border:1px solid var(--border);display:flex;align-items:center;justify-content:center;
  cursor:pointer;font-size:1.1rem;transition:all .15s;flex-shrink:0}
.reconnect-btn:active{transform:scale(.88);border-color:var(--accent);background:var(--bact)}

/* DPAD */
.dpad-wrap{position:relative;width:220px;height:220px;z-index:1}
.dpad-circle{width:100%;height:100%;border-radius:50%;background:var(--btn);
  border:2px solid var(--border);position:relative;overflow:hidden;cursor:pointer}

/* Quadrant hit areas */
.quad{position:absolute;width:50%;height:50%;display:flex;align-items:center;justify-content:center;
  font-size:1.1rem;color:var(--dim);transition:all .15s;user-select:none}
.quad:active,.quad.P{background:var(--bact);color:var(--accent)}
.q-up   {top:0;left:0;width:100%;height:50%;clip-path:polygon(0 0,100% 0,50% 100%);padding-bottom:28%}
.q-down {bottom:0;left:0;width:100%;height:50%;clip-path:polygon(0 100%,100% 100%,50% 0);padding-top:28%}
.q-left {top:0;left:0;width:50%;height:100%;clip-path:polygon(0 0,0 100%,100% 50%);padding-right:28%}
.q-right{top:0;right:0;width:50%;height:100%;clip-path:polygon(100% 0,100% 100%,0 50%);padding-left:28%}

/* Diagonal dividers */
.dpad-circle::before,.dpad-circle::after{content:'';position:absolute;
  top:50%;left:50%;width:141%;height:1px;background:#ffffff11;transform-origin:center}
.dpad-circle::before{transform:translate(-50%,-50%) rotate(45deg)}
.dpad-circle::after{transform:translate(-50%,-50%) rotate(-45deg)}

/* OK button */
.ok-btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:68px;height:68px;border-radius:50%;background:#0a2540;
  border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;
  cursor:pointer;font-family:'Orbitron',monospace;font-size:.7rem;font-weight:700;
  color:var(--accent);letter-spacing:1px;z-index:5;
  box-shadow:0 4px 16px #00000066,0 0 12px #00d4ff22;transition:all .15s;user-select:none}
.ok-btn:active,.ok-btn.P{background:var(--bact);box-shadow:0 0 20px #00d4ff44;transform:translate(-50%,-50%) scale(.9)}

/* Bottom capsule */
.bottom-caps{display:flex;width:220px;background:var(--btn);border:1px solid var(--border);
  border-radius:999px;overflow:hidden;z-index:1}
.caps-btn{flex:1;padding:12px 8px;text-align:center;cursor:pointer;font-size:.7rem;
  letter-spacing:1px;transition:all .15s;user-select:none;-webkit-user-select:none}
.caps-btn:active,.caps-btn.P{background:var(--bact);color:var(--accent)}
.caps-divider{width:1px;background:var(--border);flex-shrink:0}

/* LOG */
.log{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:10px 14px;font-size:.62rem;color:var(--dim);height:80px;overflow-y:auto;
  display:flex;flex-direction:column-reverse;gap:2px;width:100%;max-width:360px;z-index:1}
.log .e{color:var(--text)}.log .ok{color:var(--green)}.log .er{color:var(--red)}.log .wa{color:#fa0}

/* MODALS */
.overlay{position:fixed;inset:0;background:#000000aa;z-index:50;display:none;align-items:flex-end;justify-content:center}
.overlay.show{display:flex}
.overlay.center{align-items:center}

/* Bottom sheet */
.sheet{background:var(--panel);border-top:1px solid var(--border);border-radius:20px 20px 0 0;
  width:100%;max-width:500px;max-height:65vh;display:flex;flex-direction:column;
  animation:slideUp .25s ease}
@keyframes slideUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.sheet-header{display:flex;align-items:center;justify-content:space-between;
  padding:16px 20px 10px;border-bottom:1px solid var(--border);flex-shrink:0}
.sheet-title{font-family:'Orbitron',monospace;font-size:.8rem;color:var(--accent);letter-spacing:2px}
.x-btn{background:none;border:1px solid var(--border);color:var(--dim);width:28px;height:28px;
  border-radius:50%;cursor:pointer;font-size:.8rem;display:flex;align-items:center;justify-content:center}
.sheet-body{padding:16px 20px;overflow-y:auto;flex:1}
.scan-status{font-size:.7rem;color:var(--dim);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.spinner{width:10px;height:10px;border-radius:50%;border:2px solid var(--border);
  border-top-color:var(--accent);animation:spin .7s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
.tv-card{background:var(--btn);border:1px solid var(--border);border-radius:8px;
  padding:12px 16px;margin-bottom:8px;cursor:pointer;font-size:.72rem;
  display:flex;justify-content:space-between;align-items:center;transition:all .15s}
.tv-card:active{border-color:var(--accent);background:var(--bact)}
.tv-ip{color:var(--dim);font-size:.62rem}

/* Center modal */
.cmodal{background:var(--panel);border:1px solid var(--border);border-radius:16px;
  padding:24px 20px;width:90%;max-width:320px;animation:popIn .2s ease}
@keyframes popIn{from{transform:scale(.85);opacity:0}to{transform:scale(1);opacity:1}}
.cmodal h3{font-family:'Orbitron',monospace;font-size:.8rem;color:var(--accent);
  letter-spacing:2px;margin-bottom:16px;text-align:center}
.code-input{background:var(--btn);border:1px solid var(--border);color:var(--text);
  font-family:'Share Tech Mono',monospace;font-size:1.1rem;padding:10px;
  border-radius:8px;width:100%;text-align:center;letter-spacing:4px;
  text-transform:uppercase;margin-bottom:12px}
.code-input:focus{outline:none;border-color:var(--accent)}
.confirm-btn{background:var(--accent);color:#000;font-family:'Share Tech Mono',monospace;
  font-size:.75rem;font-weight:700;letter-spacing:1px;padding:10px;
  border-radius:8px;width:100%;border:none;cursor:pointer;transition:all .15s}
.confirm-btn:active{transform:scale(.96)}
.pair-result{text-align:center;font-size:.75rem;margin-top:10px;min-height:20px}
.pair-result.ok{color:var(--green)}.pair-result.er{color:var(--red)}

/* Dropdown from capsule */
.dropdown{position:fixed;background:var(--panel);border:1px solid var(--border);
  border-radius:12px;min-width:150px;z-index:60;overflow:hidden;
  box-shadow:0 8px 32px #000000aa;animation:popIn .15s ease}
.dd-item{padding:14px 20px;font-size:.72rem;cursor:pointer;transition:background .15s;text-align:center}
.dd-item:active{background:var(--bact);color:var(--accent)}
.dd-divider{height:1px;background:var(--border)}

/* VOLUME SECTION */
.vol-row{display:flex;align-items:center;justify-content:center;gap:24px;width:100%;z-index:1}
.v-capsule{width:46px;height:100px;background:var(--btn);border:2px solid var(--border);
  border-radius:23px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 15px rgba(0,0,0,0.3)}
.v-btn{flex:1;display:flex;align-items:center;justify-content:center;font-size:1.1rem;
  cursor:pointer;transition:all .15s;user-select:none;color:var(--dim)}
.v-btn:active,.v-btn.P{background:var(--bact);color:var(--accent)}
.v-sep{height:1px;background:var(--border);width:50%;margin:0 auto;opacity:0.4}
.m-btn{width:48px;height:48px;border-radius:50%;background:var(--btn);
  border:2px solid var(--border);display:flex;align-items:center;justify-content:center;
  cursor:pointer;font-size:.7rem;transition:all .15s;color:var(--dim);font-weight:bold;letter-spacing:1px}
.m-btn:active,.m-btn.P{background:var(--bact);color:var(--accent);border-color:var(--accent);box-shadow:0 0 12px #00d4ff22}
</style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
  <button class="power-btn" onclick="sk('power')" title="Power">⏻</button>
  <button class="pair-capsule" id="pair-cap" onclick="onPairTap()">Pair</button>
  <button class="reconnect-btn" onclick="doReconnect()" title="Reconnect">↻</button>
</div>

<!-- DPAD -->
<div class="dpad-wrap">
  <div class="dpad-circle">
    <div class="quad q-up"    onclick="sk('up')">▲</div>
    <div class="quad q-down"  onclick="sk('down')">▼</div>
    <div class="quad q-left"  onclick="sk('left')">◀</div>
    <div class="quad q-right" onclick="sk('right')">▶</div>
  </div>
  <div class="ok-btn" id="ok-btn" onclick="sk('select')">OK</div>
</div>

<!-- BACK / HOME -->
<div class="bottom-caps">
  <div class="caps-btn" onclick="sk('back')">BACK</div>
  <div class="caps-divider"></div>
  <div class="caps-btn" onclick="sk('home')">HOME</div>
</div>

<!-- VOLUME SECTION -->
<div class="vol-row">
  <div class="v-capsule">
    <div class="v-btn" onclick="sk('vol_up')" title="Volume Up">+</div>
    <div class="v-sep"></div>
    <div class="v-btn" onclick="sk('vol_dn')" title="Volume Down">-</div>
  </div>
  <div class="m-btn" onclick="sk('mute')" title="Mute">MUTE</div>
</div>

<!-- LOG -->
<div class="log" id="log"></div>

<!-- DEVICE SCANNER MODAL (bottom sheet) -->
<div class="overlay" id="scanner-overlay" onclick="closeScannerIfBg(event)">
  <div class="sheet" id="scanner-sheet">
    <div class="sheet-header">
      <span class="sheet-title">SELECT TV</span>
      <button class="x-btn" onclick="closeScanner()">✕</button>
    </div>
    <div class="sheet-body">
      <div class="scan-status" id="scan-status">
        <div class="spinner" id="scan-spinner"></div>
        <span id="scan-text">Scanning... (Fast)</span>
      </div>
      <div id="tv-list"></div>
    </div>
  </div>
</div>

<!-- PAIRING CODE MODAL (center) -->
<div class="overlay center" id="pair-overlay">
  <div class="cmodal">
    <h3>ENTER TV CODE</h3>
    <input class="code-input" id="pair-code" type="text" maxlength="6" placeholder="ABC123" autocomplete="off" autocorrect="off" spellcheck="false">
    <button class="confirm-btn" onclick="confirmPair()">CONFIRM</button>
    <div class="pair-result" id="pair-result"></div>
  </div>
</div>

<!-- CONNECTED DROPDOWN -->
<div class="dropdown" id="conn-dropdown" style="display:none">
  <div class="dd-item" onclick="ddChangeDevice()">Change Device</div>
  <div class="dd-divider"></div>
  <div class="dd-item" onclick="ddDisconnect()" style="color:var(--red)">Disconnect</div>
</div>

<script>
const $=id=>document.getElementById(id);
const ts=()=>new Date().toLocaleTimeString();
let connected=false, connName='', pendingIP='', pendingName='';

function log(m,c='e'){
  const d=document.createElement('div');d.className=c;
  d.textContent=`[${ts()}] ${m}`;$('log').prepend(d);
  while($('log').children.length>30)$('log').lastChild.remove();
}
async function post(u,b={}){
  try{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return await r.json()}
  catch(e){return{ok:false,error:String(e)}}
}

// ── Key sending ──────────────────────────────────────────────────────────────
async function sk(key){
  document.querySelectorAll(`[onclick*="'${key}'"]`).forEach(b=>{
    b.classList.add('P');setTimeout(()=>b.classList.remove('P'),180)
  });
  const d=await post('/key',{key});
  if(d.ok) log(key.toUpperCase()+' ✓','ok');
  else log(key.toUpperCase()+' ✗ '+d.error,'er');
}

// ── Reconnect ────────────────────────────────────────────────────────────────
async function doReconnect(){
  log('Reconnecting...','wa');
  const r=await fetch('/state');
  const s=await r.json();
  if(s.connected || s.ip){
    const d=await post('/reconnect');
    if(d.ok) log('Reconnected ✓','ok');
    else log('Reconnect failed: '+d.error,'er');
  } else {
    log('No TV saved — use Pair','wa');
  }
}

// ── Pair capsule tap ─────────────────────────────────────────────────────────
function onPairTap(){
  if(connected) toggleDropdown();
  else openScanner();
}

// ── Dropdown ─────────────────────────────────────────────────────────────────
function toggleDropdown(){
  const dd=$('conn-dropdown');
  if(dd.style.display==='none'){
    const cap=$('pair-cap');
    const rect=cap.getBoundingClientRect();
    dd.style.top=(rect.bottom+6)+'px';
    dd.style.left=rect.left+'px';
    dd.style.display='block';
    setTimeout(()=>document.addEventListener('click',closeDDOutside,{once:true}),10);
  } else {
    dd.style.display='none';
  }
}
function closeDDOutside(e){if(!$('conn-dropdown').contains(e.target))$('conn-dropdown').style.display='none';}
function ddChangeDevice(){$('conn-dropdown').style.display='none';openScanner();}
async function ddDisconnect(){
  $('conn-dropdown').style.display='none';
  await post('/disconnect');
  connected=false;connName='';
  $('pair-cap').textContent='Pair';
  $('pair-cap').classList.remove('connected');
  log('Disconnected','wa');
}

// ── Scanner ──────────────────────────────────────────────────────────────────
function openScanner(){
  $('scanner-overlay').classList.add('show');
  $('tv-list').innerHTML='';
  $('scan-text').textContent='Scanning... (Fast)';
  $('scan-spinner').style.display='block';
  runScan();
}
function closeScanner(){$('scanner-overlay').classList.remove('show')}
function closeScannerIfBg(e){if(e.target===$('scanner-overlay'))closeScanner()}

async function runScan(){
  $('tv-list').innerHTML='';
  // Fast scan
  const fast=await post('/scan/fast');
  if(fast.ok && fast.results && fast.results.length>0){
    $('scan-text').textContent='Found '+fast.results.length+' device(s)';
    $('scan-spinner').style.display='none';
    showTVList(fast.results);
    return;
  }
  // Deep scan fallback
  $('scan-text').textContent='Fast scan found nothing. Deep scanning... (may take a minute)';
  const deep=await post('/scan/deep');
  $('scan-spinner').style.display='none';
  if(deep.ok && deep.results && deep.results.length>0){
    $('scan-text').textContent='Found '+deep.results.length+' device(s)';
    showTVList(deep.results);
  } else {
    $('scan-text').textContent='No Android TVs found on network';
  }
}

function showTVList(list){
  $('tv-list').innerHTML='';
  list.forEach(tv=>{
    const card=document.createElement('div');
    card.className='tv-card';
    card.innerHTML=`<div><div>${tv.name}</div></div><div style="color:var(--accent);font-size:.7rem">▶</div>`;
    card.onclick=()=>selectTV(tv.ip, tv.name);
    $('tv-list').appendChild(card);
  });
}

async function selectTV(ip, name){
  pendingIP=ip; pendingName=name;
  log('Connecting to '+name+'...','wa');
  const d=await post('/connect',{ip,name});
  if(!d.ok){log('Connect failed: '+d.error,'er');return;}
  if(d.paired){
    closeScanner();
    setConnected(name);
    log('Connected to '+name,'ok');
  } else if(d.needs_pairing){
    closeScanner();
    openPairModal();
  }
}

// ── Pairing modal ────────────────────────────────────────────────────────────
function openPairModal(){
  $('pair-code').value='';
  $('pair-result').textContent='';
  $('pair-result').className='pair-result';
  $('pair-overlay').classList.add('show');
  setTimeout(()=>$('pair-code').focus(),100);
}

async function confirmPair(){
  const code=$('pair-code').value.trim().toUpperCase();
  if(!code){$('pair-result').textContent='Enter the code!';return;}
  $('pair-result').textContent='Verifying...';
  $('pair-result').className='pair-result';
  const d=await post('/finish_pair',{code});
  if(d.ok){
    $('pair-result').textContent='✓ Pairing Successful!';
    $('pair-result').className='pair-result ok';
    setTimeout(()=>{
      $('pair-overlay').classList.remove('show');
      setConnected(pendingName||pendingIP);
      log('Paired & connected to '+(pendingName||pendingIP),'ok');
    },1200);
  } else {
    $('pair-result').textContent='✗ Failed: '+d.error;
    $('pair-result').className='pair-result er';
    log('Pair failed: '+d.error,'er');
  }
}

function setConnected(name){
  connected=true; connName=name;
  $('pair-cap').textContent=name;
  $('pair-cap').classList.add('connected');
}

// Init — restore state
(async()=>{
  const r=await fetch('/state');
  const s=await r.json();
  if(s.connected){setConnected(s.name||s.ip);log('Restored: '+s.name,'ok')}
})();
</script>
</body>
</html>"""

# Initialize on startup (works for both local and Vercel)
load_config()

if __name__ == "__main__":
    # Local development mode
    print("="*45)
    print("  TV Remote  |  http://localhost:5000")
    print("  pip install flask androidtvremote2")
    print("="*45)
    app.run(host="0.0.0.0", port=5000, debug=False)

# Note: When running on Vercel, the app is imported by api/index.py
# and served as a serverless function. No additional setup needed here.