// Bước 5 · Storyboard & Edit, run for real: the EditDocument block of
// project-detail.js and the storyboard buttons that lead to it, against a
// scripted server. A planned project's edit is planned by one POST to
// …/steps/edit_plan (never the legacy Edit Plan or edit-beats writers), is
// applied only when the user confirms it (confirmed_apply), and each scene
// shows what GET …/edit-document says - never "done" for an HTTP 200 alone.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/project-detail.js'), 'utf8');
const START = '  // ---- Bước 5 · EditDocument ----';
const END = '  // ---- hết Bước 5 · EditDocument ----';
const block = page.slice(page.indexOf(START), page.indexOf(END));

// One top-level function of the page, as written there.
function fn(name) {
  const at = [`  async function ${name}(`, `  function ${name}(`].map((head) => page.indexOf(head)).find((index) => index >= 0);
  assert.ok(at >= 0, `no function ${name}`);
  return page.slice(at, page.indexOf('\n  }\n', at) + 4);
}
const FUNCTIONS = ['storyboardEditSummary', 'legacyStoryboardEditSummary', 'editBeatsForSegment', 'editBeatSelect',
  'planStudioSceneEdit', 'planAllStudioSceneEdits', 'applyAllStudioSceneEdits', 'planStudioGraphics',
  'applyStudioGraphics', 'renderStudioGraphicPlan', 'refreshStudioStoryboard', 'rebuildStoryboardFromScript'];
const code = block + FUNCTIONS.map(fn).join('\n');

const P = 7;
const ROWS = [{id: 31, segment_index: 1, overlays: '[{"text":"Ý chính"}]'}, {id: 32, segment_index: 2, overlays: '[]'},
  {id: 33, segment_index: 3, overlays: '[]'}];
const scene = (segment_id, status, applied = null, key = `sk-${segment_id}`) => ({scene_key: key, segment_id, status, applied});
const DOC = (over = {}) => ({project_id: P, mode: 'plan', gate: 'current', state: 'current', document_hash: 'h1',
  counts: {scenes: 3, planned: 2, applied: 1, needs_plan: 1, stale: 0},
  scenes: [scene(31, 'ready', 'applied'), scene(32, 'ready', 'not_applied'), scene(33, 'needs_plan')], ...over});
const LEGACY = {project_id: P, mode: 'legacy', gate: 'not_applicable', state: 'not_applicable', scenes: []};

function studio({doc = DOC(), plan, confirms = true, docFails = false} = {}) {
  const server = {doc, plan: plan || (() => ({status: 'planned', planned: ['sk-33'], wanted: ['sk-33'], problems: {}}))};
  const calls = [];
  const messages = [];
  const cells = [];
  const elements = {studioEditPlanState: {innerHTML: ''}, studioGraphicPlanState: {innerHTML: '', textContent: ''},
    studioBuildEditPlanButton: {disabled: false}, studioApplyEditPlanToScenesButton: {disabled: false}};
  const asked = [];
  const sandbox = {
    state: {studioProjectId: P, timeline: ROWS, shots: []},
    $: (id) => elements[id] || null,
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      calls.push({url, method, body: options.body ? JSON.parse(options.body) : null});
      if (url === `/api/projects/${P}/edit-document`) {
        if (docFails) { const error = new Error('máy chủ lỗi'); error.status = 500; throw error; }
        return server.doc;
      }
      if (method === 'POST' && url === `/api/projects/${P}/steps/edit_plan`) {
        return {step: 'edit_plan', result: await server.plan(calls.at(-1).body)};
      }
      if (url === `/api/projects/${P}`) return {project: {id: P}, latest_shots: [], latest_timeline: ROWS};
      if (method === 'POST' && url.endsWith('/timeline/reattach-voice')) return {attached: 2};
      if (method === 'POST') return {};
      if (method === 'GET' && url.endsWith('/edit-plan')) return {status: 'draft'};
      throw new Error(`unexpected ${method} ${url}`);
    },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    confirm: (text) => { asked.push(text); return confirms; },
    // The storyboard is drawn as the page draws it: one edit cell per row, which the EditDocument read fills in.
    renderStudioStoryboard: (shots, timeline) => {
      sandbox.state.timeline = timeline;
      cells.length = 0;
      for (const segment of timeline) {
        const html = sandbox.storyboardEditSummary(segment);
        cells.push({dataset: {editDocSegment: String(segment.id)}, innerHTML: html.replace(/^<div[^>]*>|<\/div>$/g, '')});
      }
      sandbox.state.studioEditDocumentLoad = sandbox.refreshStudioEditDocument();
    },
    document: {querySelectorAll: (selector) => (selector.includes('data-edit-doc-segment') ? cells : []),
      querySelector: () => null},
    setStudioProgress() {}, resolveAutoSceneProvider: async (value) => value, sidecarWarningText: async () => '',
    applyStudioSceneEdit: async (id) => { calls.push({url: `/legacy/apply/${id}`, method: 'POST', body: null}); return {jobs: []}; },
    narrationSourceNotice: () => '',
    Promise, JSON, Math, Number, String, Object, Array, Boolean, Error,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const posts = () => calls.filter((call) => call.method !== 'GET');
  const cell = (id) => (cells.find((item) => item.dataset.editDocSegment === String(id)) || {}).innerHTML || '';
  return {sandbox, server, calls, posts, messages, asked, elements, cells, cell};
}

