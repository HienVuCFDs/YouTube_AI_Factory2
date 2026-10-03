// Bước 2 · Kế hoạch, run for real: the block of project-detail.js that draws
// it, against a scripted server. What the page shows is what the server said -
// the status, the decisions, the angles, the four groups of resources - and
// what it sends is the existing step contract and nothing else.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/project-detail.js'), 'utf8');
const START = '  // ---- Bước 2 · Kế hoạch ----';
const END = '  // ---- hết Bước 2 · Kế hoạch ----';
const code = page.slice(page.indexOf(START), page.indexOf(END));

// The stages as the backend names them (project_planner.STAGES).
const STAGES = [['read_analysis', 'Đọc phân tích'], ['research', 'Nghiên cứu dữ liệu'], ['insights', 'Phân tích insight'],
  ['angles', 'Tìm góc nội dung'], ['strategy', 'Xây dựng chiến lược'], ['feasibility', 'Kiểm tra tính khả thi'],
  ['finalize', 'Hoàn thiện kế hoạch']].map(([key, label]) => ({key, label}));
const going = (stage) => ({run_id: 'r1', started_at: new Date().toISOString(), stage,
  stage_label: STAGES.find((item) => item.key === stage).label, stages: STAGES});
const chip = (html, label) => {
  const match = html.match(new RegExp(`<span class="studio-plan-stage ([a-z]*)">${label}( · giữ nguyên)?</span>`));
  assert.ok(match, label);
  return match[1] + (match[2] ? '+kept-label' : '');
};

const angle = (id, statement) => ({
  id, statement, target_audience: `Người xem của ${id}`, need_or_problem: 'Muốn câu trả lời ngắn',
  supporting_insight_ids: ['in-1'], differentiation: 'Trả lời thẳng', platform_fit: 'Hợp video ngắn', risks: ['Dễ nói quá'],
  support_confidence: 'high',
});

