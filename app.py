#!/usr/bin/env python3
"""
FrameGrabber - 从视频中提取原始分辨率帧的轻量工具
Web UI + FFmpeg 后端，支持多视频管理
"""

import os
import sys
import json
import time
import socket
import shutil
import mimetypes
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path
from flask import Flask, request, jsonify, send_file, make_response

app = Flask(__name__, static_folder="static")
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024 * 1024

# Ensure ffmpeg/ffprobe are findable (macOS .app bundles have minimal PATH)
_EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin"]
for _p in _EXTRA_PATHS:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")

# ── State ──────────────────────────────────────────────
VIDEOS = {}        # id -> {path, filename, duration, fps, width, height, codec}
ACTIVE_ID = None   # currently selected video id
NEXT_ID = 1
SAVE_DIR = str(Path.home() / "Desktop")
GRAB_COUNT = 0
TEMP_DIR = tempfile.mkdtemp(prefix="framegrabber_")
UPLOAD_DIR = os.path.join(TEMP_DIR, "uploads")
STATE_LOCK = threading.RLock()
FRAME_RENDER_LOCKS = {}

# Frame cache: vid -> {time -> jpeg_bytes}
FRAME_CACHE = {}
CACHE_MAX_PER_VIDEO = 30
CLIENT_PING_LOCK = threading.RLock()
LAST_CLIENT_PING = 0.0
CLIENT_IDLE_TIMEOUT = 4.0
STARTUP_GRACE_PERIOD = 15.0
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv",
    ".ts", ".mts", ".m2ts", ".mxf", ".mpg", ".mpeg", ".wmv",
    ".3gp", ".ogv", ".vob"
}
os.makedirs(UPLOAD_DIR, exist_ok=True)


