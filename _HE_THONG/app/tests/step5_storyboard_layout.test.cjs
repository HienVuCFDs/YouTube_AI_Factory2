// Bước 5 · Storyboard layout A, run for real: the rows' filters and search, the
// scene's plan state as GET …/edit-document says it, and editing a scene in its
// detail panel. A save sends only what changed to the same two routes as before:
// a field left out is left as it is (Database.update_project_timeline_segment),
// so the scene's voice is dropped (audio_path: '') only when its words change -
// asked first - never for a picture or length edit, never on cancel, and a
// refused request is never shown as saved.
//
// The two requests cannot be one, so a save can land half-way or end unknown.
// The fake server here holds the rows the way the routes do (text stripped), so
// the tests can see what a save leaves behind: it reads the scene back first,
// sends only what is not there yet, never writes over a field changed elsewhere,
// and says plainly which part is saved, refused or unknown. In the plan workflow
// the words are read-only and never sent.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/project-detail.js'), 'utf8');

function fn(name) {
  const at = [`  async function ${name}(`, `  function ${name}(`].map((head) => page.indexOf(head)).find((index) => index >= 0);
  assert.ok(at >= 0, `no function ${name}`);
  return page.slice(at, page.indexOf('\n  }\n', at) + 4);
}
function constant(name) {
  const at = page.indexOf(`  const ${name} = `);
  assert.ok(at >= 0, `no const ${name}`);
  return page.slice(at, page.indexOf(';\n', at) + 2);
}

const code = [
  constant('STUDIO_SCENE_PLAN'), constant('STORYBOARD_IMAGE'), constant('studioSceneWords'),
  constant('STUDIO_SCENE_FIELDS'), constant('STUDIO_SCENE_FIELD_LABELS'), constant('STUDIO_SCENE_PART_LABELS'),
  ...['studioStoryboardView', 'storyboardRowMatches', 'studioEditFlow', 'studioEditDocumentScene', 'studioScenePlanState',
    'studioScenePlanChip', 'storyboardTimecode', 'studioSelectedScene', 'renderStudioSceneDetail', 'selectStudioScene',
    'studioSceneValue', 'studioSceneRowValues', 'studioScenePending', 'studioSceneOutcome', 'studioSceneNarrationLocked', 'keepStudioSceneDraft',
    'studioSceneEditChanges', 'storyboardSceneEditForm', 'markStudioSceneEditDirty', 'cancelStudioSceneEdit',
    'studioSceneSaveReport', 'studioSceneMergeRows', 'stopStudioSceneSave', 'saveStudioSceneEdit', 'editStudioScene',
  ].map(fn),
].join('\n');

const row = (data) => ({dataset: {missingVisual: '0', missingAudio: '0', ready: '1', sceneState: 'ready', planState: '', sceneNumber: '1', search: '', ...data}});
const SHOTS = [
  {id: 11, shot_index: 1, narration: 'Mở đầu', visual_prompt: 'Đồi cây phong', duration_seconds: 5},
  {id: 12, shot_index: 2, narration: 'Diệp lục', visual_prompt: 'Tế bào lá', duration_seconds: 6.5},
];
const TIMELINE = [
  {id: 31, shot_id: 11, segment_index: 1, voice_text: 'Mỗi mùa thu, cả khu rừng đổi màu.', audio_path: 'voice-31.wav', visual_path: 'a.png'},
  {id: 32, shot_id: 12, segment_index: 2, voice_text: 'Lá có màu xanh vì diệp lục.', audio_path: '', visual_path: ''},
];

// What the routes answer when they refuse (error.status, as studio-lanes.js api() sets it),
// and what a lost connection looks like (no status at all).
const httpError = (status, message = 'Máy chủ từ chối') => Object.assign(new Error(message), {status});
const lostConnection = () => new TypeError('Failed to fetch');

