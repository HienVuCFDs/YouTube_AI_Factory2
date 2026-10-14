// Bước 05 · T9: two faults found in the browser on a test database, fixed and held here.
//   1. "Tạo lại storyboard" took the server's "stale" answer (it made nothing, it would lose voices) for a storyboard
//      and said it was made. Now it says what would happen, asks, and only then rebuilds (force); never called done.
//   2. Opening a project while the page was still restoring another wrote both into the same state: one project's
//      scenes under the other's id and plan. Loads now run one after another; the last one asked for stays.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = (name) => fs.readFileSync(path.join(__dirname, '../youtube_monitor/static', name), 'utf8');

function storyboardButton(answers, {agree = true} = {}) {
  const page = source('project-detail.js');
  const code = page.slice(page.indexOf('  async function generateStudioStoryboard('), page.indexOf('  async function saveStudioVoiceSettings('));
  const posts = [];
  const messages = [];
  const asked = [];
  const elements = {studioGenerateStoryboardButton: {disabled: false}, studioShotSummary: {textContent: ''}};
  const sandbox = {
    state: {studioProjectId: 7, timeline: []}, posts, messages, asked,
    $: (id) => elements[id] || null,
    api: async (url, options = {}) => {
      if (options.method === 'POST') { posts.push(JSON.parse(options.body)); return answers.shift(); }
      return {latest_timeline: []};
    },
    confirm: (text) => { asked.push(text); return agree; },
    setMessage: (text, type) => messages.push([text, type]),
    setStudioProgress: () => {}, renderStudioStoryboard: () => {}, updateStudioSceneGenerationAvailability: () => {},
    refreshStudioEditDocument: async () => {},
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox;
}

const STALE = {status: 'stale', stale: true, shots: [{}, {}], reconcile: {counts: {modified: 1, added: 0, removed: 0}, voice_invalidated: 1}};

test('a stale answer is never called a storyboard: the user is asked, and a refusal rebuilds nothing', async () => {
  const ui = storyboardButton([STALE], {agree: false});
  await ui.generateStudioStoryboard();
  assert.deepEqual(ui.posts, [{force: false}]);
  assert.equal(ui.asked.length, 1);
  assert.match(ui.asked[0], /1 đổi lời/);
  assert.match(ui.asked[0], /1 cảnh sẽ mất giọng/);
  const [text] = ui.messages.at(-1);
  assert.match(text, /Chưa dựng lại/);
  assert.doesNotMatch(text, /Đã tạo storyboard/);
});

test('agreed, it rebuilds with force and says when the plan now waits for a confirmation', async () => {
  const ui = storyboardButton([STALE, {status: 'saved', shots: [{}, {}, {}], edit_document: {status: 'needs_confirmation'}}]);
  await ui.generateStudioStoryboard();
  assert.deepEqual(ui.posts, [{force: false}, {force: true}]);
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'success');
  assert.match(text, /Đã tạo storyboard gồm 3 cảnh/);
  assert.match(text, /Áp dụng vào timeline/);
});

test('a storyboard that was current needs no question', async () => {
  const ui = storyboardButton([{status: 'unchanged', shots: [{}]}]);
  await ui.generateStudioStoryboard();
  assert.deepEqual(ui.posts, [{force: false}]);
  assert.equal(ui.asked.length, 0);
  assert.equal(ui.messages.at(-1)[1], 'success');
});

test('two project loads never interleave: the second waits for the first, with the video it was asked for', async () => {
  const lanes = source('studio-lanes.js');
  const at = lanes.indexOf('  let studioLoadChain = Promise.resolve();');
  const code = lanes.slice(at, lanes.indexOf('\n  }\n', lanes.indexOf('  function selectStudioVideo(', at)) + 4);
  const order = [];
  const pending = [];
  const select = {value: 'video-1'};
  const sandbox = {$: (id) => (id === 'studioVideoSelect' ? select : null), order,
    selectStudioVideoNow: (videoId, project) => new Promise((resolve) => {
      order.push(`start ${videoId}/${project}`);
      pending.push(() => { order.push(`end ${videoId}/${project}`); resolve(); });
    })};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const restoring = sandbox.selectStudioVideo(1);          // the page restoring the last session
  select.value = 'video-2';
  const opening = sandbox.selectStudioVideo(2);            // the user opening another project meanwhile
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(order, ['start video-1/1'], 'the second has not started');
  pending.shift()();
  await restoring;
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(order, ['start video-1/1', 'end video-1/1', 'start video-2/2']);
  pending.shift()();
  await opening;
  assert.equal(order.at(-1), 'end video-2/2', 'the last one asked for is the one that stays');
});

