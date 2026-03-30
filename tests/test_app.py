import io
import os
import tempfile
import unittest
from unittest.mock import patch

import app as framegrabber


class FrameGrabberAppTests(unittest.TestCase):
    def setUp(self):
        self.client = framegrabber.app.test_client()
        self.original_videos = framegrabber.VIDEOS.copy()
        self.original_active = framegrabber.ACTIVE_ID
        self.original_next = framegrabber.NEXT_ID
        self.original_cache = framegrabber.FRAME_CACHE.copy()
        self.original_locks = framegrabber.FRAME_RENDER_LOCKS.copy()

        framegrabber.VIDEOS.clear()
        framegrabber.FRAME_CACHE.clear()
        framegrabber.FRAME_RENDER_LOCKS.clear()
        framegrabber.ACTIVE_ID = None
        framegrabber.NEXT_ID = 1

    def tearDown(self):
        framegrabber.VIDEOS.clear()
        framegrabber.VIDEOS.update(self.original_videos)
        framegrabber.FRAME_CACHE.clear()
        framegrabber.FRAME_CACHE.update(self.original_cache)
        framegrabber.FRAME_RENDER_LOCKS.clear()
        framegrabber.FRAME_RENDER_LOCKS.update(self.original_locks)
        framegrabber.ACTIVE_ID = self.original_active
        framegrabber.NEXT_ID = self.original_next

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


if __name__ == "__main__":
    unittest.main()
