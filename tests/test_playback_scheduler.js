const test = require('node:test');
const assert = require('node:assert/strict');

const { getPreviewRequestPlan, getVideoSelectionPlan } = require('../static/playback_scheduler.js');

test('playback defers new preview requests while one is already in flight', () => {
  const plan = getPreviewRequestPlan({
    isDragging: false,
    isPlaying: true,
    hasPendingLoad: true,
  });

  assert.deepEqual(plan, {
    abortPending: false,
    defer: true,
    debounceMs: 0,
    shouldLoadPreview: true,
  });
});

test('manual seek still aborts stale preview requests to show latest frame first', () => {
  const plan = getPreviewRequestPlan({
    isDragging: false,
    isPlaying: false,
    hasPendingLoad: true,
  });

  assert.deepEqual(plan, {
    abortPending: true,
    defer: false,
    debounceMs: 30,
    shouldLoadPreview: true,
  });
});

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

test('selection plan primes browser video source while still loading the first still preview', () => {
  const plan = getVideoSelectionPlan({
    hasPreparedVideoSource: false,
  });

  assert.deepEqual(plan, {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: true,
    shouldReloadPreparedSource: false,
  });
});

test('selection plan avoids reloading when the correct video source is already primed', () => {
  const plan = getVideoSelectionPlan({
    hasPreparedVideoSource: true,
    hasVideoSourceError: false,
  });

  assert.deepEqual(plan, {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: false,
    shouldReloadPreparedSource: false,
  });
});

test('selection plan forces a source reload when the current prepared video source is in an error state', () => {
  const plan = getVideoSelectionPlan({
    hasPreparedVideoSource: true,
    hasVideoSourceError: true,
  });

  assert.deepEqual(plan, {
    shouldLoadStillPreview: true,
    shouldPrimeVideoSource: true,
    shouldReloadPreparedSource: true,
  });
});