const nothingLegacy = (calls) => {
  for (const call of calls) {
    assert.ok(!/\/edit-plan(\/|$)/.test(call.url), `legacy Edit Plan called: ${call.method} ${call.url}`);
    assert.ok(!call.url.includes('/edit-beats'), `legacy edit-beats called: ${call.method} ${call.url}`);
    assert.ok(!call.url.startsWith('/legacy/'), `legacy apply called: ${call.url}`);
  }
};

// ---------------------------------------------------------------------------
// Planning goes to the step; applying only when the user confirms
// ---------------------------------------------------------------------------

test('"1. Lập kế hoạch dựng" on a planned project is one POST to steps/edit_plan, without confirmed_apply', async () => {
  const ui = studio();
  await ui.sandbox.planAllStudioSceneEdits();
  assert.deepEqual(ui.posts().map((call) => [call.url, call.body]), [[`/api/projects/${P}/steps/edit_plan`, {options: {}}]]);
  nothingLegacy(ui.calls);
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'success');
  assert.match(text, /Đã lập kế hoạch dựng cho 1 cảnh\./);
  assert.match(text, /Chưa áp vào timeline/, 'planning is not applying');
  assert.match(text, /lần dựng lại storyboard\/timeline kế tiếp cũng sẽ tự áp/, 'T4 applying on the next sync is said, not hidden');
});

test('"Lập kế hoạch" (overall plan) on a planned project never calls the legacy Edit Plan', async () => {
  const ui = studio();
  await ui.sandbox.planStudioGraphics();
  assert.deepEqual(ui.posts().map((call) => call.url), [`/api/projects/${P}/steps/edit_plan`]);
  assert.deepEqual(ui.posts()[0].body, {options: {}});
  nothingLegacy(ui.calls);
});

test('both apply buttons send confirmed_apply only after the user confirms', async () => {
  for (const button of ['applyAllStudioSceneEdits', 'applyStudioGraphics']) {
    const ui = studio({plan: () => ({status: 'unchanged', planned: [], wanted: [], problems: {},
      applied: {status: 'applied', counts: {applied: 2, unchanged: 0, conflicts: 0, skipped: {}}}})});
    await ui.sandbox[button]();
    assert.deepEqual(ui.posts().map((call) => [call.url, call.body]),
      [[`/api/projects/${P}/steps/edit_plan`, {options: {confirmed_apply: true}}]], button);
    assert.equal(ui.asked.length, 1, 'asked first');
    assert.deepEqual(ui.messages.at(-1), ['Không có cảnh nào cần lập: các cảnh đều đã có kế hoạch dựng hiện hành. Đã áp 2 cảnh vào timeline.', 'success']);
    nothingLegacy(ui.calls);
  }
});