function bundle(over = {}) {
  const plan = {
    source_kind: 'video', video_type: 'giải thích nhanh', platform: 'youtube', aspect_ratio: '16:9',
    output_profile: 'youtube_landscape', language: 'vi', target_duration_seconds: 60, target_duration_from: 'ai_proposed',
    target_audience: 'Người mới tìm hiểu', goal: 'Giữ người xem tới cuối',
    primary_angle: angle('ang-1', 'Trả lời câu hỏi người xem hay hỏi nhất'), primary_angle_id: 'ang-1',
    alternative_angles: [angle('ang-3', 'Góc thứ ba'), angle('ang-2', 'Đặt lại chủ đề thành một câu hỏi')],
    hook_strategy: 'Mở bằng chính câu người xem hay hỏi',
    content_structure: [
      {name: 'Mở đầu', purpose: 'Giữ người xem', estimated_seconds: 8, key_points: ['Nêu câu hỏi'], insight_ids: ['in-1'], evidence_ids: []},
      {name: 'Thân bài', purpose: 'Trả lời', estimated_seconds: 40, key_points: ['Ý một', 'Ý hai'], insight_ids: [], evidence_ids: []},
      {name: 'Kết', purpose: 'Chốt', estimated_seconds: 12, key_points: [], insight_ids: [], evidence_ids: []},
    ],
    media_strategy: {primary_sources: ['ai_media'], supporting_sources: ['graphics'], notes: 'Hình minh hoạ là chính'},
    edit_direction: {pacing: 'nhanh', cut_style: 'cắt thẳng', transitions: 'ít', text_animation: 'chữ bật', subtitle_style: 'chữ lớn',
      callouts: 'khoanh số', zoom_punch_in: 'ở câu mở', broll_usage: 'minh hoạ', graphics: 'một biểu đồ', average_shot_length_seconds: 3.5},
    subtitle_strategy: 'Phụ đề đầy đủ', music_strategy: 'Nhạc nhẹ', sfx_strategy: 'Ít hiệu ứng', cta: 'Mời xem tiếp',
    factual_guardrails: ['Giá chỉ đúng lúc đọc'], claims_to_avoid: ['Không nói rẻ nhất'], claims_needing_proof: [],
    limitations: ['Chưa có dữ liệu giữ chân'],
    ...over.plan,
  };
  return {
    project_id: 7,
    plan: {id: 31, version: 2, status: 'completed', effective_status: 'completed', created_at: '2026-10-02T08:00:00+00:00',
      plan, feasibility: {status: 'ok', checks: [{key: 'duration_budget', status: 'ok', detail: 'Các phần cộng lại 60 giây.'}], adjustments: []},
      ...over.row},
    research_report: {report: {coverage: {videos: 8, comments_sampled: 150, articles: 2, product_pages: 0},
      limitations: ['2/8 video tìm được ít liên quan tới chủ đề.'],
      failed_sources: [{collector: 'web.search', source: 'https://chan.test/403', reason: "Client error '403 Forbidden'", collector_status: 'blocked'}]}},
    insight_report: {report: {
      insights: [{id: 'in-1', type: 'audience_question', statement: 'Người xem trong mẫu hỏi về giá.', confidence: 'high', evidence_ids: ['ev-aaaaaaaaaa']}],
      hypotheses: [{statement: 'Có thể làm thành loạt bài.'}],
      evidence_index: {'ev-aaaaaaaaaa': {source_kind: 'comment_sample', title: 'Video A', source_url: 'https://youtube.com/watch?v=a', sample_size: 100}},
    }},
    resources: {
      available: [{category: 'source_footage', label: 'Cảnh quay từ nguồn', detail: 'nguồn có 62 giây hình'}],
      app_generates: [{label: 'Kịch bản', source: 'plan'}, {label: 'Giọng đọc', source: 'plan'}, {label: 'Phụ đề', source: 'plan'}],
      missing: [], proposed: [], reviewed: true,
    },
    stages: STAGES,
    ...over.bundle,
  };
}

const row = (state, outcome, more = {}) => ({key: 'plan', state, missing: [], ...(outcome ? {outcome} : {}), ...more});
const outcome = (status, more = {}) => ({status, completed: status === 'completed', reason: '', decisions: [], plan_id: 31, plan_version: 2, ...more});

