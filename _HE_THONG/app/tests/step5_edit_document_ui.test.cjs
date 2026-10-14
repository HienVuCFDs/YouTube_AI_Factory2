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
  assert.match(text, /không tự áp kế hoạch chưa xác nhận/, 'T4 phương án B: only a confirmed version is applied, and the page says so');
});

test('"Lập kế hoạch" (overall plan) on a planned project never calls the legacy Edit Plan', async () => {
  const ui = studio();
  await ui.sandbox.planStudioGraphics();
  assert.deepEqual(ui.posts().map((call) => call.url), [`/api/projects/${P}/steps/edit_plan`]);
  assert.deepEqual(ui.posts()[0].body, {options: {}});
  nothingLegacy(ui.calls);
});

test('both apply buttons confirm the version shown (its document_hash), only after the user confirms', async () => {
  for (const button of ['applyAllStudioSceneEdits', 'applyStudioGraphics']) {
    const ui = studio({plan: () => ({status: 'unchanged', planned: [], wanted: [], problems: {},
      applied: {status: 'applied', counts: {applied: 2, unchanged: 0, conflicts: 0, skipped: {}}}})});
    await ui.sandbox[button]();
    assert.deepEqual(ui.posts().map((call) => [call.url, call.body]),
      [[`/api/projects/${P}/steps/edit_plan`, {options: {confirmed_apply: true, document_hash: 'h1'}}]], button);
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
  assert.match(ui.elements.studioEditPlanState.innerHTML, /2\/3 cảnh đã lập · 1 đã áp · 1 chưa lập · 0 cũ · .*chưa xác nhận.*\./);
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

test('F3: a read the server worked out from the timeline now (fresh false) says so; the scenes are shown as it answered', async () => {
  const ui = studio({doc: DOC({fresh: false, document_hash: 'h2', stored_document_hash: 'h1',
    counts: {scenes: 3, planned: 2, applied: 0, needs_plan: 1, stale: 0},
    scenes: [scene(31, 'ready', 'older'), scene(32, 'ready', 'not_applied'), scene(33, 'needs_plan')]})});
  await ui.sandbox.refreshStudioStoryboard();
  assert.match(ui.cell(31), /đã lập · timeline còn bản cũ, chưa áp bản mới/, 'the row whose length changed no longer reads "đã áp"');
  const head = ui.elements.studioEditPlanState.innerHTML;
  assert.match(head, /2\/3 cảnh đã lập · 0 đã áp/);
  assert.match(head, /data-edit-doc-fresh="false"/);
  assert.match(head, /Thời lượng hoặc giọng đọc của cảnh đã đổi sau lần lưu kế hoạch gần nhất/);
  assert.equal(ui.posts().length, 0, 'reading the state sends nothing');
});

test('F3: a read that could not be checked against the timeline (fresh null) names why; a fresh read adds nothing', async () => {
  const unknown = studio({doc: DOC({fresh: null, fresh_detail: 'Timeline chưa khớp <Storyboard>'})});
  await unknown.sandbox.refreshStudioStoryboard();
  const head = unknown.elements.studioEditPlanState.innerHTML;
  assert.match(head, /data-edit-doc-fresh="unknown"/);
  assert.match(head, /Chưa kiểm được kế hoạch dựng có theo kịp timeline hiện tại không: Timeline chưa khớp &lt;Storyboard&gt;/);
  for (const doc of [DOC({fresh: true}), DOC()]) {
    const ui = studio({doc});
    await ui.sandbox.refreshStudioStoryboard();
    assert.doesNotMatch(ui.elements.studioEditPlanState.innerHTML, /data-edit-doc-fresh/);
  }
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

// ---------------------------------------------------------------------------
// T6a · a hand edit of one scene's layers goes to the EditDocument in the plan
// workflow (one PUT …/edit-document/scenes/{scene_key}), never straight to the
// timeline; the legacy workflow keeps its timeline routes.
// ---------------------------------------------------------------------------

const SCENE_FUNCTIONS = ['storyboardEditSummary', 'legacyStoryboardEditSummary', 'editBeatsForSegment', 'editBeatSelect',
  'refreshStudioStoryboard', 'collectStudioSceneEditBeats', 'saveStudioSceneEditPlan', 'applyStudioSceneEdit',
  'parseSceneJsonField', 'editStudioSceneJsonLayer', 'editStudioSceneOverlays', 'editStudioSceneSoundCues'];
const sceneCode = block + SCENE_FUNCTIONS.map(fn).join('\n');
const BEAT = {id: 501, beat_index: 1, source_kind: 'primary', duration_seconds: 2, effect: 'static', transition: 'cut', prompt: 'A'};
const SCENE_ROWS = [{id: 31, segment_index: 1, overlays: '[]', sound_cues: '[]', visual_path: '/p/a.png', edit_beats: [BEAT]},
  {id: 32, segment_index: 2, overlays: '[]', sound_cues: '[]', visual_path: '', edit_beats: []}];
const APPLIED = {status: 'applied', counts: {applied: 1, unchanged: 0, conflicts: 0, skipped: {}}, applied: [{segment_id: 31}],
  conflicts: [], skipped: []};
const HAND = '[{"kind":"text","text":"Chữ tay","start_seconds":0,"end_seconds":1}]';

function sceneStudio({doc = DOC(), put = () => APPLIED, prompt = HAND, docFails = false, reloadFails = false,
  resolve = () => ({status: 'applied'}), confirms = true} = {}) {
  const calls = [];
  const messages = [];
  const asked = [];
  // One row of the scene's beat editor, as the page reads it back.
  const values = {'.beat-source': 'primary', '.beat-duration': '2', '.beat-effect': 'zoom_in', '.beat-transition': 'fade',
    '.beat-prompt': 'nhịp tay'};
  const host = {querySelectorAll: () => [{dataset: {assetId: '', visualPath: ''}, querySelector: (selector) => ({value: values[selector]})}]};
  const sandbox = {
    state: {studioProjectId: P, timeline: SCENE_ROWS, shots: []},
    $: () => null,
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({url, method, body});
      if (url === `/api/projects/${P}/edit-document`) {
        if (docFails) { const error = new Error('máy chủ lỗi'); error.status = 500; throw error; }
        return doc;
      }
      if (url === `/api/projects/${P}`) {
        if (reloadFails) { const error = new Error('mất kết nối'); error.status = 0; throw error; }
        return {project: {id: P}, latest_shots: [], latest_timeline: SCENE_ROWS};
      }
      if (method === 'PUT' && url.startsWith(`/api/projects/${P}/edit-document/scenes/`)) return put(body);
      if (method === 'POST' && url.startsWith(`/api/projects/${P}/edit-document/scenes/`) && url.endsWith('/resolve')) return resolve(body);
      if (url.startsWith('/api/timeline/')) return {status: 'saved', beats: [], segment: {}};
      throw new Error(`unexpected ${method} ${url}`);
    },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    confirm: (text) => { asked.push(text); return confirms; },
    window: {prompt: () => prompt},
    renderStudioStoryboard: (shots, timeline) => {
      sandbox.state.timeline = timeline;
      sandbox.state.studioEditDocumentLoad = sandbox.refreshStudioEditDocument();
    },
    document: {querySelectorAll: () => [], querySelector: (selector) => (selector.includes('data-edit-segment') ? host : null)},
    studioEditBeatGenerationSettings: async () => ({image_provider: 'gemini_web_image', ratio: '1280:720'}),
    watchStudioSceneGenerationJob() {},
    Promise, JSON, Math, Number, String, Object, Array, Boolean, Error,
  };
  vm.createContext(sandbox);
  vm.runInContext(sceneCode, sandbox);
  const writes = () => calls.filter((call) => call.method !== 'GET');
  return {sandbox, calls, writes, messages, asked};
}

const nothingOnTheTimeline = (calls) => {
  for (const call of calls) {
    if (call.method === 'GET') continue;
    assert.ok(!call.url.startsWith('/api/timeline/'), `a timeline route was written to: ${call.method} ${call.url}`);
  }
};

test("T6a: in the plan workflow a scene's chữ động is one PUT to its EditDocument scene, never PATCH /plan", async () => {
  const ui = sceneStudio();
  await ui.sandbox.editStudioSceneOverlays(31);
  assert.deepEqual(ui.writes().map((call) => [call.method, call.url, call.body]),
    [['PUT', `/api/projects/${P}/edit-document/scenes/sk-31`, {overlays: JSON.parse(HAND)}]]);
  nothingOnTheTimeline(ui.calls);
  assert.deepEqual(ui.messages.at(-1), ['Chữ động cảnh 1: đã lưu vào kế hoạch dựng và áp vào timeline.', 'success']);
});

test('T6a: SFX and the beats of a scene go to the EditDocument too, as the page reads them', async () => {
  const sfx = sceneStudio({prompt: '[{"type":"whoosh","start_seconds":0.2,"end_seconds":0.7}]'});
  await sfx.sandbox.editStudioSceneSoundCues(31);
  assert.deepEqual(sfx.writes().map((call) => [call.url, call.body]),
    [[`/api/projects/${P}/edit-document/scenes/sk-31`, {sound_cues: [{type: 'whoosh', start_seconds: 0.2, end_seconds: 0.7}]}]]);
  nothingOnTheTimeline(sfx.calls);
  const beats = sceneStudio();
  await beats.sandbox.saveStudioSceneEditPlan(31);
  assert.deepEqual(beats.writes().map((call) => [call.url, call.body]), [[`/api/projects/${P}/edit-document/scenes/sk-31`, {beats: [
    {asset_id: null, visual_path: '/p/a.png', source_kind: 'primary', duration_seconds: 2, effect: 'zoom_in', transition: 'fade',
      prompt: 'nhịp tay', status: 'ready'}]}]]);
  nothingOnTheTimeline(beats.calls);
});

test('T6a: a conflict, a skip, an error or an unknown answer is never called saved; "unchanged" is neutral', async () => {
  const cases = [
    [{status: 'blocked', counts: {applied: 0, unchanged: 0, conflicts: 1, skipped: {}}, conflicts: [{segment_id: 31}]}, /chưa áp vào timeline.*1 cảnh xung đột/],
    [{status: 'partial', counts: {applied: 0, unchanged: 1, conflicts: 0, skipped: {beat_has_jobs: 1}}}, /chưa áp vào timeline/],
    [{status: 'error', detail: 'EditDocument không còn hiện hành'}, /đã lưu vào kế hoạch dựng nhưng chưa áp vào timeline: EditDocument không còn hiện hành/],
    [{status: 'nothing_to_apply'}, /không coi là đã áp/],
    [{status: 'lạ'}, /không coi là đã áp/],
    [{}, /không coi là đã áp/],
  ];
  for (const [answer, text] of cases) {
    const ui = sceneStudio({put: () => answer});
    await ui.sandbox.editStudioSceneOverlays(31);
    const [message, type] = ui.messages.at(-1);
    assert.equal(type, 'error', JSON.stringify(answer));
    assert.match(message, text);
  }
  const unchanged = sceneStudio({put: () => ({status: 'unchanged', counts: {applied: 0, unchanged: 1, conflicts: 0, skipped: {}}})});
  await unchanged.sandbox.editStudioSceneOverlays(31);
  assert.deepEqual(unchanged.messages.at(-1), ['Chữ động cảnh 1: kế hoạch dựng và timeline đã đúng như vậy: không cần áp lại.', '']);
});

test('T6a: a request the server refuses (409/422) is an error in its own words, and the timeline is not written', async () => {
  const ui = sceneStudio({put: () => { const error = new Error('Nhịp dựng của cảnh đã có job tạo hình'); error.status = 409; throw error; }});
  await ui.sandbox.saveStudioSceneEditPlan(31);
  assert.deepEqual(ui.messages.at(-1), ['Không lưu được nhịp dựng cảnh 1: Nhịp dựng của cảnh đã có job tạo hình', 'error']);
  nothingOnTheTimeline(ui.calls);
});

test('T6a: saved but not reloaded is never "not saved", and nothing is sent again', async () => {
  for (const [answer, saved] of [[APPLIED, 'đã lưu vào kế hoạch dựng và áp vào timeline.'],
    [{status: 'unchanged', counts: {applied: 0, unchanged: 1, conflicts: 0, skipped: {}}}, 'không cần áp lại.']]) {
    const ui = sceneStudio({put: () => answer, reloadFails: true});
    await ui.sandbox.editStudioSceneOverlays(31);
    const [text, type] = ui.messages.at(-1);
    assert.ok(text.includes(saved), text);
    assert.match(text, /Chưa tải lại được storyboard \(mất kết nối\)/);
    assert.doesNotMatch(text, /Không lưu được/);
    assert.equal(type, '', 'saved but not reloaded: not an error, not a plain success either');
    assert.equal(ui.writes().length, 1, 'the PUT is not sent again');
  }
});

test('T6a: a failed reload changes nothing about a save that failed or a conflict', async () => {
  const blocked = sceneStudio({reloadFails: true,
    put: () => ({status: 'blocked', counts: {applied: 0, unchanged: 0, conflicts: 1, skipped: {}}, conflicts: [{segment_id: 31}]})});
  await blocked.sandbox.editStudioSceneOverlays(31);
  const [text, type] = blocked.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /chưa áp vào timeline.*1 cảnh xung đột/);
  assert.match(text, /Chưa tải lại được storyboard/);
  assert.equal(blocked.writes().length, 1);

  const refused = sceneStudio({reloadFails: true,
    put: () => { const error = new Error('Storyboard hoặc kịch bản không phải bản hiện hành'); error.status = 409; throw error; }});
  await refused.sandbox.editStudioSceneOverlays(31);
  assert.deepEqual(refused.messages.at(-1), ['Không lưu được chữ động cảnh 1: Storyboard hoặc kịch bản không phải bản hiện hành', 'error']);
  assert.equal(refused.writes().length, 1);
});

test('T6a: a scene the EditDocument does not hold, or a status that cannot be read, sends nothing', async () => {
  const missing = sceneStudio({doc: DOC({state: 'missing', scenes: []})});
  await missing.sandbox.editStudioSceneOverlays(31);
  assert.deepEqual(missing.writes(), []);
  assert.match(missing.messages.at(-1)[0], /chưa có trong kế hoạch dựng hiện tại/);
  const absent = sceneStudio({doc: DOC({scenes: [scene(33, 'ready', 'applied')]})});
  await absent.sandbox.saveStudioSceneEditPlan(31);
  assert.deepEqual(absent.writes(), []);
  const unknown = sceneStudio({docFails: true});
  await unknown.sandbox.editStudioSceneOverlays(31);
  await unknown.sandbox.saveStudioSceneEditPlan(31);
  await unknown.sandbox.applyStudioSceneEdit(31);
  assert.deepEqual(unknown.writes(), [], 'not known which workflow: nothing is written anywhere');
});

test('T6a: a second click while a scene is being saved sends nothing', async () => {
  const pending = [];
  const ui = sceneStudio({put: () => new Promise((resolve) => { pending.push(() => resolve(APPLIED)); })});
  const first = ui.sandbox.editStudioSceneOverlays(31);
  await new Promise((resolve) => setImmediate(resolve));
  const second = ui.sandbox.editStudioSceneOverlays(31);
  await new Promise((resolve) => setImmediate(resolve));
  pending.forEach((release) => release());   // every request answers, so a missing guard fails instead of hanging
  await Promise.all([first, second]);
  assert.equal(ui.writes().length, 1);
});

test('T6a: "Áp dụng cảnh này" is not drawn and is refused in the plan workflow; the legacy workflow keeps it', async () => {
  const plan = sceneStudio();
  await plan.sandbox.refreshStudioEditDocument();
  assert.ok(!plan.sandbox.legacyStoryboardEditSummary(SCENE_ROWS[0], 'Nhịp dựng trên timeline').includes('applyStudioSceneEdit('));
  await plan.sandbox.applyStudioSceneEdit(31);
  assert.deepEqual(plan.writes(), [], 'no AI picture made, no beats written');
  assert.match(plan.messages.at(-1)[0], /Ở luồng Kế hoạch/);

  const legacy = sceneStudio({doc: LEGACY});
  await legacy.sandbox.refreshStudioEditDocument();
  assert.ok(legacy.sandbox.legacyStoryboardEditSummary(SCENE_ROWS[0]).includes('applyStudioSceneEdit(31)'));
  await legacy.sandbox.editStudioSceneOverlays(31);
  await legacy.sandbox.saveStudioSceneEditPlan(31);
  await legacy.sandbox.applyStudioSceneEdit(31);
  assert.deepEqual(legacy.writes().map((call) => [call.method, call.url]), [
    ['PATCH', '/api/timeline/31/plan'], ['PUT', '/api/timeline/31/edit-beats'],
    ['PUT', '/api/timeline/31/edit-beats'], ['POST', '/api/timeline/31/edit-beats/apply']]);
  assert.ok(!legacy.calls.some((call) => call.url.includes('/edit-document/scenes/')), 'the legacy workflow has no EditDocument');
});

// ---------------------------------------------------------------------------
// T6b · a scene's conflict is shown with three choices: keep the timeline, use
// the plan (asked first: the hand edit is written over), or leave it for later.
// Only "applied"/"unchanged" are done; a 409 says the data moved on and reloads.
// ---------------------------------------------------------------------------

const CONFLICT = {columns: ['overlays', 'edit_transition'], expected_from: 'applied', state_hash: 's-31', layer_hash: 'l-31'};
const CONFLICT_DOC = () => DOC({scenes: [{...scene(31, 'ready', 'older'), conflict: CONFLICT}, scene(32, 'ready', 'applied'),
  scene(33, 'needs_plan')]});

test('T6b: a scene in conflict says so and offers its three choices; a scene without one offers none', async () => {
  const ui = sceneStudio({doc: CONFLICT_DOC()});
  await ui.sandbox.refreshStudioEditDocument();
  const line = ui.sandbox.editDocumentSceneLine({id: 31});
  assert.match(line, /xung đột/);
  assert.match(line, /chữ động, chuyển cảnh/);
  for (const call of ["resolveStudioSceneConflict(31, 'keep_timeline')", "resolveStudioSceneConflict(31, 'use_plan')",
    'deferStudioSceneConflict(31)']) assert.ok(line.includes(call), call);
  assert.equal(ui.sandbox.studioScenePlanState({id: 31}).key, 'conflict');
  const clean = ui.sandbox.editDocumentSceneLine({id: 32});
  assert.ok(!clean.includes('resolveStudioSceneConflict') && !clean.includes('deferStudioSceneConflict'));
  assert.notEqual(ui.sandbox.studioScenePlanState({id: 32}).key, 'conflict');
});

test('T6b: "Giữ bản trên timeline" is one POST with the conflict as shown, and done only when the server says so', async () => {
  const ui = sceneStudio({doc: CONFLICT_DOC(), resolve: () => ({status: 'unchanged', resolved: 'keep_timeline', conflict: null})});
  await ui.sandbox.refreshStudioEditDocument();
  await ui.sandbox.resolveStudioSceneConflict(31, 'keep_timeline');
  assert.deepEqual(ui.writes().map((call) => [call.method, call.url, call.body]), [['POST',
    `/api/projects/${P}/edit-document/scenes/sk-31/resolve`,
    {choice: 'keep_timeline', columns: ['overlays', 'edit_transition'], state_hash: 's-31', layer_hash: 'l-31'}]]);
  assert.deepEqual(ui.asked, [], 'keeping the timeline writes nothing over it: nothing to ask');
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'success');
  assert.match(text, /đã giữ bản trên timeline/);
});

test('T6b: "Dùng kế hoạch…" asks first, naming the parts written over; a refusal sends nothing', async () => {
  const refused = sceneStudio({doc: CONFLICT_DOC(), confirms: false});
  await refused.sandbox.refreshStudioEditDocument();
  await refused.sandbox.resolveStudioSceneConflict(31, 'use_plan');
  assert.deepEqual(refused.writes(), []);
  assert.equal(refused.asked.length, 1);
  assert.match(refused.asked[0], /chữ động, chuyển cảnh sẽ bị ghi đè/);

  const agreed = sceneStudio({doc: CONFLICT_DOC(), resolve: () => ({status: 'applied', resolved: 'use_plan'})});
  await agreed.sandbox.refreshStudioEditDocument();
  await agreed.sandbox.resolveStudioSceneConflict(31, 'use_plan');
  assert.deepEqual(agreed.writes().map((call) => call.body), [
    {choice: 'use_plan', columns: ['overlays', 'edit_transition'], state_hash: 's-31', layer_hash: 'l-31'}]);
  assert.deepEqual(agreed.messages.at(-1), ['Cảnh 1: đã ghi kế hoạch dựng lên cảnh này.', 'success']);
});

test('T6b: "Để sau" sends nothing and changes nothing', async () => {
  const ui = sceneStudio({doc: CONFLICT_DOC()});
  await ui.sandbox.refreshStudioEditDocument();
  ui.sandbox.deferStudioSceneConflict(31);
  assert.deepEqual(ui.writes(), []);
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, '');
  assert.match(text, /chưa đổi gì, xung đột vẫn còn/);
});

test('T6b: a 409 says the data moved on and reloads the state; nothing is sent again', async () => {
  const ui = sceneStudio({doc: CONFLICT_DOC(), resolve: () => {
    const error = new Error('Timeline hoặc kế hoạch dựng của cảnh đã đổi từ lúc bạn xem'); error.status = 409; throw error; }});
  await ui.sandbox.refreshStudioEditDocument();
  const before = ui.calls.length;
  await ui.sandbox.resolveStudioSceneConflict(31, 'keep_timeline');
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /Dữ liệu đã đổi từ lúc bạn xem, trạng thái mới đã được tải lại: hãy xem lại rồi quyết định lại/);
  assert.equal(ui.writes().length, 1, 'never sent again');
  assert.ok(ui.calls.slice(before).some((call) => call.method === 'GET' && call.url === `/api/projects/${P}/edit-document`),
    'the state is read again');
});