test('a refused confirmation sends nothing - for planning and for applying', async () => {
  for (const button of ['planAllStudioSceneEdits', 'applyAllStudioSceneEdits', 'planStudioGraphics', 'applyStudioGraphics']) {
    const ui = studio({confirms: false});
    await ui.sandbox[button]();
    assert.equal(ui.posts().length, 0, button);
  }
});

test("a scene's own button plans that scene alone, again, by its scene_key", async () => {
  const ui = studio();
  await ui.sandbox.refreshStudioEditDocument();
  await ui.sandbox.planStudioSceneEdit(32);
  assert.deepEqual(ui.posts().map((call) => call.body), [{options: {scene_keys: ['sk-32'], replan: true}}]);
  nothingLegacy(ui.calls);
});

test('a scene the current EditDocument does not hold is not planned on a guess', async () => {
  const ui = studio({doc: DOC({state: 'outdated', scenes: []})});
  await ui.sandbox.planStudioSceneEdit(32);
  assert.equal(ui.posts().length, 0);
  assert.equal(ui.messages.at(-1)[1], 'error');
});

test('when the EditDocument cannot be read, nothing is planned at all - not even the legacy way', async () => {
  const ui = studio({docFails: true});
  for (const button of ['planAllStudioSceneEdits', 'applyAllStudioSceneEdits', 'planStudioGraphics', 'applyStudioGraphics']) {
    await ui.sandbox[button]();
  }
  assert.equal(ui.posts().length, 0);
  assert.match(ui.messages.at(-1)[0], /Không đọc được trạng thái kế hoạch dựng: máy chủ lỗi/);
  assert.equal(ui.messages.at(-1)[1], 'error');
});

test('a project outside the plan workflow keeps the legacy per-scene planner', async () => {
  const ui = studio({doc: LEGACY});
  await ui.sandbox.planAllStudioSceneEdits();
  const posts = ui.posts().map((call) => call.url);
  assert.deepEqual(posts, ROWS.map((row) => `/api/timeline/${row.id}/edit-beats/plan`));
  assert.ok(!posts.some((url) => url.endsWith('/steps/edit_plan')));
});

// ---------------------------------------------------------------------------
// What the server answered, never success for a 200 alone
// ---------------------------------------------------------------------------

const ANSWERS = {
  unchanged: [{status: 'unchanged', planned: [], wanted: []}, /Không có cảnh nào cần lập/, ''],
  not_current: [{status: 'not_current', detail: 'Storyboard hoặc kịch bản không phải bản hiện hành: chưa lập kế hoạch dựng'},
    /Chưa lập kế hoạch dựng: Storyboard hoặc kịch bản không phải bản hiện hành.*Hãy dựng lại storyboard trước\./, 'error'],
  needs_rebuild: [{status: 'needs_rebuild', voice_outdated: 2, detail: 'Có giọng làm với cấu hình cũ'}, /Có giọng làm với cấu hình cũ/, 'error'],
  partial: [{status: 'partial', planned: ['sk-31'], wanted: ['sk-31', 'sk-33'], problems: {'sk-33': 'AI không trả kế hoạch cho cảnh này'}},
    /Chỉ lập được 1\/2 cảnh\. Chưa lập: sk-33: AI không trả kế hoạch cho cảnh này/, 'error'],
  blocked: [{status: 'blocked', planned: [], wanted: ['sk-33'], problems: {'sk-33': 'Lớp dựng không vừa cảnh'}},
    /Không lập được cảnh nào: sk-33: Lớp dựng không vừa cảnh/, 'error'],
  error: [{status: 'error', planned: [], planner_error: 'model down'}, /Lập kế hoạch dựng lỗi: model down/, 'error'],
  not_applicable: [{status: 'not_applicable'}, /không thuộc luồng Kế hoạch/, 'error'],
  empty: [{}, /trạng thái không rõ \(trống\): không coi là đã lập/, 'error'],
  odd: [{status: 'done'}, /trạng thái không rõ \(done\)/, 'error'],
};