// `respond(call, server)` may answer a call itself (return a value), fail it (throw), or
// return undefined to let the fake server do what the route does. `server.apply(call)`
// performs the route's write, so a test can write and then lose the answer.
function board({confirms = true, respond = null, flow = null} = {}) {
  const calls = [];
  const messages = [];
  const asked = [];
  const values = {studioSceneEditNarration: null, studioSceneEditVisual: null, studioSceneEditDuration: null};
  const detail = {innerHTML: '', scrollIntoView() {}};
  const db = {shots: SHOTS.map((s) => ({...s})), timeline: TIMELINE.map((t) => ({...t}))};
  const strip = (body) => Object.fromEntries(Object.entries(body).map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v]));
  const server = {
    db,
    apply(call) {
      const shot = call.url.match(/^\/api\/shots\/(\d+)$/);
      const segment = call.url.match(/^\/api\/timeline\/(\d+)$/);
      if (shot) {
        const target = db.shots.find((s) => s.id === Number(shot[1]));
        Object.assign(target, strip(call.body));
        return {status: 'saved', shot: {...target}};
      }
      if (segment) {
        const target = db.timeline.find((t) => t.id === Number(segment[1]));
        Object.assign(target, strip(call.body));
        return {status: 'saved', segment: {...target}};
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    },
  };
  const sandbox = {
    state: {studioProjectId: 7, shots: SHOTS.map((s) => ({...s})), timeline: TIMELINE.map((t) => ({...t})), storyboardView: null,
      studioEditDocument: flow ? {project_id: 7, mode: flow} : null},
    $: (id) => {
      if (id === 'studioSceneDetail') return detail;
      if (id === 'studioSceneEditForm') return detail.innerHTML.includes('studioSceneEditForm') ? {} : null;
      if (id in values) return detail.innerHTML.includes(id) ? {get value() { return values[id] ?? undefined; }, focus() {}} : null;
      return null;
    },
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      const call = {url, method, body: options.body ? JSON.parse(options.body) : null};
      calls.push(call);
      const answer = respond ? respond(call, server) : undefined;
      if (answer !== undefined) return answer;
      if (method === 'GET') return {latest_shots: db.shots.map((s) => ({...s})), latest_timeline: db.timeline.map((t) => ({...t}))};
      return server.apply(call);
    },
    renderStudioStoryboard: (shots, timeline) => { sandbox.state.timeline = timeline; sandbox.rendered = (sandbox.rendered || 0) + 1; },
    storyboardSegmentForShot: (shot, timeline) => timeline.find((t) => Number(t.shot_id) === Number(shot.id)) || null,
    storyboardSceneFacts: () => ({state: 'ready', label: 'Sẵn sàng'}),
    storyboardSceneParts: () => ({preview: '<img>', body: '<div class="storyboard-body-parts"></div>', wantsVisual: false}),
    findStudioShot: (id) => sandbox.state.shots.find((s) => Number(s.id) === Number(id)) || null,
    editStudioScenePrompt: async () => { calls.push({url: 'prompt-dialogs', method: 'PROMPT'}); },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    confirm: (text) => { asked.push(text); return confirms; },
    document: {querySelectorAll: () => []},
    window: {matchMedia: () => ({matches: false})},
    Promise, JSON, Math, Number, String, Object, Array, Boolean, Error, Set,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return {sandbox, calls, messages, asked, values, detail, db, writes: () => calls.filter((c) => c.method !== 'GET')};
}

// ---------------------------------------------------------------------------
// Filters and search read the row's own data
// ---------------------------------------------------------------------------

test('production filters: missing picture, missing voice, both, draft and fallback each pick their rows', () => {
  const {sandbox} = board();
  const match = (data, view) => sandbox.storyboardRowMatches(row(data), {query: '', prod: 'all', plan: 'all', ...view});
  const both = {missingVisual: '1', missingAudio: '1', ready: '0', sceneState: 'missing_both'};
  assert.equal(match(both, {prod: 'missing_visual'}), true, 'a scene missing both is missing its picture');
  assert.equal(match(both, {prod: 'missing_audio'}), true);
  assert.equal(match(both, {prod: 'missing_both'}), true);
  assert.equal(match({missingVisual: '1', ready: '0', sceneState: 'missing_visual'}, {prod: 'missing_both'}), false);
  assert.equal(match({}, {prod: 'ready'}), true);
  assert.equal(match({ready: '0', sceneState: 'draft'}, {prod: 'draft'}), true);
  assert.equal(match({ready: '1', sceneState: 'fallback'}, {prod: 'draft'}), false);
  assert.equal(match({sceneState: 'fallback'}, {prod: 'fallback'}), true);
});

test('the plan filter compares the state the row holds, and "all" keeps every row', () => {
  const {sandbox} = board();
  const match = (planState, plan) => sandbox.storyboardRowMatches(row({planState}), {query: '', prod: 'all', plan});
  assert.equal(match('applied', 'applied'), true);
  assert.equal(match('planned', 'applied'), false);
  assert.equal(match('stale', 'all'), true);
  assert.equal(match('', 'all'), true, 'a legacy project has no plan state and is not filtered out');
});

test('search finds a scene by its number or by words of its narration or picture', () => {
  const {sandbox} = board();
  const view = (query) => ({query, prod: 'all', plan: 'all'});
  const scene7 = row({sceneNumber: '7', search: 'màu đỏ của cây phong hàng cây phong đỏ'});
  for (const query of ['7', 'cảnh 7', '#7', 'Cây Phong']) assert.equal(sandbox.storyboardRowMatches(scene7, view(query)), true, query);
  assert.equal(sandbox.storyboardRowMatches(scene7, view('17')), false, 'a number matches the whole scene number');
  assert.equal(sandbox.storyboardRowMatches(row({sceneNumber: '17'}), view('7')), false, 'scene 17 is not scene 7');
  assert.equal(sandbox.storyboardRowMatches(scene7, view('diệp lục')), false);
});

// ---------------------------------------------------------------------------
// The plan state of a row is the EditDocument's, never a guess
// ---------------------------------------------------------------------------

