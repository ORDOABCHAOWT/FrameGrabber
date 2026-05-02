(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.FrameGrabberPlaybackScheduler = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
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

  function getVideoSelectionPlan({ hasPreparedVideoSource, hasVideoSourceError = false }) {
    const shouldReloadPreparedSource = hasPreparedVideoSource && hasVideoSourceError;
    return {
      shouldLoadStillPreview: true,
      shouldPrimeVideoSource: !hasPreparedVideoSource || shouldReloadPreparedSource,
      shouldReloadPreparedSource,
    };
  }

  function getCaptureTime({ currentTime, previewVideoTime, isPlaying = false }) {
    if (isPlaying && Number.isFinite(previewVideoTime)) {
      return previewVideoTime;
    }
    if (Number.isFinite(currentTime)) {
      return currentTime;
    }
    return 0;
  }

  return {
    getPreviewRequestPlan,
    getVideoSelectionPlan,
    getCaptureTime,
  };
});