for (const [name, [answer, words, type]] of Object.entries(ANSWERS)) {
  test(`the step answering ${name} is shown as it is (${type || 'neutral'}), never as success`, async () => {
    const ui = studio({plan: () => answer});
    await ui.sandbox.planAllStudioSceneEdits();
    const [text, said] = ui.messages.at(-1);
    assert.match(text, words);
    assert.equal(said, type);
    assert.doesNotMatch(text, /Chưa áp vào timeline/, 'nothing planned, nothing to apply');
  });
}

test('applying that the server reports partial, blocked or not current is an error even when planning went fine', async () => {
  const cases = {
    partial: [{status: 'partial', counts: {applied: 1, conflicts: 1, skipped: {stale: 1}}}, /Chỉ áp được 1 cảnh; 1 cảnh xung đột .*1 cảnh bỏ qua/],
    blocked: [{status: 'blocked', counts: {applied: 0, conflicts: 2, skipped: {}}}, /Không áp được cảnh nào: 2 cảnh xung đột/],
    not_current: [{status: 'not_current', detail: 'Storyboard của kịch bản này không phải bản hiện hành'}, /Chưa áp: Storyboard của kịch bản/],
    no_document: [{status: 'no_document'}, /Chưa áp: dự án chưa có EditDocument/],
    error: [{status: 'error', detail: 'EditDocument hỏng'}, /Áp kế hoạch dựng lỗi: EditDocument hỏng/],
    missing: [undefined, /Chưa áp: máy chủ không báo kết quả áp/],
  };
  for (const [name, [applied, words]] of Object.entries(cases)) {
    const ui = studio({plan: () => ({status: 'planned', planned: ['sk-33'], wanted: ['sk-33'], problems: {}, applied})});
    await ui.sandbox.applyAllStudioSceneEdits();
    const [text, type] = ui.messages.at(-1);
    assert.match(text, words, name);
    assert.equal(type, 'error', name);
  }
});

test('a failed request is reported in its own words', async () => {
  const ui = studio({plan: () => { const error = new Error('Bước Storyboard chưa xong'); error.status = 409; throw error; }});
  await ui.sandbox.planAllStudioSceneEdits();
  assert.deepEqual(ui.messages.at(-1), ['Không lập được kế hoạch dựng: Bước Storyboard chưa xong', 'error']);
});

test('a second click while planning runs sends nothing', async () => {
  let release;
  const ui = studio();
  ui.server.plan = () => new Promise((resolve) => { release = resolve; });
  const first = ui.sandbox.runStudioEditDocumentPlan({});
  await new Promise((resolve) => setImmediate(resolve));
  await ui.sandbox.runStudioEditDocumentPlan({});
  assert.equal(ui.posts().length, 1);
  release({status: 'unchanged', planned: [], wanted: []});
  await first;
});

// ---------------------------------------------------------------------------
// Each scene shows the EditDocument's word for it
// ---------------------------------------------------------------------------

test('each card says what the EditDocument holds: planned and applied, planned not applied, not planned', async () => {
  const ui = studio({doc: DOC({scenes: [scene(31, 'ready', 'applied'), scene(32, 'ready', 'older'), scene(33, 'needs_plan')]})});
  await ui.sandbox.refreshStudioStoryboard();
  assert.match(ui.cell(31), /Kế hoạch dựng:<\/b> đã lập · đã áp vào timeline\./);
  assert.match(ui.cell(32), /đã lập · timeline còn bản cũ, chưa áp bản mới/);
  assert.match(ui.cell(33), /Kế hoạch dựng:<\/b> chưa lập\./);
  assert.match(ui.cell(31), /onclick="planStudioSceneEdit\(31\)">Lập lại cảnh này</);
  assert.match(ui.cell(33), /onclick="planStudioSceneEdit\(33\)">Lập kế hoạch cảnh này</);
  assert.match(ui.elements.studioEditPlanState.innerHTML, /2\/3 cảnh đã lập · 1 đã áp · 1 chưa lập · 0 cũ\./);
  assert.match(ui.elements.studioEditPlanState.innerHTML, /1 cảnh đã lập chưa áp/);
});

