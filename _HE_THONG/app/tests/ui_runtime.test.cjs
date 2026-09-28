const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = (name) => fs.readFileSync(path.join(__dirname, '../youtube_monitor/static', name), 'utf8');

test('saved project data loads while optional tool checks remain pending; refreshes coalesce', async () => {
  const page = source('publish.js');
  const code = page.slice(page.indexOf('  let studioRefreshPending'), page.indexOf('  async function queuePendingTranscripts'));
  const counts = {};
  const sandbox = {state: {}, setMessage() {}, Date, Promise};
  for (const name of new Set(code.match(/\bload\w+/g))) {
    sandbox[name] = async () => { counts[name] = (counts[name] || 0) + 1; };
  }
  sandbox.loadToolStatus = () => new Promise(() => {});
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const first = sandbox.refresh();
  assert.equal(sandbox.refresh({poll: true}), first);
  await first;
  assert.equal(counts.loadProjects, 1);
  await sandbox.refresh({poll: true});
  assert.equal(counts.loadProjects, 1);
  assert.equal(counts.loadWorkflows, 1);
});

test('Short playback survives refreshes and reloads only for a different render', () => {
  const page = source('studio-lanes.js');
  const code = page.slice(page.indexOf('  function renderShortLane('), page.indexOf('  function stopShortVoiceSequence('));
  let writes = 0;
  const output = {dataset: {}, querySelector: () => null, set innerHTML(value) { writes++; }};
  const sandbox = {state: {studioProjectId: 43}, $: id => id === 'studioShortFinal' ? output : null,
    document: {querySelectorAll: () => []}, syncStudioLaneTabs() {}, renderShortVoiceReview() {},
    encodeURIComponent};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const lane = {script: {id: 76}, output_path: 'short.mp4', render_version: '133-1'};
  sandbox.renderShortLane(lane);
  sandbox.renderShortLane({...lane, voiced: 3});
  assert.equal(writes, 1);
  sandbox.renderShortLane({...lane, render_version: '154-2'});
  assert.equal(writes, 2);
});

test('German and Spanish select native voices and retain a matching manual choice', () => {
  const core = source('core.js');
  const lanes = source('studio-lanes.js');
  const group = {dataset: {voiceProviders: 'edge_tts pyvideotrans'}};
  const options = ['vi-VN-HoaiMyNeural', 'de-DE-KatjaNeural', 'de-DE-ConradNeural',
    'es-ES-ElviraNeural', 'es-ES-AlvaroNeural'].map(value => ({value, parentElement: group, hidden: false}));
  group.querySelectorAll = () => options;
  const select = {value: 'vi-VN-HoaiMyNeural', options, querySelectorAll: () => [group],
    get selectedOptions() { return options.filter(option => option.value === this.value); }};
  const elements = {studioEdgeVoiceGroup: group, studioVoiceModelSelect: select,
    studioVoiceProviderSelect: {value: 'edge_tts'}, studioPublishLanguageSelect: {value: 'vi'}};
  const sandbox = {$: id => elements[id], document: {querySelectorAll: () => []}};
  vm.createContext(sandbox);
  vm.runInContext(core.slice(core.indexOf('  function ensureStudioNarrationVoices('), core.indexOf('  async function loadWorkflows(')), sandbox);
  vm.runInContext(lanes.slice(lanes.indexOf('  function syncStudioVoiceModelOptions('), lanes.indexOf('  function syncStudioSubtitleOptions(')), sandbox);
  sandbox.syncStudioNarrationLanguage('de');
  assert.equal(select.value, 'de-DE-KatjaNeural');
  select.value = 'de-DE-ConradNeural';
  sandbox.syncStudioNarrationLanguage('de');
  assert.equal(select.value, 'de-DE-ConradNeural');
  sandbox.syncStudioNarrationLanguage('es');
  assert.equal(select.value, 'es-ES-ElviraNeural');
  assert.equal(elements.studioPublishLanguageSelect.value, 'es');
});

test('the target duration box keeps one hh:mm:ss shape', () => {
  const page = source('project-detail.js');
  const code = page.slice(page.indexOf('  function parseStudioDuration('), page.indexOf('  function inferStudioDurationFromPrompt('));
  const input = {value: ''};
  const sandbox = {$: id => id === 'studioTargetDurationSeconds' ? input : null};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const typed = (value) => { input.value = value; sandbox.maskStudioDurationInput(); return input.value; };
  assert.equal(typed('1'), '1');
  assert.equal(typed('0012'), '00:12');
  assert.equal(typed('001230'), '00:12:30');
  assert.equal(typed('00:12:30:99'), '00:12:30');
  assert.equal(typed('ab12cd'), '12');
  // What was on screen is what is kept: 00:12 means twelve minutes.
  input.value = '00:12';
  sandbox.normaliseStudioDurationInput();
  assert.equal(input.value, '00:12:00');
  // A value saved in an older format is read as it was meant.
  sandbox.restoreStudioDurationInput('12:00');
  assert.equal(input.value, '00:12:00');
  sandbox.restoreStudioDurationInput('1 phút 30 giây');
  assert.equal(input.value, '00:01:30');
  assert.equal(sandbox.parseStudioDuration('00:12:30'), 750);
});

test('each step switches between the long video and the Short', () => {
  const page = source('studio-lanes.js');
  const code = page.slice(page.indexOf('  function syncStudioLaneTabs('), page.indexOf('  async function loadShortLane('));
  const node = (extra = {}) => ({hidden: false, dataset: {}, classList: {toggle() {}}, setAttribute() {}, ...extra});
  const tabButtons = ['long', 'short'].map((lane) => {
    const button = node({dataset: {lane}, attributes: {}});
    button.classList = {active: false, toggle(_name, on) { button.active = on; }};
    button.setAttribute = (name, value) => { button.attributes[name] = value; };
    return button;
  });
  const tabs = node({querySelectorAll: () => tabButtons});
  const panes = {long: node(), short: node()};
  const sandbox = {
    state: {}, SHORT_LANE_PANES: ['studioStep3'], wanted: true,
    shortLaneWanted() { return sandbox.wanted; },
    document: {querySelector(selector) {
      if (selector.startsWith('.studio-lane-tabs')) return tabs;
      return selector.includes('data-lane="short"') ? panes.short : panes.long;
    }},
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);

  sandbox.syncStudioLaneTabs();
  assert.equal(tabs.hidden, false);
  assert.equal(panes.long.hidden, false);
  assert.equal(panes.short.hidden, true);

  sandbox.setStudioLaneTab('short');
  assert.equal(panes.long.hidden, true);
  assert.equal(panes.short.hidden, false);
  assert.equal(tabButtons[1].attributes['aria-selected'], 'true');

  // Unticking the Short option closes the tab bar and brings the long video back.
  sandbox.wanted = false;
  sandbox.syncStudioLaneTabs();
  assert.equal(tabs.hidden, true);
  assert.equal(panes.long.hidden, false);
  assert.equal(panes.short.hidden, true);
});
