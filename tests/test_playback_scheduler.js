const test = require('node:test');
const assert = require('node:assert/strict');

const { getPreviewRequestPlan } = require('../static/playback_scheduler.js');

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
  });
});