test('a planned scene is never shown "chưa lập" for lack of edit beats, and overlays alone never make it "đã lập"', async () => {
  const ui = studio({doc: DOC({scenes: [scene(31, 'needs_plan'), scene(32, 'ready', 'not_applied'), scene(33, 'needs_plan')]})});
  await ui.sandbox.refreshStudioStoryboard();
  // Row 31 has an overlay on the timeline, yet the EditDocument has no edit for it.
  assert.match(ui.cell(31), /chưa lập/);
  assert.doesNotMatch(ui.cell(31), /đã lập/);
  // Row 32 has no edit beats, yet its edit is planned.
  assert.match(ui.cell(32), /đã lập · chưa áp vào timeline/);
  assert.doesNotMatch(ui.cell(32), /chưa lập/);
});

test('stale, review, missing, outdated and unreadable documents each say so', async () => {
  const stale = studio({doc: DOC({scenes: [scene(31, 'stale_content'), scene(32, 'stale_timing'), scene(33, 'visual_review', 'applied')]})});
  await stale.sandbox.refreshStudioStoryboard();
  assert.match(stale.cell(31), /cũ: lời cảnh đã đổi, cần lập lại/);
  assert.match(stale.cell(32), /cũ: thời lượng đổi, cần lập lại/);
  assert.match(stale.cell(33), /đã lập · cần xem lại hình · đã áp vào timeline/);
  const missing = studio({doc: DOC({state: 'missing', scenes: [], counts: undefined})});
  await missing.sandbox.refreshStudioStoryboard();
  assert.match(missing.cell(31), /chưa lập \(chưa có EditDocument\)/);
  assert.match(missing.elements.studioEditPlanState.innerHTML, /Chưa lập kế hoạch dựng\./);
  const outdated = studio({doc: DOC({state: 'outdated', scenes: [], gate: 'stale'})});
  await outdated.sandbox.refreshStudioStoryboard();
  assert.match(outdated.cell(31), /EditDocument thuộc storyboard trước/);
  assert.match(outdated.elements.studioEditPlanState.innerHTML, /Storyboard chưa ở trạng thái hiện hành \(stale\)/);
  const broken = studio({doc: DOC({state: 'error', detail: 'Bản ghi áp #3 không đọc được', scenes: []})});
  await broken.sandbox.refreshStudioStoryboard();
  assert.match(broken.cell(31), /không đọc được EditDocument: Bản ghi áp #3 không đọc được/);
});

test('a legacy project keeps the legacy edit summary on its cards', async () => {
  const ui = studio({doc: LEGACY});
  await ui.sandbox.refreshStudioStoryboard();
  assert.match(ui.cell(31), /Kế hoạch dựng:<\/b> chưa lập\. <button class="btn small ghost" type="button" onclick="planStudioSceneEdit\(31\)">Lập kế hoạch cảnh này/);
  assert.equal(ui.elements.studioEditPlanState.innerHTML, '', 'the legacy state box is left as the legacy planner keeps it');
});

test("another project's EditDocument is never drawn on this one", async () => {
  const ui = studio({doc: DOC({project_id: 99})});
  await ui.sandbox.refreshStudioStoryboard();
  assert.equal(ui.sandbox.studioEditFlow(), null);
  assert.doesNotMatch(ui.cell(31), /đã áp vào timeline/);
});

// ---------------------------------------------------------------------------
// Rebuilding the storyboard forces it, in the body the routes read
// ---------------------------------------------------------------------------

test('"Dựng lại storyboard từ kịch bản" sends force in the JSON body, never the query string', async () => {
  const ui = studio();
  await ui.sandbox.rebuildStoryboardFromScript();
  const posts = ui.posts();
  assert.deepEqual(posts.slice(0, 2).map((call) => [call.url, call.body]), [
    [`/api/projects/${P}/shots/generate`, {force: true}],
    [`/api/projects/${P}/timeline/generate`, {force: true}],
  ]);
  assert.ok(posts.every((call) => !call.url.includes('?')), 'no query string');
});

test('a refused rebuild sends nothing', async () => {
  const ui = studio({confirms: false});
  await ui.sandbox.rebuildStoryboardFromScript();
  assert.equal(ui.posts().length, 0);
});
