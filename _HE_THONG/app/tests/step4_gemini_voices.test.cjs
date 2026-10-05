// Bước 4 · the Gemini voice list, run for real: loadGeminiVoices from core.js
// against a scripted catalog. The catalog's voices for a language need not
// include the default voice - Google's vi-VN list is "vi-vn-…" voices, no Kore -
// and the voice select must still end up on a voice that is listed, unless the
// project already saved a Gemini voice: that one stays chosen, listed or not.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const core = fs.readFileSync(path.join(__dirname, '../youtube_monitor/static/core.js'), 'utf8');
const START = 'function loadGeminiVoices(provider) {';
const code = core.slice(core.indexOf(START), core.indexOf('function voiceLocaleLabel('));

const option = (value, textContent = value, dataset = {}) => ({value, textContent, dataset: {...dataset}});

function page({catalog, chosen = '', language = 'vi', initial = [option('Kore')], storedChosen = false}) {
  const calls = [];
  const group = {
    label: '',
    children: initial.map((item) => ({...item, dataset: {...item.dataset}})),
    set innerHTML(html) {
      this.children = [...html.matchAll(/<option value="([^"]*)"([^>]*)>([^<]*)<\/option>/g)].map((match) => {
        const dataset = Object.fromEntries([...match[2].matchAll(/data-([a-z]+)="([^"]*)"/g)].map((pair) => [pair[1], pair[2]]));
        return option(match[1], match[3], dataset);
      });
    },
    querySelectorAll() { return this.children; },
    appendChild(child) { this.children.push(child); },
  };
  const select = {
    value: chosen,
    get selectedOptions() { return group.children.filter((item) => item.value === this.value); },
  };
  if (storedChosen) group.children.filter((item) => item.value === chosen).forEach((item) => { item.dataset.stored = '1'; });
  const elements = {
    studioGeminiVoiceGroup: group,
    studioVoiceModelSelect: select,
    studioPublishLanguageSelect: {value: language},
  };
  const context = {
    state: {},
    document: {createElement: () => option('')},
    $: (id) => elements[id] || null,
    esc: (value) => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    api: async (url) => { calls.push(url); await new Promise((resolve) => setTimeout(resolve, 5)); return catalog; },
    syncStudioVoiceModelOptions: () => {},
    setMessage: (text, kind) => calls.push(`message:${kind}:${text}`),
  };
  vm.createContext(context);
  vm.runInContext(`${code}\nthis.loadGeminiVoices = loadGeminiVoices;`, context);
  return {context, elements, calls, group, select};
}

const VI_CATALOG = {
  provider: 'google_gemini_3_8_flash_tts', source: 'api', language_code: 'vi-VN', default_voice: 'Kore', total: 3,
  voices: ['vi-vn-advisor-1', 'vi-vn-advisor-6', 'vi-vn-tutor-2'].map((id) => ({id, name: id, language_code: 'vi-VN', gender: 'female'})),
};

test('a catalog without the default voice still leaves a listed voice chosen, never an empty select', async () => {
  // Switching from Edge: the page placeholder (Kore, not the project's voice) was showing.
  const {context, select, calls} = page({catalog: VI_CATALOG, chosen: 'Kore'});
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  assert.equal(select.value, 'vi-vn-advisor-1');
  assert.deepEqual(calls, ['/api/tts/voices?provider=google_gemini_3_8_flash_tts&language=vi']);
});

test("each option carries what the catalog said about the voice, and nothing it did not", async () => {
  const catalog = {...VI_CATALOG, total: 2, voices: [
    {id: 'vi-vn-advisor-6', name: 'Authoritative Advisor 6', gender: 'MALE', persona: 'Storyteller', description: 'Calm', language_code: 'vi-VN'},
    {id: 'vi-vn-plain-1', name: 'Plain 1'},
  ]};
  const {context, group} = page({catalog, chosen: 'Kore'});
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  const [described, bare] = group.children;
  assert.deepEqual({...described.dataset}, {name: 'Authoritative Advisor 6', gender: 'male', persona: 'Storyteller', description: 'Calm', language: 'vi-VN'});
  assert.deepEqual({...bare.dataset}, {name: 'Plain 1'}, 'no gender, persona or language is made up');
  assert.deepEqual({...context.state.geminiCatalog}, {total: 2, source: 'api', stale: false, language_code: 'vi-VN', error: ''},
    'the count shown is the one the server gave');
  assert.equal(context.state.geminiVoicesBusy, false);
});

test('a voice already chosen from the catalog is kept', async () => {
  const {context, select} = page({catalog: VI_CATALOG, chosen: 'vi-vn-advisor-6', initial: [option('Kore'), option('vi-vn-advisor-6')]});
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  assert.equal(select.value, 'vi-vn-advisor-6');
});

test("the project's saved Gemini voice stays chosen even when the catalog does not list it", async () => {
  // A project saved with Kore (a prebuilt voice) opened after a restart: the vi-VN catalog has no Kore.
  const {context, select, group} = page({catalog: VI_CATALOG, chosen: 'Kore', storedChosen: true});
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  assert.equal(select.value, 'Kore');
  assert.deepEqual(group.children.map((item) => item.value), ['vi-vn-advisor-1', 'vi-vn-advisor-6', 'vi-vn-tutor-2', 'Kore']);
  assert.equal(group.children.at(-1).textContent, 'Kore · giọng đã chọn');
  assert.equal(group.children.at(-1).dataset.outside, '1', 'shown as a voice outside the list just loaded');
  assert.equal(select.selectedOptions[0].dataset.stored, '1');
});

test('the default voice is chosen when the list has it and the stored voice is foreign', async () => {
  const builtin = {source: 'builtin', default_voice: 'Kore', total: 2, voices: [{id: 'Puck', name: 'Puck'}, {id: 'Kore', name: 'Kore'}]};
  const {context, select, group} = page({catalog: builtin, chosen: 'vi-VN-HoaiMyNeural', initial: []});
  await context.loadGeminiVoices('google_gemini_3_8_flash_lite_tts');
  assert.equal(select.value, 'Kore');
  assert.match(group.label, /dựng sẵn/);
});

test('a save waits on the same load: one request, and the voice is chosen when it resolves', async () => {
  const {context, select, calls} = page({catalog: VI_CATALOG, chosen: 'Kore'});
  const first = context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  const second = context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  assert.equal(first, second, 'whoever asks during the load gets the same load');
  assert.equal(select.value, 'Kore', 'before the list arrives the placeholder is still showing');
  await second;
  assert.equal(select.value, 'vi-vn-advisor-1', 'once it resolves, the voice that will be saved is the one shown');
  assert.equal(calls.length, 1);
});

test('the catalog is asked once per model and language, not on every sync', async () => {
  const {context, calls} = page({catalog: VI_CATALOG});
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  await context.loadGeminiVoices('google_gemini_3_8_flash_tts');
  assert.equal(calls.length, 1);
  await context.loadGeminiVoices('google_gemini_3_8_flash_lite_tts');
  assert.equal(calls.length, 2);
});