function studio({steps, plan, post, video, kind = 'video', analysis} = {}) {
  const server = {row: steps || row('ready'), bundle: plan === undefined ? bundle({bundle: {plan: null}}) : plan, post};
  const calls = [];
  const messages = [];
  const timers = [];
  const elements = {
    studioPlanHead: {innerHTML: ''}, studioPlanBody: {innerHTML: ''}, studioToScriptButton: {disabled: false, title: ''},
    studioPlanProfile: {value: ''}, studioPlanSeconds: {value: ''},
  };
  const tab = {dataset: {}, flags: {}, classList: {toggle(name, on) { tab.flags[name] = Boolean(on); }}};
  const clock = (total) => `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(Math.round(total) % 60).padStart(2, '0')}`;
  const sandbox = {
    state: {studioProjectId: 7, studioStep: 2, studioAnalysis: {result: analysis || {topic: 'Trái Đất quay'}}},
    $: (id) => elements[id] || null,
    document: {hidden: false, addEventListener() {}, querySelector: (selector) => (selector.includes('data-studio-tab="2"') ? tab : null)},
    api: async (url, options = {}) => {
      const method = options.method || 'GET';
      calls.push({url, method, body: options.body ? JSON.parse(options.body) : null});
      if (method === 'POST') return server.post ? server.post(server) : {};
      return url.endsWith('/steps') ? {steps: [server.row]} : server.bundle;
    },
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    setMessage: (text, type = '') => messages.push([text, type]),
    studioSelectedVideo: () => (video === null ? null : (video || {title: 'Trái Đất được tạo ra như thế nào?', duration_seconds: 62})),
    studioSourceKind: () => ({kind, label: {video: 'Video', product: 'Sản phẩm', audio: 'Audio', article: 'Bài viết'}[kind], platform: 'YouTube'}),
    studioSourceHost: () => 'vnexpress.net',
    studioPlainText: (text) => String(text || '').replace(/HTTP\s*\d{3}\s*:?\s*/gi, '').trim(),
    studioProse: (text) => String(text || '').trim(),
    studioMoney: (value, text) => String(text || value || ''),
    formatStudioDuration: clock,
    setStudioStep() {},
    syncStudioScriptGate() {},
    PUBLISH_PROFILE_LABELS: {youtube_landscape: 'YouTube ngang · 16:9', youtube_shorts: 'YouTube Shorts · 9:16', tiktok: 'TikTok · 9:16'},
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout() {},
    Date, Promise, JSON, Math, Number, String, Object, URL, Set, Boolean,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const posts = () => calls.filter((call) => call.method === 'POST');
  return {sandbox, server, calls, posts, messages, timers, tab, head: () => elements.studioPlanHead.innerHTML,
    body: () => elements.studioPlanBody.innerHTML, next: elements.studioToScriptButton, elements};
}

const group = (html, title) => {
  const start = html.indexOf(title);
  assert.notEqual(start, -1, title);
  return html.slice(start, html.indexOf('</div>', html.indexOf('</h3>', start)));
};

test('with no plan the page says so and offers to make one', async () => {
  const ui = studio();
  assert.equal(await ui.sandbox.loadStudioPlan(7), false);
  assert.match(ui.head(), /Chưa lập kế hoạch/);
  assert.match(ui.head(), /onclick="startStudioPlan\(\)">Lập kế hoạch<\/button>/);
  assert.equal(ui.body(), '');
  assert.equal(ui.next.disabled, true);
  assert.doesNotMatch(ui.head(), /Sẵn sàng/);
  assert.equal(ui.posts().length, 0, 'opening the step starts nothing');
});

test('a source that was not analysed is sent back to step one, not planned', async () => {
  const ui = studio({steps: row('blocked', null, {missing: ['analyze']})});
  await ui.sandbox.loadStudioPlan(7);
  assert.match(ui.head(), /Phân tích nguồn trước/);
  assert.doesNotMatch(ui.head(), /startStudioPlan/);
});

test('a run found on the server after a reload is shown as running and cannot be started twice', async () => {
  const running = row('running', null, {run: going('insights')});
  const ui = studio({steps: running});
  assert.equal(await ui.sandbox.loadStudioPlan(7), true, 'a reopened project stops at step two');
  assert.match(ui.head(), /Đang lập kế hoạch…/);
  assert.match(ui.head(), /<button class="btn primary" type="button" disabled>Đang lập kế hoạch…<\/button>/);
  assert.equal(chip(ui.head(), 'Phân tích insight'), 'now');
  // The page did not see the earlier stages run, so it does not say they did.
  assert.equal(chip(ui.head(), 'Nghiên cứu dữ liệu'), '');
  assert.ok(!ui.head().includes('giữ nguyên'));
  assert.equal(ui.timers.length, 1, 'the server is asked again later');
  await ui.sandbox.startStudioPlan();
  assert.equal(ui.posts().length, 0, 'no second run');

  // The server finishes: the next ask brings the plan in.
  ui.server.row = row('done', outcome('completed'), {last_run: {status: 'success'}});
  ui.server.bundle = bundle();
  await ui.timers[0]();
  assert.match(ui.head(), /Sẵn sàng/);
  assert.match(ui.body(), /GÓC ĐANG CHỌN/);
  assert.deepEqual(ui.messages.at(-1), ['Đã lập kế hoạch.', 'success']);
});

test('a completed plan is shown whole: summary, angles, structure, production, resources', async () => {
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle()});
  assert.equal(await ui.sandbox.loadStudioPlan(7), true);
  const head = ui.head();
  const body = ui.body();
  assert.match(head, /status-badge green">Sẵn sàng</);
  assert.match(head, /Chọn góc khác/);
  assert.match(head, /Lập lại kế hoạch/);
  for (const text of ['Giữ người xem tới cuối', 'Người mới tìm hiểu', 'YouTube', 'giải thích nhanh', '01:00 (app đề xuất)', '16:9', 'Tiếng Việt',
    'Mở bằng chính câu người xem hay hỏi', '00:00–00:08', '00:08–00:48', '00:48–01:00', 'Tổng 01:00 · mục tiêu 01:00',
    'Mục tiêu: Giữ người xem', 'Hình AI', 'Đồ hoạ', 'Phụ đề đầy đủ', 'Nhạc nhẹ', 'Mời xem tiếp', 'Giá chỉ đúng lúc đọc', 'Không nói rẻ nhất']) {
    assert.ok(body.includes(text), text);
  }
  // A strategy, not a storyboard.
  for (const gone of ['shot 0', 'Shot 0', 'camera', 'prompt']) assert.ok(!body.toLowerCase().includes(gone.toLowerCase()), gone);
  // Only a completed plan finishes the step.
  assert.equal(ui.next.disabled, false);
  assert.equal(ui.tab.dataset.planState, 'completed');
});