test('each EditDocument status keeps its own name: stale, review, older, applied, planned, not planned', () => {
  const {sandbox} = board();
  const doc = (scenes, state = 'current') => ({project_id: 7, mode: 'plan', state, scenes});
  const at = (status, applied = null) => sandbox.studioScenePlanState({id: 31}, doc([{segment_id: 31, scene_key: 'k', status, applied}])).key;
  assert.equal(at('needs_plan'), 'needs_plan');
  assert.equal(at('ready', 'not_applied'), 'planned');
  assert.equal(at('ready', 'applied'), 'applied');
  assert.equal(at('ready', 'older'), 'older');
  assert.equal(at('stale_content'), 'stale');
  assert.equal(at('stale_timing'), 'stale');
  assert.equal(at('visual_review', 'applied'), 'review');
  assert.equal(sandbox.studioScenePlanState({id: 99}, doc([])).key, 'absent');
  assert.equal(sandbox.studioScenePlanState({id: 31}, doc([], 'missing')).key, 'needs_plan');
  assert.equal(sandbox.studioScenePlanState({id: 31}, doc([], 'outdated')).key, 'outdated');
  assert.equal(sandbox.studioScenePlanState({id: 31}, doc([], 'error')).key, 'unknown');
  assert.equal(sandbox.studioScenePlanState({id: 31}, {project_id: 7, mode: 'legacy', state: 'not_applicable'}).key, '', 'no plan state outside the plan workflow');
  assert.equal(sandbox.studioScenePlanState({id: 31}, {project_id: 8, mode: 'plan', state: 'current', scenes: []}).key, '', "another project's document is never read");
});

// ---------------------------------------------------------------------------
// Editing a scene in its panel
// ---------------------------------------------------------------------------

const edits = (ui) => ui.writes().map((c) => [c.method, c.url, c.body]);

test('"Sửa cảnh" opens the form for that scene; it says a picture or length edit keeps the voice', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  assert.match(ui.detail.innerHTML, /id="studioSceneEditForm"/);
  assert.match(ui.detail.innerHTML, /Mỗi mùa thu, cả khu rừng đổi màu\./, 'the form starts from the scene as it is');
  assert.match(ui.detail.innerHTML, /Sửa mô tả hình hoặc thời lượng giữ nguyên giọng đọc của cảnh\./);
  assert.match(ui.detail.innerHTML, /id="studioSceneVoiceWarning" role="alert" hidden/, 'no warning while the words are unchanged');
  assert.match(ui.detail.innerHTML, /step="1"/, 'whole seconds, as both routes take');
});

test('cancelling sends nothing and leaves the scene as it was', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditNarration: 'Lời khác', studioSceneEditVisual: 'Hình khác', studioSceneEditDuration: '9'});
  ui.sandbox.markStudioSceneEditDirty();
  ui.sandbox.cancelStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.equal(ui.asked.length, 0);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.doesNotMatch(ui.detail.innerHTML, /studioSceneEditForm/);
  assert.equal(ui.sandbox.state.timeline[0].audio_path, 'voice-31.wav');
  assert.equal(ui.sandbox.state.shots[0].visual_prompt, 'Đồi cây phong');
});

test('editing only the picture keeps the voice: no question, no audio_path, no words sent', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.values.studioSceneEditVisual = 'Đồi cây phong lúc hoàng hôn';
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 0, 'nothing to warn about');
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {visual_prompt: 'Đồi cây phong lúc hoàng hôn'}],
    ['PATCH', '/api/timeline/31', {visual_prompt: 'Đồi cây phong lúc hoàng hôn'}],
  ]);
  for (const call of ui.writes()) {
    assert.ok(!('audio_path' in call.body), `${call.url} must not touch the voice`);
    assert.ok(!('voice_text' in call.body) && !('narration' in call.body), `${call.url} must not resend the words`);
  }
  assert.deepEqual(ui.messages.at(-1), ['Đã lưu cảnh này. Giọng đọc của cảnh được giữ nguyên.', 'success']);
});

test('editing only the length keeps the voice too', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.values.studioSceneEditDuration = '6';
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 0);
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {duration_seconds: 6}],
    ['PATCH', '/api/timeline/31', {duration_seconds: 6}],
  ]);
});

test('retyping the same words with other spacing is not a change of words', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditNarration: '  Mỗi mùa thu,  cả khu rừng\nđổi màu. ', studioSceneEditVisual: 'Hình mới'});
  ui.sandbox.markStudioSceneEditDirty();
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 0);
  assert.ok(ui.writes().every((call) => !('audio_path' in call.body) && !('voice_text' in call.body)));
});

test('changing the words warns at once, asks before saving, then drops the voice through the existing contract', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.values.studioSceneEditNarration = 'Lời mới.';
  const warning = {hidden: true};
  const $ = ui.sandbox.$;
  ui.sandbox.$ = (id) => (id === 'studioSceneVoiceWarning' ? warning : $(id));
  ui.sandbox.markStudioSceneEditDirty();
  assert.equal(warning.hidden, false, 'the warning shows as soon as the words differ');
  ui.sandbox.$ = $;
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 1);
  assert.match(ui.asked[0], /Lời đọc đã đổi nên giọng đọc hiện tại của cảnh này sẽ bị bỏ/);
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {narration: 'Lời mới.'}],
    ['PATCH', '/api/timeline/31', {voice_text: 'Lời mới.', subtitle_text: 'Lời mới.', audio_path: ''}],
  ]);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.equal(ui.messages.at(-1)[1], 'success');
  assert.equal(ui.sandbox.rendered, 1, 'the storyboard is drawn again from the server');
});