// 3. The render button held by the render gate said nothing: it now says why (title), and a press that gets
//    through still stops on the gate's reasons before anything is saved or sent.
function renderUi(check) {
  const page = source('project-detail.js');
  const code = page.slice(page.indexOf('  function renderStudioRenderReadiness('), page.indexOf('  async function refreshStudioRenderReadiness('))
    + page.slice(page.indexOf('  async function queueStudioRender('), page.indexOf('  async function watchStudioProductionJob('));
  const posts = [];
  const messages = [];
  const button = {disabled: false, title: '', dataset: {}};
  const elements = {studioQueueRenderButton: button, studioRenderReadinessNote: {className: '', innerHTML: ''},
    studioRenderSummary: null, studioRenderProviderSelect: {value: 'ffmpeg_builtin'}};
  const sandbox = {
    state: {studioProjectId: 7, productionQueue: {}}, posts, messages, button, saved: [],
    $: (id) => (id in elements ? elements[id] : null), esc: (value) => String(value),
    api: async (url, options = {}) => { if (options.method === 'POST') { posts.push(url); return {job: {id: 1}}; } return check; },
    confirm: () => true, setMessage: (text, type) => messages.push([text, type]), setStudioProgress: () => {},
    setStudioStep: () => {}, syncStudioRenderProvider: () => {}, watchStudioProductionJob: () => {},
  };
  sandbox.saveRenderSettings = async () => { sandbox.saved.push(true); };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox;
}

const HELD = {total: 2, missing_visual: 0, missing_audio: 0, draft_visual: 0, can_render: false,
  issues: ['Cảnh 1: lớp dựng được làm cho lời, chữ hoặc thời lượng cũ'],
  render_gate: [{code: 'stale_layers', detail: 'Cảnh 1: lớp dựng được làm cho lời, chữ hoặc thời lượng cũ', next_step: 'Lập lại kế hoạch dựng cho cảnh này ở Bước 5.'}]};

test('a render held by its gate is disabled and says why on the button', () => {
  const ui = renderUi(HELD);
  ui.renderStudioRenderReadiness(HELD);
  assert.equal(ui.button.disabled, true);
  assert.equal(ui.button.dataset.blocked, '1');
  assert.match(ui.button.title, /Chưa thể dựng: Cảnh 1: lớp dựng/);
  ui.renderStudioRenderReadiness({...HELD, can_render: true, issues: [], render_gate: []});
  assert.deepEqual([ui.button.disabled, ui.button.title, ui.button.dataset.blocked], [false, '', '0']);
});

test('a press that gets through stops on the gate, nothing saved, no job asked for', async () => {
  const ui = renderUi(HELD);
  await ui.queueStudioRender();
  assert.deepEqual(ui.posts, []);
  assert.deepEqual(ui.saved, [], 'the render settings are not saved for a render that will not run');
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /Chưa thể dựng: Cảnh 1: lớp dựng .* → Lập lại kế hoạch dựng/);
});

// 4. Cleanups kept in an edit plan nobody confirmed: the message and the state box say they wait, never "covered".
test('cleanups waiting for a confirmation are said to wait, never to cover', async () => {
  const core = source('core.js');
  const lanes = source('studio-lanes.js');
  const messages = [];
  const box = {innerHTML: ''};
  const sandbox = {
    state: {studioProjectId: 7}, messages,
    $: (id) => ({studioCleanupPosition: {value: 'top_right'}, studioCleanupMethod: {value: 'blur'}, studioCleanupState: box}[id] || null),
    setMessage: (text, type) => messages.push([text, type]), esc: (value) => String(value),
    api: async () => ({status: 'needs_confirmation', segments: 0, cleanups: [{position: 'top_right', method: 'blur'}],
      not_applied: [{segment_id: 1, reason: 'Đã ghi vào kế hoạch dựng; kế hoạch còn phần chưa xác nhận'}]}),
  };
  vm.createContext(sandbox);
  vm.runInContext(core.slice(core.indexOf('  async function applyTimelineCleanup('), core.indexOf('  // Short is a checkbox')), sandbox);
  vm.runInContext(lanes.slice(lanes.indexOf('  const CLEANUP_KIND_LABELS'), lanes.indexOf('  async function loadAutomationStatus(')), sandbox);
  await sandbox.applyTimelineCleanup(false);
  const [text] = messages.at(-1);
  assert.match(text, /chưa xác nhận/);
  assert.doesNotMatch(text, /Đã đánh dấu che/);
  assert.match(box.innerHTML, /Chờ xác nhận/);
  assert.doesNotMatch(box.innerHTML, /Đang che/);
});

