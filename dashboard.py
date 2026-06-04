"""
Flask dashboard (LAN only, no auth).

Runs on its own daemon thread so it never blocks the capture loop. Serves:
    /             status page (live badge, FPS, disk, uptime, backend)
    /clips        responsive card grid of recorded clips with inline players
    /stream       MJPEG live preview (replaces the --show GUI on a headless Pi)
    /status.json  machine-readable status (the status page polls this)
    /media/<name> serve / download a clip

The UI is deliberately a bright, Apple-style light theme: system fonts,
generous whitespace, rounded cards, a single blue accent. Looks good on iPhone.
"""

from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("gkcam.dashboard")

# ---------------------------------------------------------------------------
# Shared CSS + page chrome
# ---------------------------------------------------------------------------
BASE_CSS = """
:root { --accent:#007aff; --bg:#f5f5f7; --card:#ffffff; --text:#1d1d1f;
        --muted:#6e6e73; --green:#34c759; --red:#ff3b30; --orange:#ff9500; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       -webkit-font-smoothing:antialiased; }
.wrap { max-width:960px; margin:0 auto; padding:24px 18px 64px; }
header { display:flex; align-items:center; justify-content:space-between;
         margin:8px 0 28px; }
h1 { font-size:26px; font-weight:600; letter-spacing:-0.02em; margin:0; }
nav a { text-decoration:none; color:var(--accent); font-weight:500;
        font-size:15px; margin-left:18px; }
.card { background:var(--card); border-radius:18px; padding:22px;
        box-shadow:0 1px 3px rgba(0,0,0,0.06); margin-bottom:18px; }
.badge { display:inline-flex; align-items:center; gap:8px; font-weight:600;
         font-size:15px; padding:8px 16px; border-radius:980px; }
.badge .dot { width:10px; height:10px; border-radius:50%; }
.idle { background:rgba(52,199,89,0.12); color:#1e8e3e; }
.idle .dot { background:var(--green); }
.rec  { background:rgba(255,59,48,0.12); color:#c4271d; }
.rec  .dot { background:var(--red); animation:pulse 1s infinite; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.35;} }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
        gap:14px; }
.stat { background:var(--bg); border-radius:14px; padding:16px; }
.stat .label { color:var(--muted); font-size:13px; margin-bottom:6px; }
.stat .value { font-size:22px; font-weight:600; letter-spacing:-0.01em; }
.preview { width:100%; border-radius:14px; display:block; background:#000; }
.warn { background:rgba(255,149,0,0.12); color:#9a5b00; border-radius:14px;
        padding:14px 16px; font-weight:500; margin-bottom:18px; }
.clips { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
         gap:18px; }
.clip video { width:100%; border-radius:12px; background:#000; display:block; }
.clip .name { font-weight:600; margin:12px 0 4px; font-size:15px;
              word-break:break-all; }
.clip .meta { color:var(--muted); font-size:13px; line-height:1.5; }
.btn { display:inline-block; margin-top:12px; background:var(--accent);
       color:#fff; text-decoration:none; padding:9px 16px; border-radius:980px;
       font-size:14px; font-weight:500; }
.empty { color:var(--muted); text-align:center; padding:48px 0; }
"""