test('the angles are choices, not a ranking, and the chosen one is marked', async () => {
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle()});
  await ui.sandbox.loadStudioPlan(7);
  const body = ui.body();
  assert.equal(body.split('GÓC ĐANG CHỌN').length - 1, 1);
  assert.equal(body.split('>Chọn góc này<').length - 1, 2, 'one button per angle that is not the chosen one');
  assert.deepEqual([...body.matchAll(/data-angle="(ang-\d)"/g)].map((match) => match[1]), ['ang-1', 'ang-2', 'ang-3'], 'in the order of their ids');
  for (const text of ['Người xem của ang-2', 'Muốn câu trả lời ngắn', 'Trả lời thẳng', 'Hợp video ngắn', 'Dễ nói quá', 'Người xem trong mẫu hỏi về giá.']) {
    assert.ok(body.includes(text), text);
  }
  // Raw data lives only under Nâng cao; nothing on show ranks or scores the angles.
  const shown = body.slice(0, body.indexOf('<details class="studio-advanced-json">'));
  for (const ranked of ['tốt nhất', 'Top 1', 'support_confidence', 'điểm số', 'xếp hạng']) assert.ok(!shown.includes(ranked), ranked);
});

test('choosing an angle sends primary_angle_id and nothing that would research again', async () => {
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle(), post: (server) => {
    server.bundle = bundle({plan: {primary_angle: angle('ang-2', 'Đặt lại chủ đề thành một câu hỏi'), primary_angle_id: 'ang-2',
      alternative_angles: [angle('ang-1', 'Trả lời câu hỏi người xem hay hỏi nhất'), angle('ang-3', 'Góc thứ ba')]}});
    return {};
  }});
  await ui.sandbox.loadStudioPlan(7);
  await ui.sandbox.chooseStudioPlanAngle('ang-2');
  assert.deepEqual(ui.posts().map((call) => [call.url, call.body]), [['/api/projects/7/steps/plan', {options: {primary_angle_id: 'ang-2'}}]]);
  assert.match(ui.body(), /data-angle="ang-2">\s*<span class="tag green">GÓC ĐANG CHỌN/);
  assert.deepEqual(ui.messages.at(-1), ['Đã lập kế hoạch.', 'success']);
});

