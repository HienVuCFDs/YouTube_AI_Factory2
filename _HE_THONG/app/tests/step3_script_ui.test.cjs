// Bước 3 · Kịch bản, run for real: the block of project-detail.js that draws
// it, against a scripted server. What the page shows is what the server said -
// the ScriptDocument, its state, whether production may go on from it, and why
// not in the server's own words - and what it sends is the step's contract:
// one POST to …/steps/script, a PATCH of the words, nothing from the old writer.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/project-detail.js'), 'utf8');
const START = '  // ---- Bước 3 · Kịch bản ----';
const END = '  // ---- hết Bước 3 · Kịch bản ----';
const code = page.slice(page.indexOf(START), page.indexOf(END));

// The backend's own words (script_engine.CONTINUE_MESSAGES and the plan refusals of
// the script step); tests/test_step3_ui.py checks the server really answers with them.
const SAID = {
  missing: 'Chưa có kịch bản viết từ Kế hoạch hiện tại. Hãy viết kịch bản trước khi tiếp tục.',
  stale: 'Kịch bản này thuộc một kế hoạch cũ. Hãy viết lại kịch bản trước khi tiếp tục.',
  invalid: 'Kịch bản hiện tại không còn hợp lệ với kế hoạch. Hãy viết lại kịch bản trước khi tiếp tục.',
  mismatch: 'Kịch bản hiện tại không khớp với kế hoạch hiện tại.',
  running: 'Kịch bản đang được tạo. Vui lòng chờ lượt hiện tại hoàn tất.',
  no_plan: 'Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản.',
  needs_user_decision: 'Kế hoạch hiện cần bạn quyết định trước khi viết kịch bản.',
  blocked: 'Kế hoạch hiện chưa thể thực hiện, chưa thể viết kịch bản.',
  plan_stale: 'Kế hoạch đã cũ vì dữ liệu bên dưới đã thay đổi. Hãy lập lại kế hoạch ở Bước 2 trước khi viết kịch bản.',
  busy: 'Bước Viết kịch bản đang chạy cho dự án này. Chờ lượt đó xong rồi hãy chạy lại.',
};
const STAGES = [['read_plan', 'Đọc kế hoạch'], ['write', 'Viết lời'], ['check', 'Kiểm tra kịch bản'], ['finalize', 'Hoàn thiện kịch bản']]
  .map(([key, label]) => ({key, label}));
const going = (stage) => ({run_id: 'r1', started_at: new Date().toISOString(), stage,
  stage_label: STAGES.find((item) => item.key === stage).label, stages: STAGES});

const line = (text, speaker = 'narrator') => ({speaker, text});
const DOCUMENT = {
  title: 'Vì sao Trái Đất quay', language: 'vi', target_duration_seconds: 100, estimated_seconds: 98,
  plan: {plan_id: 16, plan_version: 5, primary_angle_id: 'ang-2'},
  hook: {plan_section_id: 's1', spoken_lines: [line('Bạn có biết vì sao có ngày và đêm?')], on_screen_text: ['Ngày và đêm'], estimated_seconds: 4},
  sections: [
    {id: 'sec-1', plan_section_id: 's1', name: 'Mở đầu', budget_seconds: 10, estimated_seconds: 6,
      spoken_lines: [line('Mỗi sáng mặt trời mọc ở phía đông.')], on_screen_text: [], insight_ids: ['in-1'], evidence_ids: ['ev-aaaaaaaaaa']},
    {id: 'sec-2', plan_section_id: 's2', name: 'Thân bài', budget_seconds: 24, estimated_seconds: 25,
      spoken_lines: [line('Trái Đất tự quay quanh trục của nó.'), line('Đúng vậy, mỗi vòng mất một ngày.', 'khách mời')],
      on_screen_text: ['Một vòng = 24 giờ'], insight_ids: [], evidence_ids: []},
    {id: 'sec-3', plan_section_id: 's3', name: 'Kết', budget_seconds: 19, estimated_seconds: 18,
      spoken_lines: [line('Nhờ vậy ta có ngày và đêm.')], on_screen_text: [], insight_ids: [], evidence_ids: []},
  ],
  cta: {plan_section_id: 's3', spoken_lines: [line('Mời bạn xem phần tiếp theo.')], on_screen_text: [], estimated_seconds: 4},
  missing_information: [], limitations: ['Chưa có số liệu về tốc độ quay.'],
};
const PLAN_OK = {id: 16, version: 5, status: 'completed'};
const script = (over = {}) => ({
  id: 98, project_id: 7, version: 1, variant: 'long', plan_id: 16, plan_version: 5, engine_version: 'script-phase1',
  script_title: 'Vì sao Trái Đất quay', hook: 'Bạn có biết vì sao có ngày và đêm?',
  main_content: 'Mỗi sáng mặt trời mọc ở phía đông.\nTrái Đất tự quay quanh trục của nó.', cta: 'Mời bạn xem phần tiếp theo.',
  status: 'draft', approval_status: 'draft', document: DOCUMENT, state: 'completed', stale: false, stale_reasons: [], stale_kind: '',
  invalid: false, validation_errors: [], current: true, blocked_reason: '', write_blocked_reason: '', current_plan: PLAN_OK,
  generation: {status: 'idle', run: null, last_run: null}, ...over,
});
const missing = (over = {}) => ({project_id: 7, status: 'missing', state: 'missing', stale: false, document: null,
  generation: {status: 'idle', run: null, last_run: null}, current_plan: PLAN_OK, current: false,
  blocked_reason: SAID.missing, write_blocked_reason: '', ...over});
