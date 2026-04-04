# FrameGrabber Startup And Load Performance Design

**Problem**

FrameGrabber currently feels slower than necessary in two moments that matter most to the user:

- app startup, where the local server, browser UI, and supporting resources all become ready at slightly different times
- first video selection, where the frontend immediately does both exact-frame preview work and browser video setup, while the backend still pays cold-start costs for FFmpeg-driven preview generation

The existing behavior is functionally correct, but the first visible result arrives later than it needs to, and the transition into playback is less smooth than it could be.

**Goals**

- Reduce perceived startup delay without changing the existing window, route, or interaction model.
- Make the first selected video show a usable preview faster.
- Reduce the delay before browser playback starts for a newly selected video.
- Keep current features and user experience intact.

**Non-Goals**

- Redesigning the UI or changing controls.
- Replacing FFmpeg or Flask.
- Changing screenshot output quality or saved file format.

**Design**

1. Add lightweight backend warmup after server start.
   - A background warmup thread runs after startup so the app can pay small one-time costs before the user selects a video.
   - Warmup is best-effort and silent. If it fails, the app behaves exactly as it does today.
   - The warmup should avoid heavy work and should not block the server from accepting requests.

2. Prewarm newly selected videos in the background.
   - When a video becomes active, the backend starts a best-effort prewarm for that specific file.
   - Prewarm prepares a small first-frame preview and nudges the decode path so the first user-visible frame request is more likely to hit a warm path.
   - This preview is cached under the normal frame cache key for time `0.000` and the current neutral exposure.

3. Split frontend video selection into staged loading.
   - On selection, the UI should prioritize the fastest visible still preview first.
   - Browser video source preparation should happen in parallel but should not delay the initial visible frame.
   - Once playback is requested, the video element should reuse the prepared source rather than restarting unnecessary work.

4. Remove avoidable frontend reload work.
   - Avoid redundant `video.load()` calls when the source is already correct.
   - Avoid forcing both preview modes to compete for attention before the user asks to play.
   - Keep the current play/pause/scrub behavior and exact paused preview logic.

**Data Flow**

- App launch:
  - Flask starts listening
  - browser opens as today
  - a background warmup thread performs lightweight server-side prewarming

- Video selection:
  - frontend immediately requests the paused preview frame for time `0`
  - frontend asynchronously prepares the browser video source
  - backend launches a best-effort active-video prewarm so the first preview and later playback are more likely to hit warm state

- Playback:
  - frontend reuses the prepared video source
  - timeline stays synced from `video.currentTime` as it does now
  - paused-state exact preview still comes from `/api/frame`

**Backend Changes**

- Add a small warmup coordinator for process startup.
- Add a best-effort per-video prewarm path that can generate and cache the neutral first frame.
- Reuse existing frame-cache semantics so the optimization does not change external API behavior.
- Keep all warmup work bounded and non-fatal.

**Frontend Changes**

- Add a background `primePreviewVideo` path during selection that does not block the first still frame.
- Avoid redundant source resets and `load()` churn.
- Preserve the current UI, controls, and user interactions.

**Testing**

- Backend tests should cover:
  - startup warmup is one-shot and non-blocking in behavior
  - active video prewarm populates the neutral first-frame cache only when appropriate
  - frame cache still serves the same `/api/frame` contract

- Frontend tests should cover:
  - selecting a video requests immediate still preview but does not force unnecessary video reloads
  - playback prep remains reusable once the source is primed

- Manual verification should confirm:
  - startup still opens the app normally
  - selecting a video shows the first frame faster
  - pressing play after selection starts faster or at least no slower
  - existing play, pause, scrub, exposure, and grab flows behave the same

**Risks**

- Background warmup can waste a small amount of work if the user closes the app immediately, so it must stay lightweight.
- Prewarming must not hold global locks long enough to delay real requests.
- Cached warmup frames must use the same keys as regular preview generation to avoid duplicate or stale entries.
