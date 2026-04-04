# FrameGrabber Playback Sync And Exposure Design

**Problem**

Current preview playback advances the timeline on the frontend while preview frames are still fetched one-by-one from `/api/frame`. This makes the progress bar move at real time while the preview image updates only as fast as FFmpeg frame extraction can complete, so playback looks choppy and time display drifts ahead of the visible frame.

The app also lacks a way to adjust exposure before capture. The user needs a preview-time exposure control and wants the saved PNG to reflect the same exposure adjustment they saw before pressing capture.

**Goals**

- Keep playback preview visually synchronized with the progress bar and time display.
- Preserve precise paused/scrubbed frame preview and full-resolution screenshot capture.
- Add an exposure control that affects playback preview, paused preview, and saved screenshots consistently.

**Non-Goals**

- Color grading beyond a single exposure control.
- Reworking the broader layout or file import workflow.
- Replacing FFmpeg-based capture with browser-side canvas export.

**Design**

1. Playback preview uses a browser `video` element backed by `/api/video`.
   - During playback, the app shows the `video` element and derives the timeline/timecode from `video.currentTime`.
   - The manual timer that blindly advances `currentTime` is removed.
   - When playback pauses, ends, or the user scrubs, the app switches back to the existing image preview path so the visible frame remains tied to an exact requested timestamp.

2. Paused preview stays on `/api/frame`.
   - The preview `img` remains the source of truth for paused state, scrubbing, and frame stepping.
   - `/api/frame` accepts an `exposure` query parameter so paused preview matches the current playback look.
   - Frame cache keys include both timestamp and exposure so differently adjusted previews do not collide.

3. Exposure control is shared across all preview modes and capture.
   - The UI adds an exposure slider with a numeric readout and reset button.
   - The `video` and `img` previews both apply the same CSS `filter: brightness(...)` transform for immediate visual feedback.
   - `/api/grab` accepts an `exposure` value and maps it to an FFmpeg filter so the saved PNG matches the adjusted preview.
   - The same exposure parameter is also passed to `/api/frame`, allowing the paused preview and saved output to remain consistent even after play/pause transitions.

**Data Flow**

- Play:
  - frontend sets `video.src` to `/api/video?vid=...`
  - user presses play
  - `video` becomes visible, `img` hides
  - `timeupdate` / `requestAnimationFrame` syncs timeline UI from `video.currentTime`

- Pause or seek:
  - frontend pauses `video`
  - frontend updates `currentTime`
  - frontend requests `/api/frame?vid=...&t=...&exposure=...`
  - returned JPEG becomes the visible paused preview

- Capture:
  - frontend posts `{ vid, time, exposure }` to `/api/grab`
  - backend runs FFmpeg with the requested timestamp and exposure filter
  - saved PNG reflects the adjusted exposure

**Backend Changes**

- Extend `/api/frame` to parse `exposure`, add it to cache keys, and apply an FFmpeg exposure filter before the preview JPEG is written.
- Extend `/api/grab` to parse `exposure` and apply the same exposure filter before saving the PNG.
- Keep `/api/video` unchanged aside from continuing to serve the original file for browser playback.

**Frontend Changes**

- Add a `video` element alongside the existing `img` element inside the preview area.
- Replace timer-driven playback progression with `video` event-driven UI updates.
- Keep the existing frame request scheduler only for paused preview and scrubbing.
- Add exposure slider UI and ensure both preview elements receive the same computed visual filter.

**Testing**

- Backend unit tests verify `/api/frame` and `/api/grab` pass exposure through to FFmpeg filters.
- Frontend scheduler tests verify playback mode no longer relies on the old deferred JPG playback path for time progression decisions.
- Manual verification confirms:
  - progress bar and visible picture stay aligned during playback
  - pausing lands on the expected frame
  - exposure adjustments are visible before capture
  - saved PNG matches the adjusted preview

**Risks**

- Browser-decoded playback and FFmpeg-decoded paused frames may differ slightly on some codecs; the design minimizes this by switching to FFmpeg-backed exact preview when playback stops.
- CSS brightness and FFmpeg exposure are not numerically identical. The implementation should choose a simple shared mapping and keep UI wording centered on “曝光调整” rather than promising exact photometric equivalence.
