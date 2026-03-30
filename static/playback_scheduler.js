(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.FrameGrabberPlaybackScheduler = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  function getPreviewRequestPlan({ isDragging, isPlaying, hasPendingLoad }) {
    if (isPlaying && hasPendingLoad) {
      return {
        abortPending: false,
        defer: true,
        debounceMs: 0,
      };
    }

    return {
      abortPending: hasPendingLoad,
      defer: false,
      debounceMs: isDragging ? 100 : 30,
    };
  }

  return {
    getPreviewRequestPlan,
  };
});
