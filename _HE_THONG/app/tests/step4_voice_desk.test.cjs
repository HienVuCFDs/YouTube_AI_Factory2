// Bước 4 · the voice desk, run for real: the block of studio-lanes.js that draws
// the engine cards, the voice list, the "Đang chọn" card, the speed slider, the
// player and the save button, against a scripted page. The desk is a view over
// the form it replaced: what it shows comes from the selects and the server's
// tts_providers, and what it does is set those selects and fire the change a
// dropdown would. It also says little: no catalog, model or tips blocks.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const lanes = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/studio-lanes.js'), 'utf8');
const START = '  const GEMINI_TTS_PROVIDERS';
const END = '  async function selectStudioSharedVoiceSample(key) {';
const code = lanes.slice(lanes.indexOf(START), lanes.indexOf(END));

const FLASH = 'google_gemini_3_8_flash_tts';
const LITE = 'google_gemini_3_8_flash_lite_tts';
const status = (key, value, label, extra = {}) => ({key, status: value, status_label: label, detail: '', ...extra});
const READY = [
  status('edge_tts', 'ready', 'Sẵn sàng', {vendor: 'microsoft', label: 'Edge TTS', model: 'edge-tts'}),
  status(FLASH, 'ready', 'Sẵn sàng', {vendor: 'google', label: 'Gemini 3.8 Flash TTS', model: 'gemini-3.8-flash-tts'}),
  status(LITE, 'ready', 'Sẵn sàng', {vendor: 'google', label: 'Gemini 3.8 Flash-Lite TTS', model: 'gemini-3.8-flash-lite-tts'}),
  status('pyvideotrans', 'ready', 'Sẵn sàng', {vendor: 'pyvideotrans', label: 'pyVideoTrans'}),
  status('voxcpm', 'ready', 'Sẵn sàng', {vendor: 'openbmb', label: 'VoxCPM2'}),
];

function element(id, extra = {}) {
  return {
    id, html: '', listeners: {}, dataset: {}, hidden: false, disabled: false, title: '', className: '', textContent: '', attributes: {},
    set innerHTML(value) { this.html = value; }, get innerHTML() { return this.html; },
    contains: () => false, querySelectorAll: () => [], setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
    ...extra,
  };
}

function selectOf(id, values, chosen) {
  const options = values.map(([value, textContent, dataset = {}, hidden = false]) => ({value, textContent, dataset: {...dataset}, hidden, disabled: false}));
  const events = [];
  const select = element(id, {options, value: chosen, events, dispatchEvent(event) { events.push(event.type); return true; }});
  // Accessors defined on the object itself (a spread would freeze them into plain values).
  Object.defineProperties(select, {
    selectedOptions: {get() { return options.filter((option) => option.value === this.value); }},
    selectedIndex: {get() { return options.findIndex((option) => option.value === this.value); }, set(index) { this.value = options[index]?.value; }},
  });
  return select;
}

const RATES = [['-25%', 'Rất chậm · -25%'], ['-15%', 'Chậm · -15%'], ['-8%', 'Hơi chậm · -8%'], ['+0%', 'Bình thường · 0%'],
  ['+8%', 'Hơi nhanh · +8%'], ['+15%', 'Nhanh · +15%'], ['+25%', 'Rất nhanh · +25%']];

