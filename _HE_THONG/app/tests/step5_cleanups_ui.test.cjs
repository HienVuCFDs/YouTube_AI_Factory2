// Bước 05 · T7: in the plan workflow the cleanups go through the EditDocument. A scene it could not take them
// for is named in the message (an error, not a success) - never counted as covered.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = (name) => fs.readFileSync(path.join(__dirname, '../youtube_monitor/static', name), 'utf8');

function cleanupUi(answer) {
  const core = source('core.js');
  const lanes = source('studio-lanes.js');
  const messages = [];
  const calls = [];
  const sandbox = {
    state: {studioProjectId: 7}, messages,
    $: (id) => ({studioCleanupPosition: {value: 'top_right'}, studioCleanupMethod: {value: 'blur'}}[id] || null),
    setMessage: (text, type) => messages.push([text, type]),
    renderCleanupState: () => {},
    api: async (url, options) => { calls.push([url, JSON.parse(options.body)]); return answer; },
    esc: (value) => String(value),
  };
  vm.createContext(sandbox);
  vm.runInContext(core.slice(core.indexOf('  async function applyTimelineCleanup('), core.indexOf('  // Short is a checkbox')), sandbox);
  vm.runInContext(lanes.slice(lanes.indexOf('  async function detectTimelineCleanup('), lanes.indexOf('  const CLEANUP_KIND_LABELS')), sandbox);
  vm.runInContext(lanes.slice(lanes.indexOf('  function cleanupNotAppliedText('), lanes.indexOf('  function renderCleanupState(')), sandbox);
  return {sandbox, messages, calls};
}

test('every scene covered: the same success as before', async () => {
  const ui = cleanupUi({status: 'saved', segments: 5, cleanups: [{position: 'top_right', method: 'blur'}], not_applied: []});
  await ui.sandbox.applyTimelineCleanup(false);
  assert.deepEqual(ui.messages.at(-1), ['Đã đánh dấu che 5 cảnh. Render lại để áp dụng.', 'success']);
  assert.deepEqual(ui.calls, [['/api/projects/7/timeline/cleanups', {position: 'top_right', method: 'blur', clear: false}]]);
});

test('a scene the plan could not take them for is named, and the message is an error', async () => {
  const answer = {status: 'partial', segments: 4, cleanups: [{position: 'top_right', method: 'blur'}],
    not_applied: [{segment_id: 3, reason: 'Xung đột: hàng đang giữ chỉnh sửa ngoài kế hoạch dựng (edit_cleanups)'}]};
  for (const run of [(ui) => ui.sandbox.applyTimelineCleanup(false), (ui) => ui.sandbox.detectTimelineCleanup()]) {
    const ui = cleanupUi(answer);
    await run(ui);
    const [text, type] = ui.messages.at(-1);
    assert.equal(type, 'error');
    assert.match(text, /4 cảnh/);
    assert.match(text, /1 cảnh chưa che được \(Xung đột/);
  }
});

test('outside the plan workflow (no not_applied in the answer) nothing changes', async () => {
  const ui = cleanupUi({status: 'cleared', segments: 5, cleanups: [{kind: 'none', source: 'user_cleared'}]});
  await ui.sandbox.applyTimelineCleanup(true);
  assert.deepEqual(ui.messages.at(-1), ['Đã bỏ che trên 5 cảnh.', 'success']);
});
