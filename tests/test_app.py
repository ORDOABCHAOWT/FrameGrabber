import io
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import app as framegrabber


class FrameGrabberAppTests(unittest.TestCase):
    def setUp(self):
        self.client = framegrabber.app.test_client()
        self.original_videos = framegrabber.VIDEOS.copy()
        self.original_active = framegrabber.ACTIVE_ID
        self.original_next = framegrabber.NEXT_ID
        self.original_cache = framegrabber.FRAME_CACHE.copy()
        self.original_locks = framegrabber.FRAME_RENDER_LOCKS.copy()
        self.original_runtime_warmup_started = getattr(framegrabber, "RUNTIME_WARMUP_STARTED", False)
        self.original_video_prewarm_started = getattr(framegrabber, "VIDEO_PREWARM_STARTED", set()).copy()

        framegrabber.VIDEOS.clear()
        framegrabber.FRAME_CACHE.clear()
        framegrabber.FRAME_RENDER_LOCKS.clear()
        framegrabber.ACTIVE_ID = None
        framegrabber.NEXT_ID = 1
        if hasattr(framegrabber, "VIDEO_PREWARM_STARTED"):
            framegrabber.VIDEO_PREWARM_STARTED.clear()
        if hasattr(framegrabber, "RUNTIME_WARMUP_STARTED"):
            framegrabber.RUNTIME_WARMUP_STARTED = False

    def tearDown(self):
        framegrabber.VIDEOS.clear()
        framegrabber.VIDEOS.update(self.original_videos)
        framegrabber.FRAME_CACHE.clear()
        framegrabber.FRAME_CACHE.update(self.original_cache)
        framegrabber.FRAME_RENDER_LOCKS.clear()
        framegrabber.FRAME_RENDER_LOCKS.update(self.original_locks)
        framegrabber.ACTIVE_ID = self.original_active
        framegrabber.NEXT_ID = self.original_next
        if hasattr(framegrabber, "VIDEO_PREWARM_STARTED"):
            framegrabber.VIDEO_PREWARM_STARTED.clear()
            framegrabber.VIDEO_PREWARM_STARTED.update(self.original_video_prewarm_started)
        if hasattr(framegrabber, "RUNTIME_WARMUP_STARTED"):
            framegrabber.RUNTIME_WARMUP_STARTED = self.original_runtime_warmup_started

    def test_upload_endpoint_adds_dragged_video(self):
        fake_meta = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 12.5,
            "fps": 25.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
        }

        with patch.object(framegrabber, "probe_video", return_value=fake_meta), \
             patch.object(framegrabber, "generate_thumbnail"):
            response = self.client.post(
                "/api/upload",
                data={
                    "files": (io.BytesIO(b"fake-video-bytes"), "clip.mp4"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["active"], 1)
        self.assertEqual(len(data["added"]), 1)
        self.assertEqual(data["added"][0]["filename"], "clip.mp4")

    def test_video_endpoint_serves_selected_video(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

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

            response = self.client.get("/api/video?vid=1")

            self.assertEqual(response.status_code, 200)
            self.assertGreater(len(response.data), 0)
            response.close()
        finally:
            os.remove(temp_path)

    def test_select_video_schedules_prewarm_for_active_video(self):
        framegrabber.VIDEOS[1] = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 2.0,
            "fps": 24.0,
            "width": 640,
            "height": 360,
            "codec": "h264",
        }

        with patch.object(framegrabber, "schedule_video_prewarm") as prewarm_mock:
            response = self.client.post("/api/select", json={"id": 1})

        self.assertEqual(response.status_code, 200)
        prewarm_mock.assert_called_once_with(1)

    def test_schedule_video_prewarm_caches_neutral_first_frame_once(self):
        framegrabber.VIDEOS[1] = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 2.0,
            "fps": 24.0,
            "width": 640,
            "height": 360,
            "codec": "h264",
        }

        class InlineThread:
            def __init__(self, target=None, args=(), daemon=None, **kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with patch.object(framegrabber, "render_preview_frame_bytes", return_value=b"warm-jpeg") as render_mock, \
             patch.object(framegrabber.threading, "Thread", side_effect=InlineThread):
            framegrabber.schedule_video_prewarm(1)
            framegrabber.schedule_video_prewarm(1)

        self.assertEqual(framegrabber.FRAME_CACHE[1]["0.000|0.000"], b"warm-jpeg")
        render_mock.assert_called_once()

    def test_schedule_video_prewarm_retries_after_failed_warmup(self):
        framegrabber.VIDEOS[1] = {
            "path": "/tmp/clip.mp4",
            "filename": "clip.mp4",
            "duration": 2.0,
            "fps": 24.0,
            "width": 640,
            "height": 360,
            "codec": "h264",
        }

        class InlineThread:
            def __init__(self, target=None, args=(), daemon=None, **kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with patch.object(framegrabber, "render_preview_frame_bytes", side_effect=[None, b"warm-jpeg"]) as render_mock, \
             patch.object(framegrabber.threading, "Thread", side_effect=InlineThread):
            framegrabber.schedule_video_prewarm(1)
            framegrabber.schedule_video_prewarm(1)

        self.assertEqual(framegrabber.FRAME_CACHE[1]["0.000|0.000"], b"warm-jpeg")
        self.assertEqual(render_mock.call_count, 2)

    def test_frame_endpoint_passes_exposure_filter_to_ffmpeg(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

        preview_path = os.path.join(framegrabber.TEMP_DIR, "preview-test.jpg")

        def fake_mkstemp(prefix, suffix, dir):
            fd = os.open(preview_path, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o600)
            return fd, preview_path

        def fake_run(cmd, capture_output=True, timeout=10):
            vf_index = cmd.index("-vf") + 1
            self.assertIn("exposure=exposure=0.400", cmd[vf_index])
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

    def test_frame_cache_key_changes_with_exposure(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

        preview_path = os.path.join(framegrabber.TEMP_DIR, "preview-exposure-test.jpg")

        def fake_mkstemp(prefix, suffix, dir):
            fd = os.open(preview_path, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o600)
            return fd, preview_path

        def fake_run(cmd, capture_output=True, timeout=10):
            with open(preview_path, "wb") as fh:
                fh.write(b"adjusted")
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
            framegrabber.FRAME_CACHE[1] = {"0.500|0.000": b"plain"}

            with patch.object(framegrabber.tempfile, "mkstemp", side_effect=fake_mkstemp), \
                 patch.object(framegrabber.subprocess, "run", side_effect=fake_run):
                response = self.client.get("/api/frame?vid=1&t=0.500&exposure=0.5")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"adjusted")
            self.assertEqual(framegrabber.FRAME_CACHE[1]["0.500|0.000"], b"plain")
            self.assertEqual(framegrabber.FRAME_CACHE[1]["0.500|0.500"], b"adjusted")
        finally:
            if os.path.exists(preview_path):
                os.remove(preview_path)
            os.remove(temp_path)

    def test_grab_endpoint_passes_exposure_filter_to_ffmpeg(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(b"video-bytes")
            temp_path = handle.name

        save_dir = tempfile.mkdtemp()
        original_save_dir = framegrabber.SAVE_DIR

        def fake_run(cmd, capture_output=True, text=True, timeout=30):
            vf_index = cmd.index("-vf") + 1
            self.assertIn("exposure=exposure=-0.300", cmd[vf_index])
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

    def test_open_browser_when_ready_waits_for_server_listener(self):
        attempts = []

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_connect(address, timeout):
            attempts.append((address, timeout))
            if len(attempts) == 1:
                raise OSError("not ready")
            return _Conn()

        with patch.object(framegrabber.socket, "create_connection", side_effect=fake_connect), \
             patch.object(framegrabber.time, "sleep") as sleep_mock, \
             patch.object(framegrabber.webbrowser, "open") as open_mock:
            opened = framegrabber.open_browser_when_ready(9973, timeout=0.2, poll_interval=0.01)

        self.assertTrue(opened)
        open_mock.assert_called_once_with("http://localhost:9973")
        sleep_mock.assert_called_once()

    def test_open_browser_when_ready_gives_up_after_timeout(self):
        with patch.object(framegrabber.socket, "create_connection", side_effect=OSError("not ready")), \
             patch.object(framegrabber.time, "sleep"), \
             patch.object(framegrabber.webbrowser, "open") as open_mock:
            opened = framegrabber.open_browser_when_ready(9973, timeout=0.03, poll_interval=0.01)

        self.assertFalse(opened)
        open_mock.assert_not_called()

    def test_ensure_runtime_warmup_only_starts_once(self):
        warm_mock = Mock()

        class InlineThread:
            def __init__(self, target=None, args=(), daemon=None, **kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with patch.object(framegrabber, "warm_runtime_dependencies", warm_mock), \
             patch.object(framegrabber.threading, "Thread", side_effect=InlineThread):
            framegrabber.ensure_runtime_warmup()
            framegrabber.ensure_runtime_warmup()

        warm_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
