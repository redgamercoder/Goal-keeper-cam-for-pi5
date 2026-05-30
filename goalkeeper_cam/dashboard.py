"""Thread 4 — Flask web dashboard on port 8080."""
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

from .config import Config

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent.parent / "templates"),
    static_folder=str(Path(__file__).parent.parent / "static"),
)

# Set by start_dashboard(); avoids global state in tests
_state: Dict[str, Any] = {}


def _get_disk_free_gb(path: str) -> float:
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / 1e9, 2)
    except OSError:
        return -1.0


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/clips")
def clips_page():
    page = int(request.args.get("page", 1))
    per_page = 12
    index: list = _state.get("clip_index", [])
    total = len(index)
    start = (page - 1) * per_page
    clips = index[start: start + per_page]
    return render_template(
        "clips.html",
        clips=clips,
        page=page,
        total_pages=max(1, (total + per_page - 1) // per_page),
    )


@app.route("/clips/<path:filename>")
def serve_clip(filename: str):
    clips_dir = _state["config"].clip_storage_dir()
    filepath = os.path.join(clips_dir, filename)
    if not os.path.exists(filepath):
        abort(404)
    return send_file(filepath, mimetype="video/mp4", conditional=True)


@app.route("/api/status")
def api_status():
    config: Config = _state["config"]
    clips_dir = config.clip_storage_dir()
    return jsonify({
        "state": _state.get("recorder_state", "unknown"),
        "fps": round(_state.get("fps_actual", 0.0), 1),
        "last_ball_time": _state.get("last_ball_time"),
        "disk_free_gb": _get_disk_free_gb(clips_dir),
        "clip_count": len(_state.get("clip_index", [])),
        "uptime_s": round(time.time() - _state.get("start_time", time.time())),
    })


@app.route("/api/config", methods=["POST"])
def api_config():
    config: Config = _state["config"]
    data = request.get_json(force=True)
    allowed = {"hold_seconds", "confidence", "detect_every_n"}
    for key in allowed:
        if key in data:
            try:
                val = type(getattr(config, key))(data[key])
                setattr(config, key, val)
            except (ValueError, TypeError) as e:
                return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

def start_dashboard(
    config: Config,
    clip_index: list,
    clip_index_lock: threading.Lock,
    get_recorder_state,
    get_fps,
    get_last_ball_time,
) -> threading.Thread:
    _state.update({
        "config": config,
        "clip_index": clip_index,
        "clip_index_lock": clip_index_lock,
        "get_recorder_state": get_recorder_state,
        "get_fps": get_fps,
        "get_last_ball_time": get_last_ball_time,
        "start_time": time.time(),
    })

    def _refresh_state():
        while True:
            _state["recorder_state"] = get_recorder_state()
            _state["fps_actual"] = get_fps()
            _state["last_ball_time"] = get_last_ball_time()
            time.sleep(0.5)

    t_refresh = threading.Thread(target=_refresh_state, daemon=True, name="state-refresh")
    t_refresh.start()

    def _run():
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)
        app.run(host=config.host, port=config.port, threaded=True, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info("Dashboard: http://%s:%d", config.host, config.port)
    return t
