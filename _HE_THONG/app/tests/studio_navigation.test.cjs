// Moving between the studio's steps. Every way of getting to a step - a tab,
// a "continue" or "back" button, the code that restores a session - calls
// setStudioStep, so the rule lives there: Bước 3 · Kịch bản opens only when
// Bước 2 · Kế hoạch is ready.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/studio-lanes.js'), 'utf8');
const code = page.slice(page.indexOf('  // Kịch bản được viết từ kế hoạch, nên Bước 3 chỉ mở'), page.indexOf('  // Audio hangs off a timeline row'));
const GATE = 'Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản.';

const outcome = (status) => ({status, completed: status === 'completed'});
const plan = (status, more = {}) => ({projectId: 7, running: false, row: {key: 'plan', state: status === 'completed' ? 'done' : status, outcome: outcome(status)}, ...more});

function studio({studioPlan = null, step = 2, projectId = 7} = {}) {
  const messages = [];
  const loads = [];
  const panels = [1, 2, 3, 4, 5, 6, 7].map((value) => ({dataset: {studioStep: String(value)}, hidden: value !== step}));
  const tabs = [1, 2, 3, 4, 5, 6, 7].map((value) => {
    const tab = {dataset: {studioTab: String(value)}, flags: {}, title: '', attributes: {}, label: {textContent: ''}};
    tab.classList = {toggle(name, on) { tab.flags[name] = Boolean(on); }};
    tab.querySelector = () => tab.label;
    tab.setAttribute = (name, value_) => { tab.attributes[name] = value_; };
    return tab;
  });
  const sandbox = {
    state: {studioProjectId: projectId, studioStep: step, studioPlan, studioWorkflow: 'content'},
    $: () => null,
    document: {
      querySelectorAll: (selector) => (selector === '[data-studio-step]' ? panels : selector === '[data-studio-tab]' ? tabs : []),
      querySelector: (selector) => (selector === '[data-studio-tab="3"]' ? tabs[2] : null),
    },
    setMessage: (text, type = '') => messages.push([text, type]),
    loadStudioPlan: async (id) => { loads.push(id); },
    normalizeStudioWorkflowForSource() {}, renderStudioShortWorkflowNote() {}, refreshStudioPublish: async () => {},
    studioSelectedVideo: () => null, syncStudioVoiceModelOptions() {}, syncStudioSubtitleOptions() {},
    hydrateStudioVoiceSettings: async () => {}, refreshStudioRenderReadiness: async () => {}, saveStudioSession() {},
    Number, Boolean, Math,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const shown = () => panels.filter((panel) => !panel.hidden).map((panel) => Number(panel.dataset.studioStep));
  return {sandbox, messages, loads, tabs, shown, script: tabs[2]};
}

const NOT_READY = {
  'no plan yet': null,
  'a plan being made': plan('running', {running: true}),
  'a completed plan being made again': {projectId: 7, running: true, row: {key: 'plan', state: 'running', outcome: outcome('completed')}},
  'a run found on the server': {projectId: 7, running: false, row: {key: 'plan', state: 'running', outcome: outcome('completed')}},
  'research only (draft)': plan('draft', {row: {key: 'plan', state: 'ready', outcome: outcome('draft')}}),
  'needs_user_decision': plan('needs_user_decision'),
  'blocked': plan('blocked'),
  'stale': plan('stale'),
  'the plan of another project': {...plan('completed'), projectId: 99},
};

for (const [name, studioPlan] of Object.entries(NOT_READY)) {
  test(`with ${name}, the script step does not open`, () => {
    const ui = studio({studioPlan});
    ui.sandbox.setStudioStep(3);   // what the tab, "Tiếp tục Kịch bản →" and "← Kịch bản" all call
    assert.equal(ui.sandbox.state.studioStep, 2);
    assert.deepEqual(ui.shown(), [2]);
    assert.deepEqual(ui.messages, [[GATE, 'error']]);
    assert.equal(ui.script.flags.active, false);
    assert.equal(ui.script.flags.locked, true);
    assert.equal(ui.script.title, GATE);
    assert.equal(ui.script.attributes['aria-disabled'], 'true');
    assert.equal(ui.tabs[1].flags.done, false, 'and step two is not marked done');
  });
}

test('with a completed plan the script step opens', () => {
  const ui = studio({studioPlan: plan('completed')});
  ui.sandbox.setStudioStep(3);
  assert.equal(ui.sandbox.state.studioStep, 3);
  assert.deepEqual(ui.shown(), [3]);
  assert.deepEqual(ui.messages, []);
  assert.equal(ui.script.flags.active, true);
  assert.equal(ui.script.flags.locked, false);
  assert.equal(ui.script.title, '');
  assert.equal(ui.tabs[1].flags.done, true);
});

test('blocked, the person stays on the step they were on', () => {
  for (const from of [1, 4, 6]) {
    const ui = studio({studioPlan: plan('needs_user_decision'), step: from});
    ui.sandbox.setStudioStep(3);
    assert.equal(ui.sandbox.state.studioStep, from);
    assert.deepEqual(ui.shown(), [from]);
    assert.deepEqual(ui.messages, [[GATE, 'error']]);
  }
});

test('code that re-applies the current step cannot keep the script step open either', () => {
  // The page was on step three and the plan has since gone stale: the next time
  // anything sets the step again (a workflow change, a restore), it leaves.
  const ui = studio({studioPlan: plan('stale'), step: 3});
  ui.sandbox.setStudioStep(ui.sandbox.state.studioStep);
  assert.equal(ui.sandbox.state.studioStep, 2);
  assert.deepEqual(ui.shown(), [2]);
  assert.deepEqual(ui.loads, [7], 'and the plan step reads its state from the server');
});

test('no project, no way in', () => {
  const ui = studio({studioPlan: plan('completed'), projectId: null});
  ui.sandbox.setStudioStep(3);
  assert.notEqual(ui.sandbox.state.studioStep, 3);
});

test('the other steps move as before, and the lock on the tab follows the plan', () => {
  const ui = studio({studioPlan: null, step: 1});
  ui.sandbox.setStudioStep(2);
  assert.deepEqual(ui.shown(), [2]);
  assert.deepEqual(ui.messages, []);
  assert.equal(ui.script.flags.locked, true, 'locked before anyone clicks it');
  ui.sandbox.state.studioPlan = plan('completed');
  ui.sandbox.syncStudioScriptGate();
  assert.equal(ui.script.flags.locked, false);
  ui.sandbox.setStudioStep(1);
  assert.deepEqual(ui.shown(), [1]);
});

// Reopening a project: how far it got is read from what it holds, but a project
// whose plan is not ready opens at the plan - whatever it already has beyond it.
const restoreCode = page.slice(page.indexOf('  async function restoreStudioProgress('), page.indexOf('  async function restoreSavedStudioSession('));

async function reopen({ready, bundle}) {
  const opened = [];
  const messages = [];
  const sandbox = {
    state: {studioVideoId: 'v1', projects: [{id: 7, youtube_video_id: 'v1'}], studioWorkflow: 'content'},
    WORKFLOWS: {content: {}},
    api: async () => bundle,
    $: () => null,
    setStudioStep: (step) => opened.push(step),
    setMessage: (text, type = '') => messages.push([text, type]),
    studioPlanReady: () => ready,
    loadStudioPlan: async () => true,
    followStudioAnalyze: async () => false,
    normalizeStudioWorkflowForSource() {}, renderStudioAnalysis() {}, renderStudioScript() {}, loadShortLane() {},
    syncStudioLaneTabs() {}, loadProjectLog() {}, renderStudioPublish() {}, renderStudioStoryboard() {},
    updateStudioSceneGenerationAvailability() {}, saveStudioSession() {},
    Number, String, Boolean,
  };
  vm.createContext(sandbox);
  vm.runInContext(restoreCode, sandbox);
  await sandbox.restoreStudioProgress(7);
  return {opened, messages};
}

const analysed = {project: {workflow: 'content'}, reference_analysis: {result: {topic: 'x'}}};
const OLD_PROJECTS = {
  'a script': {...analysed, latest_script: {id: 94}},
  'a script and scenes': {...analysed, latest_script: {id: 94}, latest_shots: [{id: 1}], latest_timeline: [{id: 1, audio_path: ''}]},
  'a voiced timeline': {...analysed, latest_script: {id: 94}, latest_shots: [{id: 1}], latest_timeline: [{id: 1, audio_path: 'a.wav'}]},
  'a finished video': {...analysed, latest_script: {id: 94}, latest_shots: [{id: 1}], latest_timeline: [{id: 1, audio_path: 'a.wav'}], final_video: {available: true}},
};

for (const [name, bundle] of Object.entries(OLD_PROJECTS)) {
  test(`an older project with ${name} but no ready plan opens at the plan, without an error`, async () => {
    const {opened, messages} = await reopen({ready: false, bundle});
    assert.deepEqual(opened, [2]);
    assert.deepEqual(messages, [], 'reopening is not a mistake the person made');
  });
}

test('with a ready plan a project opens where it had got to', async () => {
  const steps = [];
  for (const bundle of Object.values(OLD_PROJECTS)) steps.push((await reopen({ready: true, bundle})).opened[0]);
  assert.deepEqual(steps, [3, 4, 5, 7]);
});