const row = (state, more = {}) => ({key: 'script', state, missing: [], ...more});

function studio({steps, body, post, patch} = {}) {
  const server = {row: steps || row('ready'), body: body || missing(), post, patch};
  const calls = [];
  const messages = [];
  const timers = [];
  const shorts = [];
  const lanes = [];
  const narration = [];
  const element = (extra = {}) => ({innerHTML: '', value: '', disabled: false, hidden: false, title: '', checked: false, ...extra});
  const elements = {
    studioScriptHead: element(), studioScriptResult: element({scrollIntoView() {}}), studioToRenderButton: element(),
    studioGenerateStoryboardButton: element(), studioChatBox: element({hidden: true}), studioCreateStandaloneShort: element({checked: true}),
    studioShortScriptSeconds: element({value: '45'}), studioWriterProviderSelect: element({value: 'auto'}),
    studioProjectSummary: element(), studioScriptSummary: element(),
  };
  const tab = {dataset: {}};
  const sandbox = {
    state: {studioProjectId: 7, studioStep: 3, studioWorkflow: 'content'},
    $: (id) => elements[id] || null,
    document: {hidden: false, addEventListener() {}, querySelector: (selector) => (selector.includes('data-studio-tab="3"') ? tab : null)},
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      calls.push({url, method, body: options.body ? JSON.parse(options.body) : null});
      if (method === 'POST' && url.endsWith('/steps/script')) return server.post ? server.post(server) : {result: {}};
      if (method === 'PATCH') return server.patch ? server.patch(server) : {};
      if (method === 'POST') return {};
      if (url.endsWith('/steps')) return {steps: [server.row]};
      if (url.endsWith('/script')) return server.body;
      throw new Error(`unexpected ${method} ${url}`);
    },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    formatStudioDuration: (total) => `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(Math.round(total) % 60).padStart(2, '0')}`,
    studioPlanWhen: (value) => String(value || ''),
    STUDIO_PLAN_LANGUAGES: {vi: 'Tiếng Việt', en: 'Tiếng Anh'},
    syncStudioNarrationLanguage: (language) => narration.push(language),
    saveRenderSettings: async () => {},
    loadShortLane: async () => { lanes.push('loaded'); },
    writeShortScript: async () => { shorts.push('written'); },
    setStudioLaneTab() {}, loadProjects: async () => {}, setStudioStep() {},
    confirm: () => true,
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout() {},
    Date, Promise, JSON, Math, Number, String, Object, Set, Boolean, Array,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const posts = () => calls.filter((call) => call.method !== 'GET');
  return {sandbox, server, calls, posts, messages, timers, shorts, lanes, narration, tab, elements,
    head: () => elements.studioScriptHead.innerHTML, body: () => elements.studioScriptResult.innerHTML};
}

const nothingFromTheOldWriter = (calls) => {
  for (const call of calls) {
    assert.ok(!call.url.includes('/writer'), call.url);
    assert.ok(!call.url.includes('/script/draft'), call.url);
    assert.ok(!call.url.includes('director-draft'), call.url);
    assert.ok(!JSON.stringify(call.body || {}).includes('force'), call.url);
  }
};