function desk({provider = FLASH, voice = 'vi-vn-advisor-6', style = '', projectId = 78, tts = READY, voices, catalog, busy = false, saved, rate = '+0%'} = {}) {
  const providers = selectOf('studioVoiceProviderSelect', [
    ['edge_tts', 'Edge TTS · cloud/online'], [FLASH, 'Gemini 3.8 Flash TTS · biểu cảm'], [LITE, 'Gemini 3.8 Flash-Lite TTS · nhanh, tiết kiệm'],
    ['pyvideotrans', 'pyVideoTrans · local GPU'], ['voxcpm', 'VoxCPM2 · local GPU · đa ngôn ngữ'],
  ], provider);
  const voiceSelect = selectOf('studioVoiceModelSelect', voices || [
    ['vi-vn-advisor-6', 'Authoritative Advisor 6 · male · Storyteller', {name: 'Authoritative Advisor 6', gender: 'male', persona: 'Storyteller', description: 'Calm voice'}],
    ['vi-vn-advisor-1', 'Authoritative Advisor 1 · female', {name: 'Authoritative Advisor 1', gender: 'female'}],
    ['vi-vn-tutor-2', 'Tutor 2', {name: 'Tutor 2'}],
    ['Kore', 'Kore · giọng đã chọn', {outside: '1'}],
    ['vi-VN-HoaiMyNeural', 'Tiếng Việt · HoaiMy · Nữ', {name: 'HoaiMy', gender: 'female', locale: 'vi-VN'}, true],
  ], voice);
  const chip = (attr, value, textContent) => element('', {dataset: {[attr]: value}, textContent});
  const styleChips = [chip('voiceStyle', 'Giọng kể chuyện tự nhiên, ấm áp.', 'Kể chuyện'), chip('voiceStyle', 'Giọng bản tin.', 'Tin tức')];
  const genderChips = ['', 'male', 'female', 'other'].map((value) => chip('voiceGender', value, value || 'Tất cả'));
  const bar = element('studioVoicePreviewBar', {firstElementChild: {style: {}}});
  const elements = Object.fromEntries([
    providers, voiceSelect, bar,
    element('studioVoiceStyleInput', {value: style, events: [], dispatchEvent(event) { this.events.push(event.type); }}),
    selectOf('studioVoiceRateSelect', RATES, rate),
    selectOf('studioPublishLanguageSelect', [['vi', 'Tiếng Việt']], 'vi'),
    selectOf('studioSubtitleModelSelect', [['timeline', 'Dùng lời thoại từ timeline · khuyên dùng'], ['faster-whisper-small', 'Faster-Whisper small · nhanh']], 'timeline'),
    element('studioVoiceEngineCards'), element('studioVoiceLocalChoice'), element('studioVoiceList'), element('studioVoiceListCount'),
    element('studioVoiceCatalogNotice'), element('studioVoiceCurrent'), element('studioVoiceSavedBadge'), element('studioVoiceProjectNotice'),
    element('studioVoiceAdvancedSummary'), element('studioVoiceTechDetail'), element('studioSaveVoiceButton'), element('studioVoiceSearch'),
    element('studioVoiceRateRange', {value: '3', max: '6'}), element('studioVoiceRateLabel'), element('studioVoicePreviewTime'),
  ].map((item) => [item.id, item]));
  const playButton = element('', {innerHTML: '', classList: {toggle() {}}});
  const state = {studioProjectId: projectId, productionQueue: {tts_providers: tts}, geminiCatalog: catalog, geminiVoicesBusy: busy};
  const context = {
    state, Event: class { constructor(type) { this.type = type; } }, console, URL: {revokeObjectURL() {}},
    $: (id) => elements[id] || null,
    esc: (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[c])),
    voiceLocaleLabel: (locale) => ({'vi-VN': 'Tiếng Việt'}[locale] || locale),
    loadGeminiVoices: () => Promise.resolve(),
    setMessage() {},
    document: {
      activeElement: null,
      querySelector: (selector) => selector === '[onclick="previewStudioSelectedVoice()"]' ? playButton : null,
      querySelectorAll: (selector) => selector === '[data-voice-style]' ? styleChips : selector === '[data-voice-gender]' ? genderChips : [],
    },
  };
  vm.createContext(context);
  vm.runInContext(`${code}\nObject.assign(this, {renderStudioVoiceDesk, chooseStudioVoiceEngine, chooseStudioVoice, rememberStudioVoiceSaved,
    studioVoiceErrorParts, studioVoicePreviewWasCached, studioVoiceClock, studioTtsBlocked, previewStudioSelectedVoice, studioVoicePreviewKey});`, context);
  if (saved) context.rememberStudioVoiceSaved(projectId, saved);
  context.renderStudioVoiceDesk();
  return {context, elements, state, styleChips, genderChips, playButton};
}

const SAVED_FLASH = {voice_provider: FLASH, voice_model: 'vi-vn-advisor-6', voice_style: '', voice_rate: '+0%', publish_language: 'vi', subtitle_model: 'timeline'};
const visibleText = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