HEADER = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Goalkeeper Cam</title><style>{css}</style></head><body><div class="wrap">
<header><h1>{title}</h1><nav><a href="/">Status</a><a href="/clips">Clips</a></nav></header>
"""

FOOTER = "</div></body></html>"


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _clip_duration(path: str) -> str:
    """Best-effort duration via OpenCV; returns 'm:ss' or '—'."""
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        if fps > 0 and frames > 0:
            total = int(frames / fps)
            return f"{total // 60}:{total % 60:02d}"
    except Exception:
        pass
    return "—"


def create_app(cfg, state):
    from flask import (Flask, Response, jsonify, render_template_string,
                       request, send_from_directory)

    app = Flask(__name__)

    @app.route("/")
    def index():
        body = """
        {% if state.disk_warning %}
        <div class="warn">⚠️ Disk limit reached ({{ cfg.max_disk_usage_gb }} GB) —
        new recordings are paused. Free up space in the clips folder.</div>
        {% endif %}
        <div class="card">
          {% if state.status == "RECORDING" %}
            <span class="badge rec"><span class="dot"></span>RECORDING</span>
          {% else %}
            <span class="badge idle"><span class="dot"></span>IDLE</span>
          {% endif %}
        </div>
        <div class="card">
          <img class="preview" src="/stream" alt="live preview">
        </div>
        <div class="grid">
          <div class="stat"><div class="label">FPS</div><div class="value" id="fps">{{ '%.1f'|format(state.fps) }}</div></div>
          <div class="stat"><div class="label">Clips</div><div class="value" id="clips">{{ state.clip_count }}</div></div>
          <div class="stat"><div class="label">Disk free</div><div class="value" id="disk">{{ '%.1f'|format(state.disk_free_gb) }} GB</div></div>
          <div class="stat"><div class="label">Clips size</div><div class="value" id="size">{{ '%.1f'|format(state.clips_size_gb) }} GB</div></div>
          <div class="stat"><div class="label">Uptime</div><div class="value" id="uptime">{{ uptime }}</div></div>
          <div class="stat"><div class="label">Camera</div><div class="value">{{ state.backend }}</div></div>
        </div>
        <script>
        async function tick(){
          try{
            const r = await fetch('/status.json'); const d = await r.json();
            document.getElementById('fps').textContent = d.fps.toFixed(1);
            document.getElementById('clips').textContent = d.clip_count;
            document.getElementById('disk').textContent = d.disk_free_gb.toFixed(1)+' GB';
            document.getElementById('size').textContent = d.clips_size_gb.toFixed(1)+' GB';
            document.getElementById('uptime').textContent = d.uptime;
          }catch(e){}
        }
        setInterval(tick, 2000);
        </script>
        """
        page = HEADER.format(css=BASE_CSS, title="Goalkeeper Cam") + body + FOOTER
        return render_template_string(page, cfg=cfg, state=state,
                                      uptime=_fmt_uptime(state.uptime_seconds))

    @app.route("/status.json")
    def status_json():
        return jsonify(
            status=state.status,
            fps=round(state.fps, 1),
            clip_count=state.clip_count,
            backend=state.backend,
            disk_free_gb=round(state.disk_free_gb, 2),
            clips_size_gb=round(state.clips_size_gb, 2),
            disk_warning=state.disk_warning,
            uptime=_fmt_uptime(state.uptime_seconds),
        )

    @app.route("/clips")
    def clips_page():
        clips = []
        if os.path.isdir(cfg.output):
            names = [n for n in os.listdir(cfg.output) if n.endswith(".mp4")]
            for name in sorted(names, reverse=True):  # newest first
                path = os.path.join(cfg.output, name)
                st = os.stat(path)
                clips.append(dict(
                    name=name,
                    size_mb=st.st_size / 1e6,
                    ts=time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.localtime(st.st_mtime)),
                    duration=_clip_duration(path),
                ))
        body = """
        {% if clips %}
        <div class="clips">
          {% for c in clips %}
          <div class="card clip">
            <video controls preload="metadata" src="/media/{{ c.name }}"></video>
            <div class="name">{{ c.name }}</div>
            <div class="meta">{{ c.ts }}<br>{{ c.duration }} · {{ '%.1f'|format(c.size_mb) }} MB</div>
            <a class="btn" href="/media/{{ c.name }}?download=1">Download</a>
          </div>
          {% endfor %}
        </div>
        {% else %}
        <div class="card empty">No clips yet. Wave in front of the camera!</div>
        {% endif %}
        """
        page = HEADER.format(css=BASE_CSS, title="Clips") + body + FOOTER
        return render_template_string(page, clips=clips)

    @app.route("/media/<path:name>")
    def media(name):
        as_attachment = bool(request.args.get("download"))
        return send_from_directory(cfg.output, name, as_attachment=as_attachment)

    @app.route("/stream")
    def stream():
        def gen():
            boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
            while True:
                jpeg = state.get_preview()
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                yield boundary + jpeg + b"\r\n"
                time.sleep(1.0 / max(1, cfg.fps))
        return Response(gen(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


def start_dashboard(cfg, state) -> None:
    """Start Flask on a daemon thread. Never crash the app if Flask is absent."""
    try:
        app = create_app(cfg, state)
    except ImportError:
        log.warning("Flask not installed; dashboard disabled. "
                    "Install with: pip install flask")
        return

    def run():
        # threaded=True so the MJPEG stream doesn't block status requests
        app.run(host="0.0.0.0", port=cfg.dashboard_port,
                threaded=True, debug=False, use_reloader=False)

    thread = threading.Thread(target=run, name="dashboard", daemon=True)
    thread.start()
    log.info("Dashboard on http://0.0.0.0:%d", cfg.dashboard_port)
