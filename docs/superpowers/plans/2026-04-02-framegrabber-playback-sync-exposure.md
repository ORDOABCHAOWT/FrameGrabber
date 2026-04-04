# FrameGrabber Playback Sync And Exposure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace timer-driven preview playback with synchronized browser video playback and add an exposure control that affects preview and captured PNG output.

**Architecture:** Use the existing `/api/video` endpoint for real-time browser playback and keep `/api/frame` for exact paused preview and scrubbing. Thread a shared `exposure` value through the frontend UI plus `/api/frame` and `/api/grab`, applying CSS filters in the browser and FFmpeg filters on the backend so the saved image matches the adjusted preview closely.

**Tech Stack:** Python, Flask, HTML/CSS/JavaScript, Node test runner, FFmpeg

---

### Task 1: Add backend regression tests for exposure-aware frame and grab routes

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_frame_endpoint_passes_exposure_filter_to_ffmpeg(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

        preview_path = os.path.join(framegrabber.TEMP_DIR, "preview-test.jpg")

        def fake_mkstemp(prefix, suffix, dir):
            fd = os.open(preview_path, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o600)
            return fd, preview_path

        def fake_run(cmd, capture_output=True, timeout=10):
            self.assertIn("eq=exposure=0.4", cmd[cmd.index("-vf") + 1])
            with open(preview_path, "wb") as fh:
                fh.write(b"jpeg-bytes")
            return type("Proc", (), {"returncode": 0})()

        try:
            framegrabber.VIDEOS[1] = {
                "path": temp_path,
                "filename": os.path.basename(temp_path),
                "duration": 2.0,
                "fps": 24.0,
                "width": 640,
                "height": 360,
                "codec": "h264",
            }
            framegrabber.ACTIVE_ID = 1

            with patch.object(framegrabber.tempfile, "mkstemp", side_effect=fake_mkstemp), \
                 patch.object(framegrabber.subprocess, "run", side_effect=fake_run):
                response = self.client.get("/api/frame?vid=1&t=0.500&exposure=0.4")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"jpeg-bytes")
        finally:
            if os.path.exists(preview_path):
                os.remove(preview_path)
            os.remove(temp_path)

    def test_grab_endpoint_passes_exposure_filter_to_ffmpeg(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

        save_dir = tempfile.mkdtemp()

        def fake_run(cmd, capture_output=True, text=True, timeout=30):
            self.assertIn("eq=exposure=-0.3", cmd[cmd.index("-vf") + 1])
            output_path = cmd[-1]
            with open(output_path, "wb") as fh:
                fh.write(b"png-bytes")
            return type("Proc", (), {"returncode": 0})()

        try:
            framegrabber.VIDEOS[1] = {
                "path": temp_path,
                "filename": os.path.basename(temp_path),
                "duration": 2.0,
                "fps": 24.0,
                "width": 640,
                "height": 360,
                "codec": "h264",
            }
            framegrabber.ACTIVE_ID = 1
            with framegrabber.STATE_LOCK:
                original_save_dir = framegrabber.SAVE_DIR
                framegrabber.SAVE_DIR = save_dir

            with patch.object(framegrabber.subprocess, "run", side_effect=fake_run):
                response = self.client.post("/api/grab", json={"vid": 1, "time": 0.25, "exposure": -0.3})

            self.assertEqual(response.status_code, 200)
            self.assertIn("filename", response.get_json())
        finally:
            with framegrabber.STATE_LOCK:
                framegrabber.SAVE_DIR = original_save_dir
            for name in os.listdir(save_dir):
                os.remove(os.path.join(save_dir, name))
            os.rmdir(save_dir)
            os.remove(temp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_app -v`
Expected: FAIL because `/api/frame` and `/api/grab` do not yet include `exposure` handling or FFmpeg filter assertions.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_exposure(raw_value):
    try:
        return max(-1.0, min(1.0, float(raw_value)))
    except (TypeError, ValueError):
        return 0.0

def build_eq_filter(exposure, include_scale=False):
    filters = []
    if include_scale:
        filters.append("scale='min(1280,iw)':-1")
    if abs(exposure) > 0.0001:
        filters.append(f"eq=exposure={exposure:.3f}")
    return ",".join(filters) if filters else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/whitney/Downloads/FrameGrabber/tests/test_app.py /Users/whitney/Downloads/FrameGrabber/app.py
git commit -m "test: cover exposure-aware frame capture"
```

### Task 2: Add synchronized browser-video playback UI

**Files:**
- Modify: `static/index.html`
- Test: `tests/test_playback_scheduler.js`

- [ ] **Step 1: Write the failing frontend test**

```javascript
test('playback mode does not request deferred jpg previews for time progression', () => {
  const plan = getPreviewRequestPlan({
    isDragging: false,
    isPlaying: true,
    hasPendingLoad: false,
    useVideoPlayback: true,
  });

  assert.deepEqual(plan, {
    abortPending: false,
    defer: false,
    debounceMs: 0,
    shouldLoadPreview: false,
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/test_playback_scheduler.js`
Expected: FAIL because the scheduler does not yet describe video-backed playback behavior.

- [ ] **Step 3: Write minimal implementation**

```javascript
function getPreviewRequestPlan({ isDragging, isPlaying, hasPendingLoad, useVideoPlayback = false }) {
  if (isPlaying && useVideoPlayback) {
    return {
      abortPending: hasPendingLoad,
      defer: false,
      debounceMs: 0,
      shouldLoadPreview: false,
    };
  }

  if (isPlaying && hasPendingLoad) {
    return {
      abortPending: false,
      defer: true,
      debounceMs: 0,
      shouldLoadPreview: true,
    };
  }

  return {
    abortPending: hasPendingLoad,
    defer: false,
    debounceMs: isDragging ? 100 : 30,
    shouldLoadPreview: true,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/test_playback_scheduler.js`
Expected: PASS

- [ ] **Step 5: Update the playback UI**

```html
<video id="previewVideo" playsinline muted preload="metadata"></video>
<img id="previewImg" src="" alt="">
```

```javascript
function startPlayback() {
  previewVideo.src = `/api/video?vid=${activeId}`;
  previewVideo.currentTime = currentTime;
  previewVideo.play();
}

previewVideo.addEventListener('timeupdate', syncTimelineFromVideo);
previewVideo.addEventListener('pause', syncPausedFrameFromVideo);
previewVideo.addEventListener('ended', syncPausedFrameFromVideo);
```

- [ ] **Step 6: Run focused tests and manual smoke check**

Run: `node --test tests/test_playback_scheduler.js`
Expected: PASS

Manual:
- open the app
- import a short clip
- press play
- confirm picture and timeline move together
- pause mid-playback and confirm the paused frame matches the shown time

- [ ] **Step 7: Commit**

```bash
git add /Users/whitney/Downloads/FrameGrabber/static/index.html /Users/whitney/Downloads/FrameGrabber/static/playback_scheduler.js /Users/whitney/Downloads/FrameGrabber/tests/test_playback_scheduler.js
git commit -m "feat: sync preview playback with browser video"
```

### Task 3: Add exposure controls to preview and capture

**Files:**
- Modify: `static/index.html`
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write the failing UI-facing test case by extending existing backend coverage**

```python
    def test_frame_cache_key_changes_with_exposure(self):
        framegrabber.FRAME_CACHE[1] = {"0.500|0.000": b"plain"}

        response = self.client.get("/api/frame?vid=1&t=0.500&exposure=0.5")

        self.assertNotEqual(response.data, b"plain")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_app -v`
Expected: FAIL because cache keys do not yet distinguish exposure variants.

- [ ] **Step 3: Write minimal implementation**

```javascript
let exposureValue = 0;

function applyPreviewExposure() {
  const brightness = (1 + exposureValue * 0.35).toFixed(3);
  const filter = `brightness(${brightness})`;
  previewImg.style.filter = filter;
  previewVideo.style.filter = filter;
}

function updateExposure(nextValue) {
  exposureValue = Number(nextValue);
  applyPreviewExposure();
  if (!isPlaying) {
    seekTo(currentTime);
  }
}
```

```python
t_key = f"{t:.3f}|{exposure:.3f}"
vf_filter = build_eq_filter(exposure, include_scale=True)
if vf_filter:
    ffmpeg_cmd.extend(["-vf", vf_filter])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

- [ ] **Step 5: Manual verification**

Manual:
- move exposure slider darker and lighter while paused
- confirm preview updates immediately
- capture a frame at each setting
- verify saved PNG brightness matches the adjusted preview closely

- [ ] **Step 6: Commit**

```bash
git add /Users/whitney/Downloads/FrameGrabber/app.py /Users/whitney/Downloads/FrameGrabber/static/index.html /Users/whitney/Downloads/FrameGrabber/tests/test_app.py
git commit -m "feat: add exposure-adjusted preview capture"
```