// 5. The wording of the cleanups (T9e): "Bỏ che" names the scenes it could not uncover, and cleanups waiting for a
// confirmation name the scenes with layers made for other words they skipped - and what to do first.
function cleanupWording(answer) {
  const core = source('core.js');
  const lanes = source('studio-lanes.js');
  const messages = [];
  const box = {innerHTML: ''};
  const sandbox = {
    state: {studioProjectId: 7}, messages,
    $: (id) => ({studioCleanupPosition: {value: 'top_right'}, studioCleanupMethod: {value: 'blur'}, studioCleanupState: box}[id] || null),
    setMessage: (text, type) => messages.push([text, type]), esc: (value) => String(value),
    api: async () => answer,
  };
  vm.createContext(sandbox);
  vm.runInContext(core.slice(core.indexOf('  async function applyTimelineCleanup('), core.indexOf('  // Short is a checkbox')), sandbox);
  vm.runInContext(lanes.slice(lanes.indexOf('  async function detectTimelineCleanup('), lanes.indexOf('  async function loadAutomationStatus(')), sandbox);
  return {sandbox, messages};
}

const CONFLICT = {segment_id: 4, scene_key: 'k4', reason: 'Xung đột: hàng đang giữ chỉnh sửa ngoài kế hoạch dựng (edit_cleanups)'};
const STALE_SCENE = {segment_id: 9, scene_key: 'k9', code: 'stale_layers', scene_index: 3,
  reason: 'Cảnh có lớp dựng cũ (stale_content): lập lại kế hoạch cảnh này trước; chưa đổi gì'};
const WAITING = {segment_id: 1, scene_key: 'k1', reason: 'Đã ghi vào kế hoạch dựng; kế hoạch còn phần chưa xác nhận'};

test('"Bỏ che" names the scenes it could not uncover, "che" the ones it could not cover', async () => {
  const answer = {status: 'partial', segments: 4, cleanups: [{kind: 'none', source: 'user_cleared'}], not_applied: [CONFLICT]};
  const cleared = cleanupWording(answer);
  await cleared.sandbox.applyTimelineCleanup(true);
  const [text, type] = cleared.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /^Đã bỏ che trên 4 cảnh\. 1 cảnh chưa bỏ che được \(Xung đột/);
  assert.doesNotMatch(text, /chưa che được/);
  const covered = cleanupWording({...answer, cleanups: [{position: 'top_right', method: 'blur'}]});
  await covered.sandbox.applyTimelineCleanup(false);
  assert.match(covered.messages.at(-1)[0], /1 cảnh chưa che được \(Xung đột/);
});

test('cleanups waiting for a confirmation name the stale scenes they skip and what to do first', async () => {
  const answer = {status: 'needs_confirmation', segments: 0, cleanups: [{position: 'top_right', method: 'blur'}],
    not_applied: [WAITING, STALE_SCENE, {...STALE_SCENE, segment_id: 12, scene_key: 'k12', scene_index: 7}]};
  for (const [name, run] of [['cover', (ui) => ui.sandbox.applyTimelineCleanup(false)],
                             ['uncover', (ui) => ui.sandbox.applyTimelineCleanup(true)],
                             ['detect', (ui) => ui.sandbox.detectTimelineCleanup()]]) {
    const ui = cleanupWording(answer);
    await run(ui);
    const [text, type] = ui.messages.at(-1);
    assert.match(text, /chưa xác nhận/, name);
    assert.match(text, /Bỏ qua 2 cảnh có lớp dựng cũ \(Cảnh 3, 7\): lập lại kế hoạch các cảnh này trước\./, name);
    assert.equal(type, 'error', name);
  }
  const one = cleanupWording({...answer, not_applied: [WAITING, STALE_SCENE]});
  await one.sandbox.applyTimelineCleanup(false);
  assert.match(one.messages.at(-1)[0], /Bỏ qua 1 cảnh có lớp dựng cũ \(Cảnh 3\): lập lại kế hoạch cảnh này trước\./);
});

test('waiting for a confirmation with no stale scene: the message is as before', async () => {
  const ui = cleanupWording({status: 'needs_confirmation', segments: 0, cleanups: [{position: 'top_right', method: 'blur'}],
    not_applied: [WAITING]});
  await ui.sandbox.applyTimelineCleanup(false);
  const [text, type] = ui.messages.at(-1);
  assert.equal(text, 'Đã ghi vùng che vào kế hoạch dựng (chưa xác nhận): chưa đổi cảnh nào trên timeline. Bấm “Áp dụng vào timeline…” ở Bước 5 để áp.');
  assert.equal(type, '');
});