test('with no script the page offers to write one, and opening the step sends nothing', async () => {
  const ui = studio();
  assert.equal(await ui.sandbox.loadStudioScript(7), false);
  assert.match(ui.head(), /Chưa có kịch bản/);
  assert.match(ui.head(), /onclick="writeStudioScript\(\)">Viết kịch bản<\/button>/);
  assert.equal(ui.body(), '');
  assert.equal(ui.elements.studioToRenderButton.disabled, true);
  assert.equal(ui.posts().length, 0);
});

test('one click is one POST to the step, with only the options it takes - no writer, no draft adapter', async () => {
  const ui = studio({post: (server) => { server.body = script(); server.row = row('done', {last_run: {status: 'success'}}); return {step: 'script', result: {}}; }});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.writeStudioScript();
  const posts = ui.posts();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/projects/7/steps/script');
  assert.deepEqual(posts[0].body, {options: {create_standalone_short: true, short_seconds: 45}});
  nothingFromTheOldWriter(ui.calls);
  // What was written is read back from the server, not taken from the reply.
  assert.ok(ui.calls.at(-1).url.endsWith('/script') || ui.calls.at(-2).url.endsWith('/script'));
  assert.match(ui.head(), /status-badge green">Sẵn sàng</);
  assert.deepEqual(ui.messages.at(-1), ['Đã viết kịch bản từ Kế hoạch.', 'success']);
  assert.deepEqual(ui.narration, ['vi'], 'the voice follows the language of the script');
});

test('the AI chosen in Nâng cao is passed through; auto leaves the choice to the server', async () => {
  const ui = studio({post: () => ({result: {}})});
  ui.elements.studioWriterProviderSelect.value = 'claude_code_cli';
  ui.elements.studioCreateStandaloneShort.checked = false;
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.writeStudioScript();
  assert.deepEqual(ui.posts()[0].body, {options: {create_standalone_short: false, short_seconds: 45, provider: 'claude_code_cli'}});
});

test('a second click while the script is being written sends nothing', async () => {
  let release;
  const ui = studio({post: () => new Promise((resolve) => { release = resolve; })});
  await ui.sandbox.loadStudioScript(7);
  const first = ui.sandbox.writeStudioScript();
  assert.match(ui.head(), /Đang viết kịch bản…/);
  assert.match(ui.head(), /<button class="btn primary" type="button" disabled>Đang viết…<\/button>/);
  await ui.sandbox.writeStudioScript();
  await ui.sandbox.writeStudioScript();
  assert.equal(ui.posts().length, 1, 'no second run');
  ui.server.body = script();
  release({result: {}});
  await first;
  assert.match(ui.head(), /Sẵn sàng/);
});

test('a run found on the server after a reload is shown as running, and finishing brings the script in', async () => {
  const ui = studio({steps: row('running', {run: going('write')}), body: missing({generation: {status: 'running', run: going('write')}})});
  assert.equal(await ui.sandbox.loadStudioScript(7), true, 'a reopened project stops at step three');
  assert.match(ui.head(), /Đang viết kịch bản…/);
  assert.match(ui.head(), /<span class="studio-plan-stage now">Viết lời<\/span>/);
  assert.match(ui.head(), /<span class="studio-plan-stage ">Đọc kế hoạch<\/span>/, 'a stage the page did not see run is not marked done');
  assert.equal(ui.timers.length, 1, 'the server is asked again later');
  await ui.sandbox.writeStudioScript();
  assert.equal(ui.posts().length, 0, 'no second run');
  ui.server.row = row('done', {last_run: {status: 'success'}});
  ui.server.body = script();
  await ui.timers[0]();
  assert.match(ui.head(), /Sẵn sàng/);
  assert.match(ui.body(), /Trái Đất tự quay quanh trục của nó\./);
});

test('a run that failed elsewhere is reported in the server\'s words once it ends', async () => {
  const ui = studio({steps: row('running', {run: going('check')}), body: missing({generation: {status: 'running'}})});
  await ui.sandbox.loadStudioScript(7);
  ui.server.row = row('ready', {last_run: {status: 'failed', status_code: 409, error: SAID.plan_stale}});
  ui.server.body = missing({generation: {status: 'failed', last_run: {status: 'failed', error: SAID.plan_stale}}});
  await ui.timers[0]();
  assert.deepEqual(ui.messages.at(-1), [SAID.plan_stale, 'error']);
  assert.ok(ui.head().includes(SAID.plan_stale));
});

test('a completed script is shown as its ScriptDocument, in its own order', async () => {
  const ui = studio({body: script()});
  await ui.sandbox.loadStudioScript(7);
  const head = ui.head();
  const body = ui.body();
  assert.match(head, /status-badge green">Sẵn sàng</);
  for (const text of ['Phiên bản 1', 'viết theo Kế hoạch v5', 'chưa duyệt']) assert.ok(head.includes(text), text);
  assert.match(head, />Chỉnh sửa</);
  assert.match(head, />Tạo Short</);
  for (const text of ['Tiếng Việt', '01:40', '01:38', 'v1', 'v5', 'HOOK', 'Bạn có biết vì sao có ngày và đêm?', 'Ngày và đêm', 'CTA',
    'Mời bạn xem phần tiếp theo.', 'Chữ trên màn hình', 'Một vòng = 24 giờ', '<b>khách mời:</b>', 'Chưa có số liệu về tốc độ quay.']) {
    assert.ok(body.includes(text), text);
  }
  // Sections in the document's order, each with its id and its seconds.
  const order = ['Mở đầu', 'Thân bài', 'Kết'].map((name) => body.indexOf(`<b>${name}</b>`));
  assert.ok(order.every((at) => at > 0) && order[0] < order[1] && order[1] < order[2], String(order));
  for (const text of ['· s1 · 00:06 / 00:10 theo kế hoạch', '· s2 · 00:25 / 00:24 theo kế hoạch', '· s3 · 00:18 / 00:19 theo kế hoạch']) {
    assert.ok(body.includes(text), text);
  }
  // What a section rests on is kept, folded.
  assert.match(body, /<summary>Dựa trên<\/summary>[\s\S]*in-1[\s\S]*ev-aaaaaaaaaa/);
  // Words, not a storyboard.
  const visible = body.slice(0, body.indexOf('studio-advanced-json'));
  for (const gone of ['visual_prompt', 'camera', 'b-roll', 'shot', 'blueprint', 'new_titles', 'hashtag']) {
    assert.ok(!visible.toLowerCase().includes(gone), gone);
  }
  assert.equal(ui.elements.studioToRenderButton.disabled, false, 'only a current script opens the next steps');
  assert.equal(ui.elements.studioGenerateStoryboardButton.disabled, false);
  assert.equal(ui.elements.studioChatBox.hidden, false);
  assert.equal(ui.tab.dataset.scriptState, 'completed');
});

for (const [name, over, label, reason] of [
  ['stale', {state: 'stale', stale: true, stale_kind: 'stale', stale_reasons: ['Kế hoạch đã thay đổi sau khi viết kịch bản'], current: false,
    blocked_reason: SAID.stale, current_plan: {id: 17, version: 6, status: 'completed'}}, 'Kịch bản đã cũ', 'Kế hoạch đã thay đổi sau khi viết kịch bản'],
  ['mismatch', {state: 'stale', stale: true, stale_kind: 'mismatch', stale_reasons: ['Kịch bản này không được viết bằng Script Engine'], current: false,
    blocked_reason: SAID.mismatch}, 'Không khớp kế hoạch', 'Kịch bản này không được viết bằng Script Engine'],
  ['invalid', {state: 'invalid', invalid: true, validation_errors: ['Kịch bản nói điều Kế hoạch yêu cầu tránh'], current: false,
    blocked_reason: SAID.invalid}, 'Không còn hợp lệ', 'Kịch bản nói điều Kế hoạch yêu cầu tránh'],
]) {
  test(`${name}: the server's words, its reasons, and a rewrite - nothing after Bước 3 opens`, async () => {
    const ui = studio({body: script(over)});
    await ui.sandbox.loadStudioScript(7);
    const head = ui.head();
    assert.ok(head.includes(`>${label}<`), label);
    assert.ok(head.includes(over.blocked_reason), 'the gate\'s message, word for word');
    assert.ok(head.includes(reason), 'and what the server listed');
    assert.match(head, /onclick="writeStudioScript\(\)">Viết lại kịch bản<\/button>/);
    assert.ok(!head.includes('>Tạo Short<'));
    if (name !== 'invalid') assert.ok(!head.includes('>Chỉnh sửa<'));
    assert.equal(ui.elements.studioToRenderButton.disabled, true);
    assert.equal(ui.elements.studioToRenderButton.title, over.blocked_reason);
    assert.equal(ui.elements.studioGenerateStoryboardButton.disabled, true);
    if (name === 'stale') assert.ok(head.includes('Kế hoạch hiện tại v6'), 'which plan is current now');
  });
}

for (const [plan, label, said] of [
  ['needs_user_decision', 'Kế hoạch cần bạn quyết định', SAID.needs_user_decision],
  ['blocked', 'Kế hoạch chưa thể thực hiện', SAID.blocked],
  ['stale', 'Kế hoạch đã cũ', SAID.plan_stale],
  [null, 'Chưa có kế hoạch', SAID.no_plan],
]) {
  test(`with the plan ${plan || 'missing'}, writing is refused in the server's words and nothing is sent`, async () => {
    const ui = studio({body: missing({current_plan: plan ? {id: 16, version: 5, status: plan} : null, write_blocked_reason: said})});
    await ui.sandbox.loadStudioScript(7);
    assert.ok(ui.head().includes(`>${label}<`), label);
    assert.ok(ui.head().includes(said));
    assert.ok(!ui.head().includes('writeStudioScript()'), 'no button to write');
    await ui.sandbox.writeStudioScript();
    assert.equal(ui.posts().length, 0);
    assert.deepEqual(ui.messages.at(-1), [said, 'error']);
  });
}

test('a 409 from the step is shown in its own words, not as a general error', async () => {
  const ui = studio({post: () => { throw Object.assign(new Error(SAID.plan_stale), {status: 409}); }});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.writeStudioScript();
  assert.deepEqual(ui.messages.at(-1), [SAID.plan_stale, 'error']);
  assert.ok(ui.head().includes(SAID.plan_stale));
  assert.ok(!ui.messages.some(([text]) => /Có lỗi xảy ra/.test(text)));
});

test('a 409 because another run is going: the page follows that run instead', async () => {
  const ui = studio({post: (server) => {
    server.row = row('running', {run: going('write')});
    throw Object.assign(new Error(SAID.busy), {status: 409});
  }});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.writeStudioScript();
  assert.deepEqual(ui.messages.at(-1), [SAID.busy, 'error']);
  assert.match(ui.head(), /Đang viết kịch bản…/);
  assert.ok(ui.timers.length >= 1);
});

test('editing sends only the words, and the state after it is read back from the server', async () => {
  const ui = studio({body: script(), patch: (server) => {
    server.body = script({state: 'invalid', invalid: true, current: false, blocked_reason: SAID.invalid,
      validation_errors: ['Kịch bản nói điều Kế hoạch yêu cầu tránh']});
    return {status: 'saved', state: 'invalid'};
  }});
  await ui.sandbox.loadStudioScript(7);
  ui.sandbox.editStudioScript();
  const editor = ui.body();
  for (const id of ['studioScriptTitleInput', 'studioScriptHookInput', 'studioScriptMainInput', 'studioScriptCtaInput']) assert.ok(editor.includes(`id="${id}"`), id);
  for (const owned of ['plan_id', 'plan_version', 'angle', 'target_duration', 'platform', 'aspect_ratio', 'studioScriptIntroInput']) {
    assert.ok(!editor.includes(owned), owned);
  }
  Object.assign(ui.elements, {
    studioScriptTitleInput: {value: 'Tiêu đề mới'}, studioScriptHookInput: {value: 'Hook mới'},
    studioScriptMainInput: {value: 'Một dòng mới'}, studioScriptCtaInput: {value: 'CTA mới'},
  });
  await ui.sandbox.saveStudioScript();
  const patch = ui.posts().find((call) => call.method === 'PATCH');
  assert.equal(patch.url, '/api/scripts/98');
  assert.deepEqual(Object.keys(patch.body).sort(), ['cta', 'hook', 'main_content', 'script_title']);
  // Saved is not the same as still valid: the page says what the server now says.
  assert.match(ui.head(), />Không còn hợp lệ</);
  assert.deepEqual(ui.messages.at(-1), [SAID.invalid, 'error']);
  assert.equal(ui.elements.studioToRenderButton.disabled, true);
});

test('with the editor closed, saving sends nothing', async () => {
  const ui = studio({body: script()});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.saveStudioScript();
  assert.equal(ui.posts().length, 0);
});

test('a Short is made only from a script the server calls current', async () => {
  const ui = studio({body: script()});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.createStudioShort();
  assert.deepEqual(ui.shorts, ['written']);
  const stale = studio({body: script({state: 'stale', current: false, blocked_reason: SAID.stale})});
  await stale.sandbox.loadStudioScript(7);
  await stale.sandbox.createStudioShort();
  assert.deepEqual(stale.shorts, []);
  assert.deepEqual(stale.messages.at(-1), [SAID.stale, 'error']);
});

test('a Short written beside the long script is loaded; one that failed is reported', async () => {
  const ui = studio({post: (server) => { server.body = script(); return {result: {short: {script: {id: 99}}, short_error: ''}}; }});
  await ui.sandbox.loadStudioScript(7);
  await ui.sandbox.writeStudioScript();
  assert.deepEqual(ui.lanes, ['loaded']);
  const failed = studio({post: (server) => { server.body = script(); return {result: {short: null, short_error: 'Không lưu được kịch bản short'}}; }});
  await failed.sandbox.loadStudioScript(7);
  await failed.sandbox.writeStudioScript();
  assert.match(failed.messages.at(-1)[0], /Không lưu được kịch bản short$/);
});

// ---- The Short lane (studio-lanes.js): what the Short was made from, and whether it still holds ----
const lanes = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/studio-lanes.js'), 'utf8');
const laneCode = lanes.slice(lanes.indexOf('  function renderShortLane('), lanes.indexOf('  function stopShortVoiceSequence('));

function shortLane(shortScript) {
  const button = (onclick) => {
    const node = {disabled: false, title: '', dataset: {}, getAttribute: (name) => (name === 'onclick' ? onclick : null)};
    return node;
  };
  const buttons = [button("queueShortVariantJob('voiceover')"), button('cutShortSourceScenes()'), button("queueShortVariantJob('source_visuals')"),
    button("openPublishDialog('short')"), button('writeShortScript()')];
  const view = {innerHTML: ''};
  const render = {disabled: false, title: '', textContent: '', dataset: {}, getAttribute: () => 'queueShortVariantJob(\'render_short\')'};
  const sandbox = {
    state: {studioProjectId: 7, shortScript, studioWorkflow: 'content'},
    $: (id) => ({studioShortScriptView: view, studioRenderShortButton: render}[id] || null),
    document: {querySelectorAll: () => buttons},
    esc: (value) => String(value ?? ''), syncStudioLaneTabs() {}, renderShortVoiceReview() {}, renderStudioStoryboard() {},
    encodeURIComponent, JSON, Number, String, Boolean, Set,
  };
  vm.createContext(sandbox);
  vm.runInContext(laneCode, sandbox);
  return {sandbox, buttons, view, render};
}

const lane = {script: {id: 99, script_title: 'Bản Short', hook: 'Hook', main_content: 'Một câu', cta: ''}, scenes: 2, voiced: 2, with_visuals: 2,
  can_render: true, estimated_seconds: 30, shots: [], timeline: []};

test('a Short made from the current script says what it came from and stays open', () => {
  const ui = shortLane({script: {id: 99}, current: true, blocked_reason: '',
    provenance: {kind: 'short_provenance', source_script_id: 98, source_script_version: 1, plan_id: 16, plan_version: 5}});
  ui.sandbox.renderShortLane(lane);
  assert.match(ui.view.innerHTML, /Viết từ kịch bản v1 · Kế hoạch v5/);
  assert.ok(!ui.view.innerHTML.includes(SAID.stale));
  assert.equal(ui.render.disabled, false);
  assert.ok(ui.buttons.every((item) => !item.disabled));
});

test('a Short from an earlier script is held: the server\'s words, and every step after it locked - but it can be written again', () => {
  const said = 'Short này được tạo từ một phiên bản kịch bản cũ. Hãy tạo lại Short từ kịch bản hiện tại.';
  const ui = shortLane({script: {id: 99}, current: false, blocked_reason: said,
    provenance: {kind: 'short_provenance', source_script_id: 98, source_script_version: 1, plan_id: 16, plan_version: 5}});
  ui.sandbox.renderShortLane(lane);
  assert.ok(ui.view.innerHTML.includes(said));
  assert.equal(ui.render.disabled, true);
  assert.equal(ui.render.title, said);
  for (const item of ui.buttons.slice(0, 4)) assert.equal(item.disabled, true, item.getAttribute('onclick'));
  assert.equal(ui.buttons[4].disabled, false, 'writing the Short again stays open');
  // Written again from the current script: the lock comes off.
  ui.sandbox.state.shortScript = {script: {id: 99}, current: true, blocked_reason: '', provenance: null};
  ui.sandbox.renderShortLane(lane);
  assert.equal(ui.buttons[0].disabled, false);
  assert.equal(ui.buttons[3].disabled, false);
});