def probe_video(path):
    """Probe a video file and return metadata dict, or None on failure."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path
        ], capture_output=True, text=True, timeout=10)
        info = json.loads(result.stdout)
    except Exception:
        return None

    video_stream = None
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            video_stream = s
            break
    if not video_stream:
        return None

    duration = float(info["format"].get("duration", 0))
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    codec = video_stream.get("codec_name", "unknown")

    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str)

    return {
        "path": path,
        "filename": os.path.basename(path),
        "duration": duration,
        "fps": round(fps, 2),
        "width": width,
        "height": height,
        "codec": codec,
    }


def generate_thumbnail(vid, v):
    """Generate thumbnail in background thread."""
    thumb_path = os.path.join(TEMP_DIR, f"thumb_{vid}.jpg")
    if os.path.exists(thumb_path):
        return
    try:
        t = min(1.0, v["duration"] * 0.1)
        subprocess.run([
            "ffmpeg", "-y", "-ss", f"{t:.3f}",
            "-i", v["path"],
            "-frames:v", "1",
            "-vf", "scale=160:-1",
            "-q:v", "4",
            thumb_path
        ], capture_output=True, timeout=10)
    except Exception:
        pass


def escape_applescript_string(value):
    """Escape a string for safe interpolation into AppleScript source."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_file_picker(prompt):
    """Open a native file picker without restrictive UTI filtering."""
    result = subprocess.run([
        "osascript", "-e",
        f'set pickerPrompt to "{escape_applescript_string(prompt)}"\n'
        'set f to (choose file with prompt pickerPrompt with multiple selections allowed)\n'
        'if class of f is not list then set f to {f}\n'
        'set out to ""\n'
        'repeat with i in f\n'
        '  set out to out & POSIX path of i & "\\n"\n'
        'end repeat\n'
        'return out'
    ], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return []
    return [
        p.strip() for p in result.stdout.strip().split("\n")
        if p.strip() and os.path.isfile(p.strip())
    ]


def filter_video_paths(paths):
    """Keep only likely video files while staying tolerant of uncommon codecs."""
    valid = []
    for path in paths:
        ext = Path(path).suffix.lower()
        if ext in VIDEO_EXTENSIONS or probe_video(path):
            valid.append(path)
    return valid


def get_frame_render_lock(vid):
    """Return a stable per-video lock for preview rendering."""
    with STATE_LOCK:
        lock = FRAME_RENDER_LOCKS.get(vid)
        if lock is None:
            lock = threading.Lock()
            FRAME_RENDER_LOCKS[vid] = lock
        return lock


def normalize_video_meta(path, meta, filename=None):
    """Ensure probed metadata matches the stored file path and display name."""
    normalized = dict(meta)
    normalized["path"] = path
    normalized["filename"] = filename or os.path.basename(path)
    return normalized


def register_video(path, filename=None):
    """Probe and register a video, returning the stored record payload or None."""
    global NEXT_ID
    if not path or not os.path.isfile(path):
        return None

    with STATE_LOCK:
        duplicate = next(
            ({"id": vid, **v} for vid, v in VIDEOS.items() if v["path"] == path),
            None
        )
    if duplicate:
        return duplicate

    meta = probe_video(path)
    if not meta:
        return None
    meta = normalize_video_meta(path, meta, filename=filename)

    with STATE_LOCK:
        duplicate = next(
            ({"id": vid, **v} for vid, v in VIDEOS.items() if v["path"] == path),
            None
        )
        if duplicate:
            return duplicate

        vid = NEXT_ID
        NEXT_ID += 1
        VIDEOS[vid] = meta
        stored = {"id": vid, **meta}

    threading.Thread(target=generate_thumbnail, args=(vid, meta), daemon=True).start()
    return stored


def infer_video_mimetype(path):
    """Guess a browser-friendly mimetype for streamed video files."""
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


# ── Routes ─────────────────────────────────────────────
@app.after_request
def add_no_cache(response):
    """Prevent browser from caching HTML/API responses."""
    if 'text/html' in response.content_type or 'application/json' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.route("/")
def index():
    # Read and serve manually to fully bypass any browser caching
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    resp = make_response(content)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route("/api/add", methods=["POST"])
def add_video():
    """Add one or more videos. Accepts {paths: [...]}."""
    global ACTIVE_ID
    data = request.json or {}
    paths = data.get("paths", [])
    if isinstance(paths, str):
        paths = [paths]

    added = []
    for p in paths:
        stored = register_video(p)
        if stored:
            added.append(stored)

    with STATE_LOCK:
        # auto-select: if current active is invalid or none, pick the first added
        if added and (ACTIVE_ID is None or ACTIVE_ID not in VIDEOS):
            ACTIVE_ID = added[0]["id"]
        active = ACTIVE_ID

    return jsonify({"added": added, "active": active})


@app.route("/api/upload", methods=["POST"])
def upload_videos():
    """Accept dragged files directly from the browser and import them."""
    global ACTIVE_ID
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "未收到文件"}), 400

    added = []
    for storage in files:
        original_name = Path(storage.filename or "video").name
        stem = Path(original_name).stem or "video"
        suffix = Path(original_name).suffix or ".mp4"
        fd, temp_path = tempfile.mkstemp(
            prefix=f"{stem}_",
            suffix=suffix,
            dir=UPLOAD_DIR,
        )
        os.close(fd)

        try:
            storage.save(temp_path)
            stored = register_video(temp_path, filename=original_name)
            if stored:
                added.append(stored)
            else:
                os.remove(temp_path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    with STATE_LOCK:
        if added and (ACTIVE_ID is None or ACTIVE_ID not in VIDEOS):
            ACTIVE_ID = added[0]["id"]
        active = ACTIVE_ID

    return jsonify({"added": added, "active": active})


@app.route("/api/select", methods=["POST"])
def select_video():
    """Switch active video."""
    global ACTIVE_ID
    data = request.json or {}
    vid = data.get("id")
    with STATE_LOCK:
        if vid in VIDEOS:
            ACTIVE_ID = vid
            return jsonify({"active": vid, "video": VIDEOS[vid]})
    return jsonify({"error": "视频不存在"}), 404


@app.route("/api/remove", methods=["POST"])
def remove_video():
    """Remove a video from the list."""
    global ACTIVE_ID
    data = request.json or {}
    vid = data.get("id")
    with STATE_LOCK:
        if vid in VIDEOS:
            del VIDEOS[vid]
            FRAME_CACHE.pop(vid, None)
            FRAME_RENDER_LOCKS.pop(vid, None)
            if ACTIVE_ID == vid:
                ACTIVE_ID = next(iter(VIDEOS), None)
            return jsonify({"active": ACTIVE_ID})
    return jsonify({"error": "视频不存在"}), 404


@app.route("/api/videos")
def list_videos():
    with STATE_LOCK:
        vids = [{"id": k, **v} for k, v in VIDEOS.items()]
        active = ACTIVE_ID
    return jsonify({"videos": vids, "active": active})


@app.route("/api/choose", methods=["POST"])
def choose_file():
    """Native file dialog, supports multiple selection."""
    try:
        paths = filter_video_paths(run_file_picker("选择视频文件"))
        return jsonify({"paths": paths})
    except Exception:
        return jsonify({"paths": []})


@app.route("/api/resolve_paths", methods=["POST"])
def resolve_paths():
    """Resolve real file paths from drag-drop filenames using mdfind (Spotlight)."""
    data = request.json or {}
    names = data.get("names", [])
    sizes = data.get("sizes", [])  # file sizes for disambiguation
    if not names:
        return jsonify({"paths": []})

    paths = []
    for i, name in enumerate(names):
        size = sizes[i] if i < len(sizes) else 0

        # Use mdfind (Spotlight index) to find exact filename - instant, no disk scan
        try:
            result = subprocess.run(
                ["mdfind", "-name", name],
                capture_output=True, text=True, timeout=5
            )
            candidates = [p.strip() for p in result.stdout.strip().split("\n")
                         if p.strip() and os.path.isfile(p.strip())
                         and os.path.basename(p.strip()) == name]

            if len(candidates) == 1:
                paths.append(candidates[0])
            elif len(candidates) > 1 and size > 0:
                # Disambiguate by file size
                for c in candidates:
                    try:
                        if abs(os.path.getsize(c) - size) < 1024:
                            paths.append(c)
                            break
                    except OSError:
                        pass
                else:
                    # If size match fails, use the first one
                    paths.append(candidates[0])
            elif candidates:
                paths.append(candidates[0])
        except Exception:
            pass

    return jsonify({"paths": paths, "resolved": len(paths), "total": len(names)})


@app.route("/api/choose_for_drop", methods=["POST"])
def choose_for_drop():
    """Fallback: open native file dialog when path resolution fails."""
    data = request.json or {}
    count = data.get("count", 1)
    try:
        prompt = f"请选择刚才拖入的 {count} 个视频文件"
        paths = filter_video_paths(run_file_picker(prompt))
        return jsonify({"paths": paths})
    except Exception:
        return jsonify({"paths": []})


@app.route("/api/choose_dir", methods=["POST"])
def choose_dir():
    global SAVE_DIR
    try:
        result = subprocess.run([
            "osascript", "-e",
            'POSIX path of (choose folder with prompt "选择保存目录")'
        ], capture_output=True, text=True, timeout=60)
        path = result.stdout.strip()
        if path and os.path.isdir(path):
            with STATE_LOCK:
                SAVE_DIR = path
            return jsonify({"dir": path, "name": os.path.basename(path.rstrip("/"))})
        return jsonify({"dir": None})
    except Exception:
        return jsonify({"dir": None})


@app.route("/api/frame")
def get_frame():
    """Return a preview frame (JPEG) at the given time. Uses scaled preview for speed."""
    vid = request.args.get("vid", None)
    try:
        vid = int(vid) if vid is not None else None
        t = float(request.args.get("t", "0"))
    except (TypeError, ValueError):
        return "Invalid request", 400

    t_key = f"{t:.3f}"
    with STATE_LOCK:
        if vid is None:
            vid = ACTIVE_ID
        if vid not in VIDEOS:
            return "No video", 404
        v = dict(VIDEOS[vid])
        cached_frame = FRAME_CACHE.get(vid, {}).get(t_key)

    if cached_frame is not None:
        return cached_frame, 200, {'Content-Type': 'image/jpeg'}

    render_lock = get_frame_render_lock(vid)
    with render_lock:
        with STATE_LOCK:
            if vid not in VIDEOS:
                return "No video", 404
            v = dict(VIDEOS[vid])
            cached_frame = FRAME_CACHE.get(vid, {}).get(t_key)
            if cached_frame is not None:
                return cached_frame, 200, {'Content-Type': 'image/jpeg'}

        preview_fd, preview_path = tempfile.mkstemp(
            prefix=f"preview_{vid}_",
            suffix=".jpg",
            dir=TEMP_DIR
        )
        os.close(preview_fd)
        try:
            result = subprocess.run([
                "ffmpeg", "-y",
                "-ss", f"{t:.3f}",
                "-i", v["path"],
                "-frames:v", "1",
                "-vf", "scale='min(1280,iw)':-1",
                "-q:v", "3",
                "-threads", "2",
                preview_path
            ], capture_output=True, timeout=10)
            if result.returncode != 0 or not os.path.exists(preview_path):
                return "FFmpeg error", 500

            with open(preview_path, 'rb') as f:
                data = f.read()

            with STATE_LOCK:
                cache = FRAME_CACHE.setdefault(vid, {})
                existing = cache.get(t_key)
                if existing is not None:
                    data = existing
                else:
                    if len(cache) >= CACHE_MAX_PER_VIDEO:
                        oldest = next(iter(cache))
                        del cache[oldest]
                    cache[t_key] = data
            return data, 200, {'Content-Type': 'image/jpeg'}
        finally:
            try:
                os.remove(preview_path)
            except OSError:
                pass


@app.route("/api/thumbnail")
def get_thumbnail():
    vid = request.args.get("vid", None)
    if vid is None:
        return "Missing vid", 400
    try:
        vid = int(vid)
    except (TypeError, ValueError):
        return "Invalid vid", 400
    with STATE_LOCK:
        if vid not in VIDEOS:
            return "No video", 404
        v = dict(VIDEOS[vid])
    thumb_path = os.path.join(TEMP_DIR, f"thumb_{vid}.jpg")

    # If thumbnail not ready yet, generate it now
    if not os.path.exists(thumb_path):
        generate_thumbnail(vid, v)

    if os.path.exists(thumb_path):
        return send_file(thumb_path, mimetype="image/jpeg")
    return "Thumb not found", 404


@app.route("/api/video")
def get_video():
    """Stream the stored video file for browser-side playback helpers."""
    vid = request.args.get("vid", None)
    try:
        vid = int(vid) if vid is not None else None
    except (TypeError, ValueError):
        return "Invalid vid", 400

    with STATE_LOCK:
        if vid is None:
            vid = ACTIVE_ID
        if vid not in VIDEOS:
            return "No video", 404
        path = VIDEOS[vid]["path"]

    if not os.path.isfile(path):
        return "Missing file", 404

    return send_file(
        path,
        mimetype=infer_video_mimetype(path),
        conditional=True,
        etag=False,
        max_age=0,
    )


@app.route("/api/grab", methods=["POST"])
def grab_frame():
    """Extract current frame at full resolution as PNG."""
    global GRAB_COUNT
    data = request.json or {}

    with STATE_LOCK:
        vid = data.get("vid", ACTIVE_ID)
        if vid not in VIDEOS:
            return jsonify({"error": "未选择视频"}), 400
        v = dict(VIDEOS[vid])
        save_dir = SAVE_DIR
    t = float(data.get("time", 0))

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t % 1) * 1000)
    time_tag = f"{h:02d}{m:02d}{s:02d}_{ms:03d}"

    video_name = Path(v["path"]).stem
    filename = f"{video_name}_{time_tag}_{timestamp}.png"
    output_path = os.path.join(save_dir, filename)

    try:
        result = subprocess.run([
            "ffmpeg", "-y", "-ss", f"{t:.3f}",
            "-i", v["path"],
            "-frames:v", "1",
            "-compression_level", "3",
            output_path
        ], capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return jsonify({"error": "截取失败"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if os.path.exists(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        with STATE_LOCK:
            GRAB_COUNT += 1
            grab_count = GRAB_COUNT
        return jsonify({
            "filename": filename,
            "path": output_path,
            "size_kb": round(size_kb, 1),
            "width": v["width"],
            "height": v["height"],
            "count": grab_count,
        })
    return jsonify({"error": "保存失败"}), 500


@app.route("/api/state")
def get_state():
    with STATE_LOCK:
        save_dir = SAVE_DIR
    return jsonify({
        "save_dir": save_dir,
        "save_dir_name": os.path.basename(save_dir.rstrip("/")),
    })


@app.route("/api/ping", methods=["POST"])
def client_ping():
    note_client_ping()
    return jsonify({"ok": True})


# ── Main ───────────────────────────────────────────────
def cleanup():
    try:
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    except Exception:
        pass


def note_client_ping():
    global LAST_CLIENT_PING
    with CLIENT_PING_LOCK:
        LAST_CLIENT_PING = time.time()


def get_last_client_ping():
    with CLIENT_PING_LOCK:
        return LAST_CLIENT_PING


def _idle_shutdown_watchdog(started_at):
    """Exit the local server after the browser page has been closed for a while."""
    while True:
        time.sleep(1.0)
        now = time.time()
        last_ping = get_last_client_ping()

        if last_ping and (now - last_ping) > CLIENT_IDLE_TIMEOUT:
            cleanup()
            os._exit(0)

        if not last_ping and (now - started_at) > STARTUP_GRACE_PERIOD:
            cleanup()
            os._exit(0)

def _pick_port(preferred_port):
    """Use the preferred port when free, otherwise fall back to an ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", preferred_port))
            return preferred_port
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def main():
    started_at = time.time()
    port = _pick_port(9973)
    print(f"\n  FrameGrabber 启动中...")
    print(f"  http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")
    threading.Thread(target=_idle_shutdown_watchdog, args=(started_at,), daemon=True).start()

    try:
        app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    finally:
        cleanup()

if __name__ == "__main__":
    main()