test('T6b: an answer that is lost is never taken as done, and never sent again on its own', async () => {
  const ui = sceneStudio({doc: CONFLICT_DOC(), resolve: () => { const error = new Error('mất kết nối'); error.status = 0; throw error; }});
  await ui.sandbox.refreshStudioEditDocument();
  await ui.sandbox.resolveStudioSceneConflict(31, 'use_plan');
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /Không rõ quyết định cảnh 1 đã được lưu hay chưa \(mất kết nối\)\. Không gửi lại/);
  assert.equal(ui.writes().length, 1);
});

test('T6b: blocked, partial or an unknown status is never called resolved', async () => {
  for (const answer of [{status: 'blocked', detail: 'Chưa ghi được kế hoạch lên cảnh này', conflict: CONFLICT},
    {status: 'partial'}, {status: 'lạ'}, {}]) {
    const ui = sceneStudio({doc: CONFLICT_DOC(), resolve: () => answer});
    await ui.sandbox.refreshStudioEditDocument();
    await ui.sandbox.resolveStudioSceneConflict(31, 'use_plan');
    const [text, type] = ui.messages.at(-1);
    assert.equal(type, 'error', JSON.stringify(answer));
    assert.doesNotMatch(text, /đã ghi kế hoạch|đã giữ bản/);
  }
});