test('the engines are four compact cards: name, model and the server readiness, nothing more on show', () => {
  const {elements} = desk({tts: [...READY.slice(0, 2), status(LITE, 'quota', 'Hết quota', {detail: 'Hết hạn mức trong ngày'}), ...READY.slice(3)]});
  const html = elements.studioVoiceEngineCards.html;
  assert.equal((html.match(/<button /g) || []).length, 4, 'Edge, Flash, Flash-Lite and one card for the local engines');
  for (const key of ['edge_tts', FLASH, LITE]) assert.match(html, new RegExp(`data-voice-engine="${key}"`));
  assert.match(html, /data-voice-local="1"/);
  assert.match(html, /data-voice-engine="google_gemini_3_8_flash_tts" aria-pressed="true"[\s\S]*?voice-check/);
  assert.match(html, /status-badge red">Hết quota/, 'the server label, with a colour and the word');
  assert.match(html, /data-voice-engine="google_gemini_3_8_flash_lite_tts" aria-pressed="false" disabled aria-label="Google Gemini 3.8 Flash-Lite TTS, Hết quota, không dùng được: Hết hạn mức trong ngày"/);
  assert.equal(visibleText(html), 'E Microsoft Edge TTS Sẵn sàng G Google Gemini 3.8 Flash TTS Sẵn sàng ✓ G Google Gemini 3.8 Flash-Lite TTS Hết quota TTS cục bộ pyVideoTrans / VoxCPM2 ▾',
    'what an engine can do lives in the tooltip, not on the card');
  assert.match(html, /title="Đọc theo Kiểu đọc · Danh mục giọng của Google · Mỗi cảnh một giọng · Tính phí theo token"/);
});

test('the local card opens its engines without choosing one; choosing one is the provider change', () => {
  const {context, elements, state} = desk({provider: 'edge_tts'});
  assert.equal(elements.studioVoiceLocalChoice.hidden, true);
  const handler = elements.studioVoiceEngineCards.listeners.click[0];
  handler({target: {closest: () => ({dataset: {voiceLocal: '1'}, disabled: false})}});
  assert.equal(state.studioVoiceLocalOpen, true);
  assert.equal(elements.studioVoiceLocalChoice.hidden, false);
  assert.deepEqual(elements.studioVoiceProviderSelect.events, [], 'opening the list is not a change of engine');
  assert.match(elements.studioVoiceLocalChoice.html, /data-voice-engine="pyvideotrans"[\s\S]*data-voice-engine="voxcpm"/);
  elements.studioVoiceLocalChoice.listeners.click[0]({target: {closest: () => ({dataset: {voiceEngine: 'voxcpm'}, disabled: false})}});
  assert.deepEqual([elements.studioVoiceProviderSelect.value, elements.studioVoiceProviderSelect.events], ['voxcpm', ['change']]);
  context.renderStudioVoiceDesk();
  assert.match(elements.studioVoiceEngineCards.html, /data-voice-local="1" aria-expanded="true"[\s\S]*VoxCPM2[\s\S]*Sẵn sàng/);
});

test('only a definite readiness locks a card: a local probe still running does not', () => {
  const tts = READY.map((item) => ({...item, status: 'not_configured', status_label: 'Chưa cấu hình', detail: 'x'}));
  const {elements, context} = desk({tts, provider: 'voxcpm', voices: [['preset:female_warm', 'Nữ ấm áp · kể chuyện', {gender: 'female'}]], voice: 'preset:female_warm'});
  assert.match(elements.studioVoiceEngineCards.html, /data-voice-engine="edge_tts" aria-pressed="false" disabled/);
  assert.doesNotMatch(elements.studioVoiceLocalChoice.html, /disabled/);
  assert.match(elements.studioVoiceLocalChoice.html, /VoxCPM2[\s\S]*Chưa cấu hình/, 'its status is still shown');
  assert.equal(context.studioTtsBlocked('voxcpm', tts[4]), false);
});

test('a readiness the server has not given yet is said to be checking, never assumed', () => {
  const {elements} = desk({tts: []});
  assert.match(elements.studioVoiceEngineCards.html, /Đang kiểm tra…/);
  assert.doesNotMatch(elements.studioVoiceEngineCards.html, /Sẵn sàng/);
});

test('choosing a card sets the provider select and fires its change, once; a locked card does nothing', () => {
  const {context, elements} = desk({provider: 'edge_tts', tts: [READY[0], READY[1], status(LITE, 'not_configured', 'Chưa cấu hình'), ...READY.slice(3)]});
  const select = elements.studioVoiceProviderSelect;
  context.chooseStudioVoiceEngine(LITE);
  assert.deepEqual([select.value, select.events], ['edge_tts', []]);
  context.chooseStudioVoiceEngine(FLASH);
  assert.deepEqual([select.value, select.events], [FLASH, ['change']]);
  context.chooseStudioVoiceEngine(FLASH);
  assert.deepEqual(select.events, ['change'], 'the same card again is not a change');
});

test('the voice list: name, id and what the catalog said - and only that', () => {
  const {context, elements, state} = desk();
  const list = elements.studioVoiceList.html;
  assert.match(list, /aria-selected="true" data-voice-value="vi-vn-advisor-6"/);
  assert.match(list, /voice-name">Authoritative Advisor 6<\/span><span class="voice-sub"><code>vi-vn-advisor-6<\/code><span class="voice-facts">Nam · Storyteller<\/span>/);
  assert.match(list, /✓ Đang chọn/);
  assert.match(list, /Ngoài danh mục/, 'the project voice the catalog does not list');
  assert.doesNotMatch(list, /HoaiMy/, 'a voice hidden for this engine is not offered');
  assert.match(list, /voice-name">Tutor 2<\/span><span class="voice-sub"><code>vi-vn-tutor-2<\/code><\/span>/, 'no gender or persona made up');
  assert.match(list, /voice-name">Kore<\/span><\/span>/);
  assert.equal(elements.studioVoiceListCount.textContent, '4 giọng');
  state.studioVoiceGender = 'female';
  context.renderStudioVoiceDesk();
  assert.match(elements.studioVoiceList.html, /Authoritative Advisor 1/);
  assert.doesNotMatch(elements.studioVoiceList.html, /Advisor 6|Tutor 2/);
  state.studioVoiceGender = 'other';
  context.renderStudioVoiceDesk();
  assert.match(elements.studioVoiceList.html, /Tutor 2[\s\S]*Kore/, '"Khác" holds voices the catalog gives no gender');
  state.studioVoiceGender = '';
  state.studioVoiceQuery = 'tutor';
  context.renderStudioVoiceDesk();
  assert.equal(elements.studioVoiceListCount.textContent, '1/4 giọng');
});

test('while the Gemini catalog loads, the placeholder is not offered as a voice and nothing can be saved', () => {
  const {elements} = desk({busy: true, voices: [['Kore', 'Kore']], voice: 'Kore'});
  assert.match(elements.studioVoiceList.html, /Đang tải giọng…/);
  assert.doesNotMatch(elements.studioVoiceList.html, /data-voice-value="Kore"/);
  assert.match(elements.studioVoiceCurrent.html, /Đang tải giọng…/);
  assert.equal(elements.studioSaveVoiceButton.disabled, true);
});

test('choosing a voice sets the voice select and fires its change; it saves nothing by itself', () => {
  const {context, elements} = desk({saved: SAVED_FLASH});
  context.chooseStudioVoice('vi-vn-advisor-1');
  assert.deepEqual([elements.studioVoiceModelSelect.value, elements.studioVoiceModelSelect.events], ['vi-vn-advisor-1', ['change']]);
  assert.deepEqual([elements.studioVoiceSavedBadge.textContent, elements.studioVoiceSavedBadge.className, elements.studioVoiceSavedBadge.title],
    ['Chưa lưu', 'status-badge orange', 'Chưa lưu: giọng']);
  context.chooseStudioVoice('no-such-voice');
  assert.equal(elements.studioVoiceModelSelect.value, 'vi-vn-advisor-1');
});

test('"Đang chọn" is three facts - engine, voice, style - and whether the project holds them', () => {
  const {context, elements} = desk({style: 'Giọng kể chuyện tự nhiên, ấm áp.', saved: {...SAVED_FLASH, voice_style: 'Giọng kể chuyện tự nhiên, ấm áp.'}});
  const card = visibleText(elements.studioVoiceCurrent.html);
  assert.equal(card, 'G Google Gemini 3.8 Flash TTS A Authoritative Advisor 6 vi-vn-advisor-6 Nam · Storyteller ✦ Kể chuyện');
  assert.deepEqual([elements.studioVoiceSavedBadge.textContent, elements.studioVoiceSavedBadge.className], ['Đã lưu', 'status-badge green']);
  assert.equal(elements.studioSaveVoiceButton.innerHTML, 'Đã lưu ✓');
  elements.studioVoiceStyleInput.value = 'Giọng thì thầm.';
  context.renderStudioVoiceDesk();
  assert.match(elements.studioVoiceCurrent.html, /✦ Tùy chỉnh/);
  assert.equal(elements.studioVoiceSavedBadge.title, 'Chưa lưu: kiểu đọc');
  assert.match(elements.studioSaveVoiceButton.innerHTML, /Lưu cấu hình/);
});

test('Edge: no style, the speed instead, and the slider is the rate select', () => {
  const {context, elements} = desk({provider: 'edge_tts', voice: 'vi-VN-HoaiMyNeural', style: 'Giọng kể chuyện tự nhiên, ấm áp.', rate: '+8%',
    voices: [['vi-VN-HoaiMyNeural', 'Tiếng Việt · HoaiMy · Nữ', {name: 'HoaiMy', gender: 'female', locale: 'vi-VN'}]]});
  const card = visibleText(elements.studioVoiceCurrent.html);
  assert.match(card, /Microsoft Edge TTS H HoaiMy vi-VN-HoaiMyNeural Nữ · Tiếng Việt Tốc độ · Hơi nhanh · \+8%/);
  assert.doesNotMatch(card, /Kể chuyện/);
  assert.deepEqual([elements.studioVoiceRateRange.value, elements.studioVoiceRateRange.max, elements.studioVoiceRateLabel.textContent], ['4', '6', 'Hơi nhanh · +8%']);
  // Dragging the slider moves the rate select and fires its change.
  elements.studioVoiceRateRange.listeners.input[0]({target: {value: '1'}});
  assert.deepEqual([elements.studioVoiceRateSelect.value, elements.studioVoiceRateSelect.events], ['-15%', ['change']]);
  context.renderStudioVoiceDesk();
  assert.equal(elements.studioVoiceRateLabel.textContent, 'Chậm · -15%');
});

test('with no project open nothing can be saved, and the page says so', () => {
  const {elements} = desk({projectId: null});
  assert.equal(elements.studioVoiceProjectNotice.hidden, false);
  assert.equal(elements.studioSaveVoiceButton.disabled, true);
  assert.equal(elements.studioVoiceSavedBadge.textContent, 'Chưa mở dự án');
});

test('the catalog speaks only when it could not be refreshed, the cause one click away', () => {
  let {elements} = desk({catalog: {total: 40, source: 'api', stale: false, language_code: 'vi-VN', error: ''}});
  assert.equal(elements.studioVoiceCatalogNotice.hidden, true, 'a healthy catalog says nothing');
  ({elements} = desk({catalog: {total: 40, source: 'api', stale: true, language_code: 'vi-VN', error: 'Gemini TTS tạm thời không trả lời được (HTTP 503)'}}));
  assert.equal(elements.studioVoiceCatalogNotice.hidden, false);
  assert.match(elements.studioVoiceCatalogNotice.html, /Đang dùng danh sách giọng gần nhất\.[\s\S]*<details><summary>Chi tiết<\/summary><code>Gemini TTS tạm thời/);
  ({elements} = desk({catalog: {total: 30, source: 'builtin', stale: false, language_code: 'vi-VN', error: ''}}));
  assert.match(elements.studioVoiceCatalogNotice.html, /danh sách giọng dựng sẵn/);
});

test('the technical details are folded away under Nâng cao, with the counts the server gave', () => {
  const {elements} = desk({catalog: {total: 37, source: 'api', stale: false, language_code: 'vi-VN', error: ''}});
  assert.match(elements.studioVoiceTechDetail.html, /Engine: google_gemini_3_8_flash_tts · gemini-3\.8-flash-tts/);
  assert.match(elements.studioVoiceTechDetail.html, /Danh mục: 37 giọng · vi-VN · api/);
  assert.equal(elements.studioVoiceAdvancedSummary.textContent, 'Phụ đề timeline · Tiếng Việt');
  assert.doesNotMatch(elements.studioVoiceTechDetail.html, /đa giọng|nhiều người nói/i, 'two speakers are not offered, so not advertised');
});

test('the desk is not redrawn when nothing changed, so the focus stays where it was', () => {
  const {context, elements} = desk();
  let writes = 0;
  Object.defineProperty(elements.studioVoiceEngineCards, 'innerHTML', {set() { writes += 1; }, get() { return ''; }});
  context.renderStudioVoiceDesk();
  context.renderStudioVoiceDesk();
  assert.equal(writes, 0);
});

test('a style preset only fills the style box, as typing would', () => {
  const {elements, styleChips} = desk();
  const handler = styleChips[0].listeners.click?.[0];
  assert.ok(handler, 'the preset is wired');
  handler();
  assert.equal(elements.studioVoiceStyleInput.value, 'Giọng kể chuyện tự nhiên, ấm áp.');
  assert.deepEqual(elements.studioVoiceStyleInput.events, ['input', 'change']);
});

test('pressing play again on the same choice plays or pauses what is loaded, without asking again', async () => {
  const {context, state} = desk();
  const played = [];
  const audio = {paused: false, ended: false, currentTime: 2, duration: 6, pause() { this.paused = true; played.push('pause'); },
    play() { this.paused = false; played.push('play'); return Promise.resolve(); }};
  state.studioVoiceAudio = audio;
  state.studioVoiceAudioKey = context.studioVoicePreviewKey();
  await context.previewStudioSelectedVoice();
  await context.previewStudioSelectedVoice();
  assert.deepEqual(played, ['pause', 'play'], 'no fetch: the same sample, paused then resumed');
});

test('errors read in the server words without the HTTP tail, which stays available', () => {
  const {context} = desk();
  const said = context.studioVoiceErrorParts('Gemini TTS từ chối yêu cầu (HTTP 400): No matching speaker voice found');
  assert.deepEqual({...said}, {text: 'Gemini TTS từ chối yêu cầu.', detail: '(HTTP 400): No matching speaker voice found'});
  assert.deepEqual({...context.studioVoiceErrorParts('Chưa có GEMINI_API_KEY.')}, {text: 'Chưa có GEMINI_API_KEY.', detail: ''});
});

test('a preview is called cached only when the server dates the file well before its answer', () => {
  const {context} = desk();
  const answer = (modified, date) => ({headers: {get: (name) => ({'last-modified': modified, date}[name] || null)}});
  assert.equal(context.studioVoicePreviewWasCached(answer('Sat, 04 Oct 2026 10:12:01 GMT', 'Sat, 04 Oct 2026 11:30:00 GMT')), true);
  assert.equal(context.studioVoicePreviewWasCached(answer('Sat, 04 Oct 2026 11:29:59 GMT', 'Sat, 04 Oct 2026 11:30:00 GMT')), false);
  assert.equal(context.studioVoicePreviewWasCached(answer(null, null)), false, 'no headers, no claim');
  assert.equal(context.studioVoiceClock(65.4), '01:05');
});

test('walking Gemini → Edge → Gemini comes back to the Gemini voice picked, not the first in the list', () => {
  const sync = lanes.slice(lanes.indexOf('  function syncStudioVoiceModelOptions('), lanes.indexOf('  function syncStudioSubtitleOptions('));
  const edgeGroup = {dataset: {voiceProviders: 'edge_tts pyvideotrans'}};
  const geminiGroup = {dataset: {voiceProviders: `${FLASH} ${LITE}`}};
  const options = [
    ['vi-VN-HoaiMyNeural', edgeGroup], ['vi-VN-NamMinhNeural', edgeGroup],
    ['vi-vn-advisor-1', geminiGroup], ['vi-vn-advisor-6', geminiGroup],
  ].map(([value, parentElement]) => ({value, parentElement, hidden: false, textContent: value, dataset: {}}));
  const voices = {value: 'vi-vn-advisor-6', options, querySelectorAll: () => [edgeGroup, geminiGroup],
    get selectedOptions() { return options.filter((option) => option.value === this.value); }};
  const provider = {value: FLASH};
  const state = {};
  const elements = {studioVoiceModelSelect: voices, studioVoiceProviderSelect: provider, studioPublishLanguageSelect: {value: 'vi'}};
  const context = {
    state, $: (id) => elements[id] || null, ensureStudioNarrationVoices() {}, document: {querySelectorAll: () => []},
    GEMINI_TTS_PROVIDERS: [FLASH, LITE],
    // The desk's own bookkeeping, as renderStudioVoiceDesk does it.
    renderStudioVoiceDesk() {
      const voice = voices.selectedOptions[0];
      if (voice && !voice.hidden) state.studioVoiceByFamily = {...(state.studioVoiceByFamily || {}), [voice.parentElement.dataset.voiceProviders]: voice.value};
    },
  };
  vm.createContext(context);
  vm.runInContext(sync, context);
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-vn-advisor-6');
  provider.value = 'edge_tts';
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-VN-HoaiMyNeural', 'Edge starts on its own first voice');
  voices.value = 'vi-VN-NamMinhNeural';
  context.renderStudioVoiceDesk();
  provider.value = FLASH;
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-vn-advisor-6', 'the Gemini voice is not lost on the way back');
  provider.value = LITE;
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-vn-advisor-6', 'Flash and Lite share their voices');
  provider.value = 'edge_tts';
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-VN-NamMinhNeural', 'and Edge comes back to its own');
  options.find((option) => option.value === 'vi-vn-advisor-6').parentElement = {dataset: {voiceProviders: 'voxcpm'}};
  provider.value = FLASH;
  context.syncStudioVoiceModelOptions();
  assert.equal(voices.value, 'vi-vn-advisor-1', 'a remembered voice no longer listed is not forced back');
});