test('an angle the server refuses leaves the plan as it was and says why in plain words', async () => {
  const refuse = (status, message) => () => { throw Object.assign(new Error(message), {status}); };
  for (const [status, message, shown] of [
    [409, 'Chưa có insight dùng lại được (Có báo cáo nghiên cứu mới hơn). Chạy mode=reason để phân tích lại.', 'Dữ liệu của kế hoạch đã thay đổi'],
    [400, 'Không có góc nội dung ang-9 trong báo cáo insight hiện tại. Chọn một trong: ang-1, ang-2.', 'Góc này không còn trong danh sách'],
  ]) {
    const ui = studio({steps: row('done', outcome('completed')), plan: bundle(), post: refuse(status, message)});
    await ui.sandbox.loadStudioPlan(7);
    const before = ui.body();
    await ui.sandbox.chooseStudioPlanAngle('ang-2');
    assert.equal(ui.body(), before, 'the plan on screen is untouched');
    assert.ok(ui.head().includes(shown), shown);
    for (const raw of ['mode=', '409', '400', 'insight hiện tại']) assert.ok(!ui.head().includes(raw), raw);
    assert.match(ui.head(), /Sẵn sàng/, 'the plan itself is still what it was');
  }
});

test('a plan waiting on a decision shows the decision and its options, and does not finish the step', async () => {
  const waiting = outcome('needs_user_decision', {feasibility: 'needs_attention', reason: 'Các phần cộng lại 110 giây.', decisions: [
    {key: 'duration_budget', detail: 'Các phần cộng lại 110 giây trong khi mục tiêu là 60 giây (lệch 83%).',
      options: ['Rút gọn cấu trúc còn khoảng 60 giây', 'Đổi thời lượng mục tiêu thành khoảng 110 giây']}]});
  const ui = studio({steps: row('needs_user_decision', waiting), plan: bundle({row: {status: 'needs_user_decision', effective_status: 'needs_user_decision'}})});
  assert.equal(await ui.sandbox.loadStudioPlan(7), true);
  assert.match(ui.head(), /status-badge orange">Cần bạn quyết định</);
  assert.match(ui.head(), /Giải quyết vấn đề/);
  assert.doesNotMatch(ui.head(), /Sẵn sàng/);
  const body = ui.body();
  assert.ok(body.startsWith('<section id="studioPlanDecisions"'), 'what needs deciding comes first');
  for (const text of ['Cần bạn quyết định', 'lệch 83%', 'Rút gọn cấu trúc còn khoảng 60 giây', 'Đổi thời lượng mục tiêu thành khoảng 110 giây', 'App không tự chọn thay bạn']) {
    assert.ok(body.includes(text), text);
  }
  assert.equal(ui.next.disabled, true);
  assert.equal(ui.tab.dataset.planState, 'needs_user_decision');
  assert.equal(ui.tab.flags.done, false);
  assert.equal(ui.posts().length, 0, 'nothing is chosen for the person');
});

test('a blocked plan and a stale plan do not finish the step either', async () => {
  const blocked = outcome('blocked', {decisions: [{key: 'source_footage', detail: 'Kế hoạch dùng cảnh quay từ nguồn nhưng nguồn không có hình để cắt.', options: ['Chọn loại tư liệu khác làm chính']}]});
  const stuck = studio({steps: row('blocked', blocked), plan: bundle({row: {status: 'blocked', effective_status: 'blocked'}})});
  await stuck.sandbox.loadStudioPlan(7);
  assert.match(stuck.head(), /status-badge red">Chưa thể thực hiện</);
  assert.match(stuck.head(), />Thử lại</);
  assert.ok(stuck.body().includes('nguồn không có hình để cắt'));
  assert.equal(stuck.next.disabled, true);

  const old = studio({steps: row('stale', outcome('stale', {reason: 'Có báo cáo nghiên cứu mới hơn'})), plan: bundle({row: {effective_status: 'stale', stale: true}})});
  await old.sandbox.loadStudioPlan(7);
  assert.match(old.head(), /Kế hoạch đã cũ/);
  assert.match(old.head(), /Có báo cáo nghiên cứu mới hơn/);
  assert.match(old.head(), /onclick="startStudioPlan\(\)">Lập lại kế hoạch</);
  assert.equal(old.next.disabled, true);
  assert.equal(old.body().split('disabled onclick="chooseStudioPlanAngle').length - 1, 2, 'an angle cannot be chosen on a stale plan');
  await old.sandbox.startStudioPlan();
  assert.deepEqual(old.posts()[0].body, {options: {mode: 'auto'}});
});

test('resources are the four groups the server made; a proposal is never shown as missing', async () => {
  const resources = {
    available: [{category: 'source_footage', label: 'Cảnh quay từ nguồn', detail: 'nguồn có 62 giây hình'}],
    app_generates: [{label: 'Giọng đọc', source: 'plan'}, {label: 'Phụ đề', source: 'plan'}, {label: 'Nhạc nền', source: 'plan'}],
    missing: [{asset: 'Ảnh sản phẩm thực tế', category: 'user_images', why: 'Cần cho phần mở hộp', required: true, source: 'ai_confirmed'}],
    proposed: [{asset: 'Tài liệu kiểm chứng', why: 'Để đối chiếu', category: 'reference', required_by_ai: true, note: ''}],
    reviewed: true,
  };
  const ui = studio({steps: row('needs_user_decision', outcome('needs_user_decision')), plan: bundle({bundle: {resources}})});
  await ui.sandbox.loadStudioPlan(7);
  const body = ui.body();
  assert.ok(group(body, 'Đã có').includes('Cảnh quay từ nguồn'));
  assert.ok(group(body, 'App sẽ tự tạo').includes('Giọng đọc'));
  const need = group(body, 'Cần bổ sung');
  assert.ok(need.includes('Ảnh sản phẩm thực tế') && need.includes('BẮT BUỘC'));
  assert.ok(!need.includes('Tài liệu kiểm chứng'), 'what the model proposed and nobody could check is not "missing"');
  assert.ok(!need.includes('Giọng đọc'));
  assert.ok(group(body, 'Chưa xác minh').includes('Tài liệu kiểm chứng'));

  const none = studio({steps: row('done', outcome('completed')), plan: bundle({bundle: {resources: {...resources, missing: []}}})});
  await none.sandbox.loadStudioPlan(7);
  assert.ok(group(none.body(), 'Cần bổ sung').includes('Không thiếu tư liệu nào.'));
  assert.ok(!none.body().includes('studio-plan-resource need'));
});

test('each kind of source is described as what it is', () => {
  const product = studio({kind: 'product', analysis: {source_facts: {price: '9999', price_text: '9.999₫', captured_at: '2026-09-30T10:59:45+00:00'}}});
  assert.match(product.sandbox.studioPlanSourceLine('product', product.sandbox.state.studioAnalysis.result), /^giá 9\.999₫ \(đọc lúc /);
  assert.equal(product.sandbox.studioPlanSourceLine('product', {source_facts: {}}), 'chưa đọc được giá');
  const other = studio();
  assert.equal(other.sandbox.studioPlanSourceLine('audio', {}), 'âm thanh 01:02, không có hình');
  assert.equal(other.sandbox.studioPlanSourceLine('article', {}), 'vnexpress.net');
  assert.equal(other.sandbox.studioPlanSourceLine('web', {}), 'vnexpress.net');
  assert.equal(other.sandbox.studioPlanSourceLine('video', {}), 'video 01:02');
  assert.equal(other.sandbox.studioPlanSourceLine('image_collection', {}), '');
});

test('a failed run is told in plain words and can be tried again', async () => {
  const ui = studio({post: () => { throw Object.assign(new Error('AI chưa chạy được bước Phân tích insight. Traceback (most recent call last): codex_cli exit 1'), {status: 502}); }});
  await ui.sandbox.loadStudioPlan(7);
  await ui.sandbox.startStudioPlan();
  assert.match(ui.head(), /Chưa lập được kế hoạch/);
  assert.match(ui.head(), /AI lập kế hoạch chưa chạy được lúc này\. Thử lại sau ít phút\./);
  assert.match(ui.head(), />Thử lại</);
  for (const raw of ['Traceback', '502', 'codex_cli']) assert.ok(!ui.head().includes(raw), raw);
  assert.deepEqual(ui.messages.at(-1), ['AI lập kế hoạch chưa chạy được lúc này. Thử lại sau ít phút.', 'error']);
  assert.equal(ui.next.disabled, true);
});

test('a run already going elsewhere is followed instead of reported as a failure', async () => {
  const ui = studio({post: (server) => {
    server.row = row('running', null, {run: going('strategy')});
    throw Object.assign(new Error('Bước Lập kế hoạch đang chạy cho dự án này. Chờ lượt đó xong rồi hãy chạy lại.'), {status: 409});
  }});
  await ui.sandbox.loadStudioPlan(7);
  await ui.sandbox.startStudioPlan();
  assert.deepEqual(ui.messages.at(-1), ['Đang có một lần lập kế hoạch khác.', 'error']);
  assert.match(ui.head(), /Đang lập kế hoạch…/);
  assert.equal(chip(ui.head(), 'Xây dựng chiến lược'), 'now');
  // Somebody else's run: the page cannot know it kept the research, and does not say so.
  assert.ok(!ui.head().includes('giữ nguyên'));
  assert.ok(ui.timers.length >= 1, 'that run is watched until it ends');
});

// A re-plan by angle or by settings reuses the stored research and insights on
// the server. What is on screen while it runs must not read as if they ran again.
async function replanInFlight(start) {
  let finish;
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle(), post: (server) => new Promise((resolve) => {
    server.row = row('running', outcome('completed'), {run: going('strategy')});
    finish = () => { server.row = row('done', outcome('completed')); resolve({}); };
  })});
  await ui.sandbox.loadStudioPlan(7);
  const run = start(ui);
  await new Promise((resolve) => setImmediate(resolve));
  const first = ui.head();
  await ui.timers.at(-1)();   // the server is asked while the request is still open
  const during = ui.head();
  finish();
  await run;
  return {ui, first, during};
}

for (const [name, start, sent] of [
  ['choosing an angle', (ui) => ui.sandbox.chooseStudioPlanAngle('ang-2'), {primary_angle_id: 'ang-2'}],
  ['changing the settings', (ui) => { ui.elements.studioPlanProfile.value = 'youtube_landscape'; ui.elements.studioPlanSeconds.value = '45'; return ui.sandbox.applyStudioPlanSettings(); },
    {mode: 'replan', settings: {target_duration_seconds: 45}}],
]) {
  test(`${name} shows a re-plan, with research and insights kept - not run again`, async () => {
    const {ui, first, during} = await replanInFlight(start);
    assert.deepEqual(ui.posts()[0].body, {options: sent});
    for (const head of [first, during]) {
      assert.match(head, /Đang lập lại kế hoạch…/);
      assert.doesNotMatch(head, /Đang lập kế hoạch…/);
      assert.match(head, /Nghiên cứu và insight hiện tại được giữ nguyên; app chỉ lập lại phần kế hoạch\./);
      for (const kept of ['Nghiên cứu dữ liệu', 'Phân tích insight', 'Tìm góc nội dung']) assert.equal(chip(head, kept), 'kept+kept-label', kept);
      assert.doesNotMatch(head, /2–3 phút/);
    }
    assert.equal(chip(during, 'Xây dựng chiến lược'), 'now');
    assert.equal(chip(during, 'Kiểm tra tính khả thi'), '');
    // Nothing reused is ever shown as running or as having just run.
    for (const reused of ['Nghiên cứu dữ liệu', 'Phân tích insight', 'Tìm góc nội dung']) {
      assert.ok(!['now', 'past'].includes(chip(during, reused)), reused);
    }
    assert.match(ui.head(), /Sẵn sàng/);
    assert.ok(!ui.head().includes('studio-plan-running'), 'the progress goes when the run ends');
  });
}

test('a full run marks only the stages the page saw the server reach', async () => {
  let finish;
  const ui = studio({post: (server) => new Promise((resolve) => {
    server.row = row('running', null, {run: going('research')});
    finish = () => { server.row = row('done', outcome('completed')); server.bundle = bundle(); resolve({}); };
  })});
  await ui.sandbox.loadStudioPlan(7);
  const run = ui.sandbox.startStudioPlan();
  await new Promise((resolve) => setImmediate(resolve));
  await ui.timers.at(-1)();
  assert.match(ui.head(), /Đang lập kế hoạch…/);
  assert.equal(chip(ui.head(), 'Nghiên cứu dữ liệu'), 'now');
  ui.server.row = row('running', null, {run: going('strategy')});
  await ui.timers.at(-1)();
  const head = ui.head();
  assert.equal(chip(head, 'Nghiên cứu dữ liệu'), 'past', 'seen running a moment ago');
  assert.equal(chip(head, 'Phân tích insight'), '', 'never seen: nothing is claimed about it');
  assert.equal(chip(head, 'Xây dựng chiến lược'), 'now');
  assert.ok(!head.includes('giữ nguyên') && head.includes('2–3 phút'));
  finish();
  await run;
});

test('changing the length or the format re-plans with only what was changed', async () => {
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle()});
  await ui.sandbox.loadStudioPlan(7);
  ui.elements.studioPlanProfile.value = 'youtube_landscape';
  ui.elements.studioPlanSeconds.value = '60';
  await ui.sandbox.applyStudioPlanSettings();
  assert.equal(ui.posts().length, 0, 'nothing changed, nothing sent');
  ui.elements.studioPlanSeconds.value = '45';
  await ui.sandbox.applyStudioPlanSettings();
  assert.deepEqual(ui.posts()[0].body, {options: {mode: 'replan', settings: {target_duration_seconds: 45}}});

  const old = studio({steps: row('stale', outcome('stale')), plan: bundle()});
  await old.sandbox.loadStudioPlan(7);
  old.elements.studioPlanProfile.value = 'tiktok';
  old.elements.studioPlanSeconds.value = '60';
  await old.sandbox.applyStudioPlanSettings();
  assert.deepEqual(old.posts()[0].body, {options: {mode: 'auto', settings: {output_profile: 'tiktok'}}});
});