test('T6b: a scene without a conflict, or a second click while deciding, sends nothing', async () => {
  const clean = sceneStudio({doc: CONFLICT_DOC()});
  await clean.sandbox.refreshStudioEditDocument();
  await clean.sandbox.resolveStudioSceneConflict(32, 'use_plan');
  assert.deepEqual(clean.writes(), []);
  assert.match(clean.messages.at(-1)[0], /không còn xung đột/);

  const pending = [];
  const busy = sceneStudio({doc: CONFLICT_DOC(), resolve: () => new Promise((resolve) => { pending.push(() => resolve({status: 'unchanged'})); })});
  await busy.sandbox.refreshStudioEditDocument();
  const first = busy.sandbox.resolveStudioSceneConflict(31, 'keep_timeline');
  await new Promise((resolve) => setImmediate(resolve));
  const second = busy.sandbox.resolveStudioSceneConflict(31, 'keep_timeline');
  await new Promise((resolve) => setImmediate(resolve));
  pending.forEach((release) => release());
  await Promise.all([first, second]);
  assert.equal(busy.writes().length, 1);
});


// ---------------------------------------------------------------------------
// T4 phương án B: "Áp dụng vào timeline…" confirms the version shown, nothing else.
// ---------------------------------------------------------------------------

test('T4 B: with no current version to confirm, nothing is sent', async () => {
  const ui = studio({doc: DOC({document_hash: ''})});
  await ui.sandbox.applyAllStudioSceneEdits();
  assert.deepEqual(ui.posts(), []);
  assert.match(ui.messages.at(-1)[0], /Chưa có kế hoạch dựng hiện hành để xác nhận/);
});

test('T4 B: a version that changed since it was shown is not applied, and the page says so', async () => {
  const ui = studio({plan: () => ({status: 'unchanged', planned: [], wanted: [], problems: {},
    applied: {status: 'needs_confirmation', detail: 'Chưa áp: kế hoạch dựng đã đổi từ lúc bạn xem - xem lại rồi xác nhận lại'}})});
  await ui.sandbox.applyAllStudioSceneEdits();
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /đã đổi từ lúc bạn xem/);
  assert.doesNotMatch(text, /Đã áp/);
});

test('T4 B: the headline says whether the version shown is confirmed', async () => {
  for (const [confirmed, words] of [[true, /đã xác nhận/], [false, /chưa xác nhận/]]) {
    const ui = studio({doc: DOC({confirmed})});
    await ui.sandbox.refreshStudioEditDocument();
    assert.match(ui.sandbox.editDocumentHeadline(), words);
  }
});
