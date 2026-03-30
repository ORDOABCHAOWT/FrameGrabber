# FrameGrabber Import And Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix drag-and-drop import so dropped videos always enter the app, and add play/pause preview controls so the user can stop on a frame and save it manually.

**Architecture:** Replace filename-based drag resolution with a real upload endpoint that stores dropped files in the app temp directory and reuses the existing metadata/indexing flow. Add a lightweight preview playback loop in the frontend that advances the current time and keeps using FFmpeg-backed frame extraction for broad codec support.

**Tech Stack:** Python, Flask, HTML/CSS/JavaScript, FFmpeg/ffprobe

---

### Task 1: Add regression tests for import and preview media access

**Files:**
- Create: `tests/test_app.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_upload_endpoint_adds_dragged_video(client):
    response = client.post('/api/upload', data={...}, content_type='multipart/form-data')
    assert response.status_code == 200

def test_video_endpoint_serves_selected_video(client):
    response = client.get('/api/video?vid=1')
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_app -v`
Expected: FAIL because `/api/upload` and `/api/video` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add:
- upload handling that persists dropped files into `TEMP_DIR/uploads`
- video streaming route for frontend playback support

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_app -v`
Expected: PASS

### Task 2: Replace drag-path guessing with direct upload

**Files:**
- Modify: `static/index.html`
- Modify: `app.py`

- [ ] **Step 1: Wire drag-drop to `FormData` upload**
- [ ] **Step 2: Keep progress/toast feedback during upload**
- [ ] **Step 3: Reuse `/api/add` response shape so list/selection UI stays stable**
- [ ] **Step 4: Verify a dropped file appears without the “无法自动定位文件” fallback**

### Task 3: Add preview play/pause controls

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add play/pause button and playback status text**
- [ ] **Step 2: Advance `currentTime` on a timer while playing and refresh preview frames**
- [ ] **Step 3: Pause automatically at the end or when the user scrubs**
- [ ] **Step 4: Verify paused time matches subsequent manual screenshot time**