test('declining that question sends nothing and keeps the form and what was typed', async () => {
  const ui = board({confirms: false});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditNarration: 'Lời mới.', studioSceneEditVisual: 'x'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 1);
  assert.equal(ui.writes().length, 0);
  assert.ok(ui.sandbox.state.storyboardEdit);
  assert.match(ui.detail.innerHTML, /studioSceneEditForm/);
});

test('a scene without a voice is not asked about; changed words still clear the (empty) voice path', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(12, 32);
  Object.assign(ui.values, {studioSceneEditNarration: 'A', studioSceneEditVisual: 'B', studioSceneEditDuration: '8'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 0);
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/12', {narration: 'A', visual_prompt: 'B', duration_seconds: 8}],
    ['PATCH', '/api/timeline/32', {voice_text: 'A', subtitle_text: 'A', audio_path: '', visual_prompt: 'B', duration_seconds: 8}],
  ]);
});

test('a form saved unchanged sends nothing and closes', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.equal(ui.asked.length, 0);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.deepEqual(ui.messages.at(-1), ['Không có thay đổi nào để lưu. Cảnh giữ nguyên.', '']);
});

test('a length that is not whole seconds from 1 to 3600 is refused before any request', async () => {
  for (const bad of ['0', '6.5', '3601', 'abc', '']) {
    const ui = board();
    await ui.sandbox.editStudioScene(11, 31);
    ui.values.studioSceneEditDuration = bad;
    await ui.sandbox.saveStudioSceneEdit();
    assert.equal(ui.writes().length, 0, bad);
    assert.deepEqual(ui.messages.at(-1), ['Thời lượng cần là số giây nguyên từ 1 đến 3600.', 'error'], bad);
    assert.ok(ui.sandbox.state.storyboardEdit, `${bad}: the form stays open`);
  }
});

test('a request refused before anything is written is an error, never "saved": nothing else is sent and the form stays', async () => {
  const ui = board({respond: (call) => { if (call.url === '/api/shots/11') throw httpError(409); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditNarration: 'Lời đã gõ', studioSceneEditVisual: 'Hình đã gõ', studioSceneEditDuration: '6'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.writes().map((c) => c.url), ['/api/shots/11'], 'the timeline is not touched after the shot was refused');
  assert.deepEqual(ui.messages.at(-1), ['Không lưu được cảnh 1: Máy chủ từ chối. Máy chủ từ chối trước khi ghi nên cảnh chưa đổi. Nội dung đang nhập được giữ nguyên.', 'error']);
  const edit = ui.sandbox.state.storyboardEdit;
  assert.ok(edit && !edit.saving, 'the form can be saved again');
  assert.ok(!edit.retry, 'nothing was written, so there is no "rest" to save');
  assert.match(ui.detail.innerHTML, /Lời đã gõ/, 'what was typed is still there');
  assert.match(ui.detail.innerHTML, />Lưu cảnh</);
  assert.deepEqual(ui.db.shots[0], SHOTS[0], 'the server rows are as they were');
});

test('moving to another scene with unsaved changes asks; declining stays on the scene being edited', async () => {
  const ui = board({confirms: false});
  await ui.sandbox.editStudioScene(11, 31);
  ui.sandbox.markStudioSceneEditDirty();
  ui.sandbox.selectStudioScene(12);
  assert.match(ui.asked.at(-1), /thay đổi chưa lưu/);
  assert.equal(ui.sandbox.state.storyboardView.selected, 11);
  assert.ok(ui.sandbox.state.storyboardEdit);
});

test('moving with unsaved changes and accepting drops the draft and shows the other scene', async () => {
  const ui = board({confirms: true});
  await ui.sandbox.editStudioScene(11, 31);
  ui.sandbox.markStudioSceneEditDirty();
  ui.sandbox.selectStudioScene(12);
  assert.equal(ui.sandbox.state.storyboardView.selected, 12);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.match(ui.detail.innerHTML, /<h3>Cảnh 2<\/h3>/);
  assert.equal(ui.writes().length, 0);
});

test('a clean form moves without asking', async () => {
  const ui = board({confirms: false});
  await ui.sandbox.editStudioScene(11, 31);
  ui.sandbox.selectStudioScene(12);
  assert.equal(ui.asked.length, 0);
  assert.equal(ui.sandbox.state.storyboardView.selected, 12);
});

test('a scene that is not on the long storyboard keeps the earlier dialogs', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(999, 0);
  assert.deepEqual(ui.calls.map((c) => c.url), ['prompt-dialogs']);
});

// ---------------------------------------------------------------------------
// Plan workflow: the words are the script's
// ---------------------------------------------------------------------------

test('in the plan workflow the words are read-only, say where to change them, and carry no voice warning', async () => {
  const ui = board({flow: 'plan'});
  await ui.sandbox.editStudioScene(11, 31);
  assert.match(ui.detail.innerHTML, /<textarea id="studioSceneEditNarration" rows="4" readonly aria-readonly="true"/);
  assert.match(ui.detail.innerHTML, /Mỗi mùa thu, cả khu rừng đổi màu\./, 'the words can still be read, selected and copied');
  assert.match(ui.detail.innerHTML, /sửa kịch bản ở Bước 3/);
  assert.doesNotMatch(ui.detail.innerHTML, /studioSceneVoiceWarning/);
  assert.match(ui.detail.innerHTML, /Sửa mô tả hình hoặc thời lượng giữ nguyên giọng đọc của cảnh\./);
});

test('in the plan workflow a save never sends the words or drops the voice, whatever the field holds', async () => {
  const ui = board({flow: 'plan'});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditNarration: 'Lời bị sửa bằng cách khác', studioSceneEditVisual: 'Hình mới'});
  ui.sandbox.markStudioSceneEditDirty();
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.asked.length, 0, 'no question about the voice');
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {visual_prompt: 'Hình mới'}],
    ['PATCH', '/api/timeline/31', {visual_prompt: 'Hình mới'}],
  ]);
  assert.equal(ui.db.timeline[0].audio_path, 'voice-31.wav');
  assert.deepEqual(ui.messages.at(-1), ['Đã lưu cảnh này. Giọng đọc của cảnh được giữ nguyên.', 'success']);
});

