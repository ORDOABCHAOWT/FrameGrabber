# FrameGrabber Startup And Load Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make app startup and first video load feel faster by adding low-risk warmup and staged preview/video preparation without changing existing functionality or UI behavior.

**Architecture:** Keep the current Flask plus browser-video architecture, but add bounded background warmup on the backend and split frontend selection into a fast still-preview path plus reusable video-source preparation. Reuse the existing frame cache and playback synchronization so the optimization stays additive instead of invasive.

**Tech Stack:** Python, Flask, HTML/CSS/JavaScript, unittest, Node test runner, FFmpeg

---

### Task 1: Add backend regression tests for warmup and first-frame prewarm

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_schedule_active_video_prewarm_caches_neutral_first_frame(self):
        framegrabber.VIDEOS[1] = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 12.0,
            "fps": 24.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
        }

        with patch.object(framegrabber, "render_preview_frame_bytes", return_value=b"warm"), \
             patch.object(framegrabber.threading, "Thread", side_effect=lambda target, args=(), daemon=None: type("T", (), {"start": lambda self: target(*args)})()):
            framegrabber.schedule_video_prewarm(1)

        self.assertEqual(framegrabber.FRAME_CACHE[1]["0.000|0.000"], b"warm")

    def test_ensure_runtime_warmup_only_runs_once(self):
        with patch.object(framegrabber, "warm_runtime_dependencies") as warm_mock, \
             patch.object(framegrabber.threading, "Thread", side_effect=lambda target, args=(), daemon=None: type("T", (), {"start": lambda self: target(*args)})()):
            framegrabber.ensure_runtime_warmup()
            framegrabber.ensure_runtime_warmup()

        warm_mock.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_app -v`
Expected: FAIL because the warmup helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def warm_runtime_dependencies():
    subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)

def ensure_runtime_warmup():
    global RUNTIME_WARMUP_STARTED
    with STATE_LOCK:
        if RUNTIME_WARMUP_STARTED:
            return
        RUNTIME_WARMUP_STARTED = True
    threading.Thread(target=warm_runtime_dependencies, daemon=True).start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

### Task 2: Add a reusable preview renderer and per-video prewarm

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_frame_endpoint_uses_prewarmed_first_frame_cache(self):
        framegrabber.VIDEOS[1] = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 12.0,
            "fps": 24.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
        }
        framegrabber.FRAME_CACHE[1] = {"0.000|0.000": b"warm"}

        response = self.client.get("/api/frame?vid=1&t=0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"warm")
```

- [ ] **Step 2: Run test to verify it fails if cache wiring is wrong**

Run: `python3 -m unittest tests.test_app -v`
Expected: FAIL until the shared preview rendering/cache path is correct.

- [ ] **Step 3: Write minimal implementation**

```python
def render_preview_frame_bytes(v, t, exposure):
    ...

def maybe_cache_frame_bytes(vid, key, data):
    ...

def prewarm_video_preview(vid):
    data = render_preview_frame_bytes(VIDEOS[vid], 0.0, 0.0)
    maybe_cache_frame_bytes(vid, "0.000|0.000", data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

### Task 3: Add frontend tests for staged selection and source reuse

**Files:**
- Modify: `static/playback_scheduler.js`
- Modify: `tests/test_playback_scheduler.js`
- Modify: `static/index.html`

- [ ] **Step 1: Write the failing tests**

```javascript
test('selection plan prefers still preview while priming browser video', () => {
  const plan = getVideoSelectionPlan({ hasPreparedVideoSource: false });

  assert.deepEqual(plan, {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: true,
    shouldReloadPreparedSource: false,
  });
});

test('selection plan avoids reloading an already prepared video source', () => {
  const plan = getVideoSelectionPlan({ hasPreparedVideoSource: true });

  assert.deepEqual(plan, {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: false,
    shouldReloadPreparedSource: false,
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/test_playback_scheduler.js`
Expected: FAIL because staged selection planning does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```javascript
function getVideoSelectionPlan({ hasPreparedVideoSource }) {
  return {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: !hasPreparedVideoSource,
    shouldReloadPreparedSource: false,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/test_playback_scheduler.js`
Expected: PASS

- [ ] **Step 5: Update selection flow**

```javascript
const plan = getVideoSelectionPlan({ hasPreparedVideoSource: currentVideoSourceId === id });
if (plan.shouldPrimeVideoSource) {
  primePreviewVideo({ background: true });
}
if (plan.shouldLoadStillPreview) {
  seekTo(0, { skipPause: true });
}
```

- [ ] **Step 6: Run focused tests and manual smoke check**

Run: `node --test tests/test_playback_scheduler.js`
Expected: PASS

Manual:
- launch the app
- import a video
- confirm the first frame appears quickly
- press play and confirm playback starts without a visible extra reload

### Task 4: Run verification and document any residual risk

**Files:**
- Modify: `docs/superpowers/specs/2026-04-04-framegrabber-startup-load-performance-design.md`
- Modify: `docs/superpowers/plans/2026-04-04-framegrabber-startup-load-performance.md`

- [ ] **Step 1: Run backend tests**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

- [ ] **Step 2: Run frontend tests**

Run: `node --test tests/test_playback_scheduler.js`
Expected: PASS

- [ ] **Step 3: Re-read the design and plan for scope drift**

Expected:
- no UI changes beyond existing behavior
- no feature regressions introduced by warmup logic
- no placeholders remain in the docs