test('research is a folded detail in plain words, with nothing technical on show', async () => {
  const ui = studio({steps: row('done', outcome('completed')), plan: bundle()});
  await ui.sandbox.loadStudioPlan(7);
  const body = ui.body();
  const detail = body.slice(body.indexOf('<details class="studio-option-card studio-plan-research">'));
  const shown = detail.slice(0, detail.indexOf('<details class="studio-advanced-json">'));
  for (const text of ['Chi tiết nghiên cứu', '8 video · 150 bình luận mẫu · 2 bài viết đã đọc', 'Câu hỏi của người xem', 'Người xem trong mẫu hỏi về giá.',
    'Video A', 'Bình luận mẫu', 'Phỏng đoán', 'Có thể làm thành loạt bài.', 'Giới hạn nghiên cứu', 'chan.test', 'Giới hạn của kế hoạch']) {
    assert.ok(shown.includes(text), text);
  }
  for (const technical of ['collector_status', 'ev-aaaaaaaaaa', '403', 'Forbidden', 'web.search', 'confidence', 'in-1']) {
    assert.ok(!shown.includes(technical), technical);
  }
  assert.ok(!body.slice(0, body.indexOf('studio-plan-research')).includes('ev-aaaaaaaaaa'), 'no evidence id in the plan itself');
});