test('in the plan workflow changing only the words is no change at all', async () => {
  const ui = board({flow: 'plan'});
  await ui.sandbox.editStudioScene(11, 31);
  ui.values.studioSceneEditNarration = 'Lời khác hẳn';
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.deepEqual(ui.messages.at(-1), ['Không có thay đổi nào để lưu. Cảnh giữ nguyên.', '']);
});

test('outside the plan workflow (and when it is not known) the words stay editable as before', async () => {
  for (const flow of ['legacy', null]) {
    const ui = board({flow});
    await ui.sandbox.editStudioScene(11, 31);
    assert.match(ui.detail.innerHTML, /<textarea id="studioSceneEditNarration" rows="4">/, String(flow));
    assert.doesNotMatch(ui.detail.innerHTML, /readonly/, String(flow));
  }
});

// ---------------------------------------------------------------------------
// A save that lands half-way, or whose outcome is not known
// ---------------------------------------------------------------------------

const typed = {studioSceneEditVisual: 'Hình đã gõ', studioSceneEditDuration: '6'};

test('every save reads the scene back first; without that read nothing is sent', async () => {
  const ui = board({respond: (call) => { if (call.method === 'GET') throw lostConnection(); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.calls.map((c) => c.method), ['GET']);
  assert.match(ui.messages.at(-1)[0], /^Chưa đọc được dữ liệu mới nhất của cảnh 1 \(Failed to fetch\) nên chưa gửi gì\./);
  assert.equal(ui.messages.at(-1)[1], 'error');
  assert.ok(ui.sandbox.state.storyboardEdit && !ui.sandbox.state.storyboardEdit.saving);
  assert.match(ui.detail.innerHTML, /Hình đã gõ/);
  assert.match(ui.detail.innerHTML, />Lưu cảnh</, 'the form is drawn ready to save again');
  assert.doesNotMatch(ui.detail.innerHTML, /aria-busy/);
});

test('shot saved, timeline refused: says which part is saved, shows the server rows, keeps the form, and the retry sends only the timeline', async () => {
  let refuse = true;
  const ui = board({respond: (call) => { if (call.url === '/api/timeline/31' && refuse) throw httpError(422, 'Dữ liệu không hợp lệ'); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {visual_prompt: 'Hình đã gõ', duration_seconds: 6}],
    ['PATCH', '/api/timeline/31', {visual_prompt: 'Hình đã gõ', duration_seconds: 6}],
  ]);
  const [text, type] = ui.messages.at(-1);
  assert.equal(type, 'error');
  assert.match(text, /^Lưu cảnh 1 chưa xong\. cảnh \(storyboard\): đã lưu; timeline: chưa lưu \(máy chủ từ chối: Dữ liệu không hợp lệ\)\./);
  assert.doesNotMatch(text, /Không lưu được cảnh/, 'never "not saved" when the shot was saved');
  assert.equal(ui.sandbox.rendered, 1, 'the page shows what the server holds now');
  assert.equal(ui.sandbox.state.shots[0].visual_prompt, 'Hình đã gõ', 'the saved shot is shown as saved');
  const edit = ui.sandbox.state.storyboardEdit;
  assert.ok(edit && !edit.saving && edit.retry);
  assert.match(ui.detail.innerHTML, /Hình đã gõ/, 'what was typed is still there');
  assert.match(ui.detail.innerHTML, /id="studioSceneSaveState"/);
  assert.match(ui.detail.innerHTML, />Lưu phần còn lại</);

  refuse = false;
  ui.calls.length = 0;
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(edits(ui), [['PATCH', '/api/timeline/31', {visual_prompt: 'Hình đã gõ', duration_seconds: 6}]], 'the shot is not sent again');
  assert.deepEqual(ui.messages.at(-1), ['Đã lưu cảnh này. Giọng đọc của cảnh được giữ nguyên.', 'success']);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.equal(ui.db.timeline[0].visual_prompt, 'Hình đã gõ');
});

test('a timeline request whose answer is lost is "unknown", is not sent again blindly, and a retry that finds it written sends nothing', async () => {
  let lose = true;
  const ui = board({respond: (call, server) => {
    if (call.url === '/api/timeline/31' && lose) { server.apply(call); throw lostConnection(); }
  }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  const [text] = ui.messages.at(-1);
  assert.match(text, /timeline: không xác định được đã lưu hay chưa \(Failed to fetch\)/);
  assert.equal(ui.writes().length, 2, 'one attempt each, no automatic resend');
  assert.ok(ui.sandbox.state.storyboardEdit.retry);

  lose = false;
  ui.calls.length = 0;
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0, 'both parts are already on the server');
  assert.deepEqual(ui.messages.at(-1), ['Thay đổi của cảnh 1 đã có sẵn trên máy chủ; không gửi lại gì.', 'success']);
});

test('a 5xx is "unknown" too; when the retry finds it was not written, only that part is sent', async () => {
  let fail = true;
  const ui = board({respond: (call) => { if (call.url === '/api/timeline/31' && fail) throw httpError(500, 'Internal Server Error'); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  assert.match(ui.messages.at(-1)[0], /timeline: không xác định được đã lưu hay chưa \(Internal Server Error\)/);
  fail = false;
  ui.calls.length = 0;
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.writes().map((c) => c.url), ['/api/timeline/31']);
});

test('a shot request whose answer is lost stops the save before the timeline, and is not called "not saved"', async () => {
  const ui = board({respond: (call) => { if (call.url === '/api/shots/11') throw lostConnection(); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.writes().map((c) => c.url), ['/api/shots/11']);
  assert.match(ui.messages.at(-1)[0], /cảnh \(storyboard\): không xác định được đã lưu hay chưa \(Failed to fetch\); timeline: chưa gửi/);
  assert.ok(ui.sandbox.state.storyboardEdit.retry);
});

test('a field changed elsewhere since the form opened is never written over: nothing is sent and the page shows the newer rows', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.db.timeline[0].visual_prompt = 'Hình do người khác sửa';
  Object.assign(ui.values, {studioSceneEditVisual: 'Hình của tôi'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.match(ui.messages.at(-1)[0], /^Không lưu cảnh 1: mô tả hình đã bị thay đổi ở nơi khác kể từ khi mở form, nên không ghi đè\. Chưa gửi gì\./);
  assert.equal(ui.db.timeline[0].visual_prompt, 'Hình do người khác sửa');
  assert.equal(ui.sandbox.rendered, 1);
  assert.match(ui.detail.innerHTML, /Hình của tôi/, 'what was typed is kept');
});

test('a voice made since the form opened is not dropped by new words: the save stops', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(12, 32);
  ui.db.timeline[1].audio_path = 'voice-32-new.wav';
  ui.values.studioSceneEditNarration = 'Lời mới';
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.match(ui.messages.at(-1)[0], /giọng đọc đã bị thay đổi ở nơi khác/);
  assert.equal(ui.db.timeline[1].audio_path, 'voice-32-new.wav');
});

test('new words always go out with an empty voice path, even when the path already reads empty', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(12, 32);
  ui.values.studioSceneEditNarration = 'Lời mới';
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(edits(ui)[1], ['PATCH', '/api/timeline/32', {voice_text: 'Lời mới', subtitle_text: 'Lời mới', audio_path: ''}]);
});

test('a retry whose timeline moved on elsewhere after the shot was saved stops instead of writing over it', async () => {
  let refuse = true;
  const ui = board({respond: (call) => { if (call.url === '/api/timeline/31' && refuse) throw httpError(409); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  refuse = false;
  ui.db.timeline[0].duration_seconds = 9;
  ui.calls.length = 0;
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.match(ui.messages.at(-1)[0], /thời lượng đã bị thay đổi ở nơi khác/);
  assert.equal(ui.db.timeline[0].duration_seconds, 9);
});

test("the form's own saved part is not mistaken for someone else's change when it is edited again", async () => {
  let refuse = true;
  const ui = board({respond: (call) => { if (call.url === '/api/timeline/31' && refuse) throw httpError(409); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  refuse = false;
  ui.values.studioSceneEditVisual = 'Hình sửa lần hai';
  ui.calls.length = 0;
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(edits(ui), [
    ['PATCH', '/api/shots/11', {visual_prompt: 'Hình sửa lần hai'}],
    ['PATCH', '/api/timeline/31', {visual_prompt: 'Hình sửa lần hai', duration_seconds: 6}],
  ]);
  assert.equal(ui.messages.at(-1)[1], 'success');
});

test('both parts saved but the reload fails: says saved and not reloaded, and shows the rows the routes sent back', async () => {
  let gets = 0;
  const ui = board({respond: (call) => { if (call.method === 'GET' && ++gets === 2) throw lostConnection(); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, {studioSceneEditVisual: 'Hình đã gõ'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 2);
  assert.deepEqual(ui.messages.at(-1), ['Đã lưu cảnh này. Giọng đọc của cảnh được giữ nguyên. Chưa tải lại được dữ liệu (Failed to fetch); danh sách có thể còn nội dung cũ, hãy mở lại dự án để xem bản mới nhất.', '']);
  assert.equal(ui.sandbox.state.storyboardEdit, null, 'nothing is left to save');
  assert.equal(ui.sandbox.state.shots[0].visual_prompt, 'Hình đã gõ');
  assert.equal(ui.sandbox.state.timeline[0].visual_prompt, 'Hình đã gõ');
});

test('a scene that is no longer on the server is not saved', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.db.timeline.splice(0, 1);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  assert.equal(ui.writes().length, 0);
  assert.match(ui.messages.at(-1)[0], /không còn trong storyboard hiện tại trên máy chủ nên chưa gửi gì/);
});

test('closing the form after a half-way save never says the scene is unchanged', async () => {
  const ui = board({respond: (call) => { if (call.url === '/api/timeline/31') throw httpError(409); }});
  await ui.sandbox.editStudioScene(11, 31);
  Object.assign(ui.values, typed);
  await ui.sandbox.saveStudioSceneEdit();
  ui.sandbox.cancelStudioSceneEdit();
  assert.doesNotMatch(ui.messages.at(-1)[0], /giữ nguyên như trước/);
  assert.match(ui.messages.at(-1)[0], /có thể đã ghi một phần/);
});

test('a field already on the server as wanted is not sent again', async () => {
  const ui = board();
  await ui.sandbox.editStudioScene(11, 31);
  ui.db.shots[0].visual_prompt = 'Hình đã gõ';
  Object.assign(ui.values, {studioSceneEditVisual: 'Hình đã gõ'});
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.writes().map((c) => c.url), ['/api/timeline/31']);
  assert.equal(ui.messages.at(-1)[1], 'success');
});

// ---------------------------------------------------------------------------
// A full redraw of the long board while a scene is being edited (audit P2-1)
// ---------------------------------------------------------------------------
// The real path: renderStudioStoryboard -> renderStudioSceneBoard, which replaces
// #studioStoryboardResult (the form inside it goes with it) and then draws the
// detail again. A scene job finishing, a new sort, clearing the filters and a
// refresh all redraw this way. The DOM here does what the browser does: setting
// a container's innerHTML destroys the elements inside it, and a field's value
// is what the user typed into that very element, or else what its HTML says.

const liveCode = [
  code,
  constant('STORYBOARD_PROD_FILTERS'), constant('STORYBOARD_SORTS'), constant('STORYBOARD_ATTENTION'), constant('STORYBOARD_PLAN_ATTENTION'),
  ...['renderStudioStoryboard', 'renderStudioSceneBoard', 'storyboardSceneRow', 'storyboardStripBlock', 'applyStudioStoryboardFilters',
    'setStudioStoryboardView', 'clearStudioStoryboardFilters', 'syncStudioScenePlanState'].map(fn),
].join('\n');

const unescapeHtml = (text) => text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');

function liveBoard() {
  const calls = [];
  const messages = [];
  const db = {shots: SHOTS.map((s) => ({...s})), timeline: TIMELINE.map((t) => ({...t}))};
  let typed = {};                       // what the user typed into the fields drawn right now
  let detailHtml = '';
  const detail = {
    get innerHTML() { return detailHtml; },
    set innerHTML(html) { detailHtml = html; typed = {}; },   // new fields: nothing typed in them yet
    scrollIntoView() {},
  };
  let resultHtml = '';
  const result = {
    get innerHTML() { return resultHtml; },
    set innerHTML(html) { resultHtml = html; detailHtml = ''; typed = {}; },   // the old detail and its form are gone
    contains: () => false,
    querySelector: () => null,
  };
  const field = (id) => {
    if (!detailHtml.includes(`id="${id}"`)) return null;
    return {
      get value() {
        if (id in typed) return typed[id];
        const area = detailHtml.match(new RegExp(`<textarea id="${id}"[^>]*>([\\s\\S]*?)</textarea>`));
        if (area) return unescapeHtml(area[1]);
        const input = detailHtml.match(new RegExp(`<input id="${id}"[^>]*value="([^"]*)"`));
        return input ? unescapeHtml(input[1]) : '';
      },
      focus() {}, setSelectionRange() {},
    };
  };
  const sandbox = {
    state: {studioProjectId: 7, shots: db.shots.map((s) => ({...s})), timeline: db.timeline.map((t) => ({...t})), storyboardView: null, studioEditDocument: null},
    $: (id) => {
      if (id === 'studioStoryboardResult') return result;
      if (id === 'studioSceneDetail') return resultHtml.includes('id="studioSceneDetail"') ? detail : null;
      if (id === 'studioSceneEditForm') return detailHtml.includes('id="studioSceneEditForm"') ? {} : null;
      if (['studioSceneEditNarration', 'studioSceneEditVisual', 'studioSceneEditDuration'].includes(id)) return field(id);
      return null;
    },
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      const call = {url, method, body: options.body ? JSON.parse(options.body) : null};
      calls.push(call);
      if (method === 'GET') return {latest_shots: db.shots.map((s) => ({...s})), latest_timeline: db.timeline.map((t) => ({...t}))};
      const target = url.startsWith('/api/shots/') ? db.shots.find((s) => `/api/shots/${s.id}` === url) : db.timeline.find((t) => `/api/timeline/${t.id}` === url);
      Object.assign(target, call.body);
      return url.startsWith('/api/shots/') ? {status: 'saved', shot: {...target}} : {status: 'saved', segment: {...target}};
    },
    refreshStudioEditDocument: () => Promise.resolve(null),
    narrationSourceNotice: () => '',
    storyboardSegmentForShot: (shot, timeline) => timeline.find((t) => Number(t.shot_id) === Number(shot.id)) || null,
    storyboardSceneFacts: () => ({state: 'ready', label: 'Sẵn sàng', ready: true, missingVisual: false, missingAudio: false}),
    storyboardSceneParts: () => ({preview: '<img>', body: '<div class="storyboard-body-parts"></div>', wantsVisual: false}),
    findStudioShot: (id) => sandbox.state.shots.find((s) => Number(s.id) === Number(id)) || null,
    editStudioScenePrompt: async () => { calls.push({url: 'prompt-dialogs', method: 'PROMPT'}); },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    confirm: () => true,
    document: {querySelectorAll: () => [], querySelector: () => null, activeElement: null},
    window: {matchMedia: () => ({matches: false}), scrollY: 0, scrollTo() {}},
    Promise, JSON, Math, Number, String, Object, Array, Boolean, Error, Set, RegExp,
  };
  vm.createContext(sandbox);
  vm.runInContext(liveCode, sandbox);
  sandbox.renderStudioStoryboard(sandbox.state.shots, sandbox.state.timeline);
  return {
    sandbox, calls, messages, db, detail,
    type: (id, value) => { assert.ok(field(id), `${id} is on screen`); typed[id] = value; },
    writes: () => calls.filter((c) => c.method !== 'GET'),
  };
}

const redraws = {
  'a scene job finishing (renderStudioStoryboard from the server)': (ui) => ui.sandbox.renderStudioStoryboard(ui.sandbox.state.shots, ui.sandbox.state.timeline),
  'a new sort (setStudioStoryboardView)': (ui) => ui.sandbox.setStudioStoryboardView({sort: 'duration'}),
  'clearing the filters (clearStudioStoryboardFilters)': (ui) => ui.sandbox.clearStudioStoryboardFilters(),
};

for (const [what, redraw] of Object.entries(redraws)) {
  test(`what is being typed in the scene form survives ${what}, and nothing is written`, async () => {
    const ui = liveBoard();
    await ui.sandbox.editStudioScene(11, 31);
    ui.type('studioSceneEditVisual', 'Chữ đang gõ dở');
    ui.type('studioSceneEditDuration', '7');
    ui.sandbox.markStudioSceneEditDirty();
    redraw(ui);
    assert.match(ui.detail.innerHTML, /id="studioSceneEditForm"/, 'the form is drawn again');
    assert.match(ui.detail.innerHTML, /<textarea id="studioSceneEditVisual" rows="3">Chữ đang gõ dở<\/textarea>/, 'the typed picture is kept');
    assert.match(ui.detail.innerHTML, /<input id="studioSceneEditDuration"[^>]*value="7"/, 'the typed length is kept');
    const edit = ui.sandbox.state.storyboardEdit;
    assert.ok(edit && edit.dirty && !edit.saving);
    assert.equal(edit.original.visual, 'Đồi cây phong', 'what "changed" means does not move');
    assert.equal(ui.writes().length, 0, 'a redraw never writes');
    const change = ui.sandbox.studioSceneEditChanges(edit);
    assert.equal(change.visual, 'Chữ đang gõ dở');
    assert.ok(change.visualChanged && change.durationChanged);
  });
}

test('after a redraw the save sends what was typed, not the scene as it was', async () => {
  const ui = liveBoard();
  await ui.sandbox.editStudioScene(11, 31);
  ui.type('studioSceneEditVisual', 'Chữ đang gõ dở');
  ui.sandbox.markStudioSceneEditDirty();
  ui.sandbox.renderStudioStoryboard(ui.sandbox.state.shots, ui.sandbox.state.timeline);
  await ui.sandbox.saveStudioSceneEdit();
  assert.deepEqual(ui.writes().map((c) => [c.method, c.url, c.body]), [
    ['PATCH', '/api/shots/11', {visual_prompt: 'Chữ đang gõ dở'}],
    ['PATCH', '/api/timeline/31', {visual_prompt: 'Chữ đang gõ dở'}],
  ]);
  assert.deepEqual(ui.messages.at(-1), ['Đã lưu cảnh này. Giọng đọc của cảnh được giữ nguyên.', 'success']);
});

test('a redraw keeps the draft only while the form is open: cancelling still goes back to the scene as it was', async () => {
  const ui = liveBoard();
  await ui.sandbox.editStudioScene(11, 31);
  ui.type('studioSceneEditVisual', 'Chữ đang gõ dở');
  ui.sandbox.renderStudioStoryboard(ui.sandbox.state.shots, ui.sandbox.state.timeline);
  ui.sandbox.cancelStudioSceneEdit();
  ui.sandbox.renderStudioStoryboard(ui.sandbox.state.shots, ui.sandbox.state.timeline);
  assert.equal(ui.sandbox.state.storyboardEdit, null);
  assert.doesNotMatch(ui.detail.innerHTML, /studioSceneEditForm|Chữ đang gõ dở/);
  assert.equal(ui.writes().length, 0);
});
