// YT Factory AI Web Bridge — background service worker.
//
// Push-driven, not polling: holds one WebSocket open to the local app
// (ws://127.0.0.1:8787/ws/browser-scene-jobs) and does nothing at all
// until the SERVER sends a message saying a job is queued for a provider
// this extension has enabled. Only then does it open a tab / talk to the
// site / call the app's REST API. No timer-driven "is there a job yet?"
// checks against the site or the app.
//
// The one exception is a long-interval chrome.alarms tick (see
// KEEPALIVE_PERIOD_MINUTES below) — MV3 service workers can be suspended
// by the browser at any time, and an open WebSocket alone isn't a
// guaranteed way to keep one alive across Chrome versions, so the alarm
// exists purely to wake the worker up and reconnect the socket if it
// dropped while suspended. It does not itself check for jobs.

const FACTORY = 'http://127.0.0.1:8787';
const WS_URL = 'ws://127.0.0.1:8787/ws/browser-scene-jobs';
const KEEPALIVE_PERIOD_MINUTES = 1; // just "is the socket still open?", not a job check
const PROVIDER_URLS = {
  gemini_web_image: 'https://gemini.google.com/app',
  chatgpt_web_image: 'https://chatgpt.com/',
  // Vibes, not the plain chat: the chat surface refuses video outright
  // (confirmed live — it returned "Yêu cầu đã bị dừng" three times and then
  // explained its video limitations), while Vibes is where Meta actually
  // generates clips. The feed of strangers' videos there is handled by the
  // agent's goal telling it not to mistake one for our result.
  meta_ai_video: 'https://www.meta.ai/vibes',
  // Only a fallback for when no Flow tab is open: normal operation reuses
  // whichever Flow project the user already has open (see REUSE_TAB_MATCH),
  // rather than forcing one hardcoded project.
  flow_veo: 'https://labs.google/fx/vi/tools/flow',
  // Same workspace as flow_veo — the composer's own tab switch picks image
  // vs video, and image generation there costs no credits.
  flow_image: 'https://labs.google/fx/vi/tools/flow',
};

// Our ratio strings, in the terms Flow's own aspect-ratio buttons use.
const FLOW_ASPECT_LABELS = {
  '1280:720': '16:9',
  '720:1280': '9:16',
  '1024:1024': '1:1',
};
const FLOW_WORKSPACE_STORAGE_KEY = 'flowProjectWorkspaces';
// Each job opens its own independent tab, so several can genuinely run at
// once with no DOM conflict — this just caps how many at a time (across
// all providers combined) rather than forcing a hard 1-at-a-time queue.
const MAX_CONCURRENT_JOBS = 3;
// Small gap between claiming additional jobs within the same notification
// burst, so a big batch doesn't open N tabs in the same instant — softens
// the automation signature slightly without giving up real parallelism.
const CLAIM_STAGGER_MS = 1500;

let activeJobs = 0;
let socket = null;
let reconnectDelayMs = 2000;

// MV3 suspends an idle service worker after ~30s, which silently kills any
// run in progress: the job stays "running" in the database forever with no
// error, no log line, and no further requests — exactly what was observed
// after a job was claimed and then nothing happened at all. Calling a
// chrome.* API resets that idle timer, so tick one while any job is live.
// The waits inside a run (11s per orchestrator decision, 8s page waits) are
// long enough to cross the threshold on their own.
let keepAliveTimer = null;
function startKeepAlive() {
  if (keepAliveTimer) return;
  keepAliveTimer = setInterval(() => {
    chrome.runtime.getPlatformInfo(() => { /* touching the API is the point */ });
  }, 20000);
}
function stopKeepAliveIfIdle() {
  if (keepAliveTimer && activeJobs === 0) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
}

// A provider added by an update turns on once, then the user's own tick
// decides. Without the knownProviders record it would be permanently
// invisible: the stored list predates it, so jobs for it would be silently
// skipped with no indication why.
async function getEnabledProviders() {
  const all = Object.keys(PROVIDER_URLS);
  const stored = await chrome.storage.local.get(['enabledProviders', 'knownProviders']);
  const enabled = stored.enabledProviders || all;
  const known = stored.knownProviders || (stored.enabledProviders ? [] : all);
  const added = all.filter((provider) => !known.includes(provider));
  if (!added.length) return enabled;
  const merged = [...new Set([...enabled, ...added])];
  await chrome.storage.local.set({ enabledProviders: merged, knownProviders: all });
  return merged;
}

// Per-job status entries (not a single overwritten line) since several jobs
// can be in flight at once now — popup.js renders the most recent handful.
async function setJobStatus(jobId, text) {
  const stored = await chrome.storage.local.get('jobStatuses');
  const statuses = stored.jobStatuses || {};
  statuses[jobId] = { text, at: Date.now() };
  const trimmed = Object.fromEntries(
    Object.entries(statuses).sort((a, b) => b[1].at - a[1].at).slice(0, 10),
  );
  await chrome.storage.local.set({ jobStatuses: trimmed });
}

async function setStatus(text) {
  await chrome.storage.local.set({ lastStatus: text, lastStatusAt: Date.now() });
}

async function apiGet(path) {
  const response = await fetch(`${FACTORY}${path}`);
  if (!response.ok) throw new Error(`GET ${path} -> HTTP ${response.status}`);
  return response.json();
}

async function uploadAsset(projectId, base64, mimeType, kind) {
  const extension = mimeType.includes('png') ? 'png' : mimeType.includes('webp') ? 'webp' : mimeType.includes('gif') ? 'gif' : mimeType.includes('mp4') ? 'mp4' : 'jpg';
  const assetType = kind === 'video' || mimeType.startsWith('video/') ? 'video' : 'image';
  const byteChars = atob(base64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i += 1) bytes[i] = byteChars.charCodeAt(i);
  const blob = new Blob([bytes], { type: mimeType });
  const form = new FormData();
  form.append('asset_type', assetType);
  form.append('file', blob, `web-bridge-${Date.now()}.${extension}`);
  const response = await fetch(`${FACTORY}/api/projects/${projectId}/assets/upload`, { method: 'POST', body: form });
  if (!response.ok) throw new Error(`Upload asset -> HTTP ${response.status}`);
  const data = await response.json();
  return data.asset.id;
}

// Imports a file the browser wrote to disk (see waitForNextDownload) —
// the extension can't read local files, but the app runs on this machine
// and can, so it takes the path and copies it into the project itself.
async function importLocalFile(projectId, path, assetType) {
  const response = await fetch(`${FACTORY}/api/projects/${projectId}/assets/import-local`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, asset_type: assetType }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(`Import file -> HTTP ${response.status} ${detail.slice(0, 200)}`);
  }
  const data = await response.json();
  return data.asset.id;
}

// chrome.downloads gives no way to tell which tab started a download, so
// jobs needing one take turns through this gate: only one job is between
// "click Download" and "download finished" at a time, which is what makes
// attributing the next new download to that job safe while other jobs keep
// generating in parallel.
let downloadGate = Promise.resolve();
function withDownloadGate(fn) {
  const run = downloadGate.then(fn, fn);
  downloadGate = run.then(() => {}, () => {});
  return run;
}

function waitForNextDownload(triggerFn, { timeoutMs = 180000 } = {}) {
  return new Promise((resolve, reject) => {
    let downloadId = null;
    let settled = false;
    const cleanup = () => {
      chrome.downloads.onCreated.removeListener(onCreated);
      chrome.downloads.onChanged.removeListener(onChanged);
      clearTimeout(timer);
    };
    const finish = (isError, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (isError) reject(value instanceof Error ? value : new Error(String(value)));
      else resolve(value);
    };
    const onCreated = (item) => { if (downloadId == null) downloadId = item.id; };
    const onChanged = (delta) => {
      if (downloadId == null || delta.id !== downloadId) return;
      if (delta.state?.current === 'complete') {
        chrome.downloads.search({ id: downloadId }, (items) => {
          const filename = items?.[0]?.filename;
          if (filename) finish(false, filename);
          else finish(true, new Error('Khong lay duoc duong dan file da tai'));
        });
      } else if (delta.state?.current === 'interrupted') {
        finish(true, new Error(`Tai file bi gian doan: ${delta.error?.current || 'khong ro'}`));
      }
    };
    const timer = setTimeout(() => finish(true, new Error('Het thoi gian cho tai file ve')), timeoutMs);
    chrome.downloads.onCreated.addListener(onCreated);
    chrome.downloads.onChanged.addListener(onChanged);
    Promise.resolve()
      .then(triggerFn)
      .then((result) => {
        if (result && result.ok === false) finish(true, new Error(result.error || 'Khong bam duoc nut Download'));
      })
      .catch((error) => finish(true, error));
  });
}

function waitForTabComplete(tabId, { timeoutMs = 30000 } = {}) {
  return new Promise((resolve) => {
    const listener = (updatedId, info) => {
      if (updatedId === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, timeoutMs);
  });
}

// Reuses a tab the user already has open on that site when reuseMatch is
// given, rather than opening a fresh one.
//
// A newly opened Flow tab never reached the scene composer — it sat on the
// content library with both "Tạo" buttons disabled, no matter which route
// the agent tried. A tab the user has already navigated to the right screen
// sidesteps that entirely, and also avoids re-running a heavy workspace
// app's startup for every job. Returns {tabId, created} so the caller only
// closes tabs it opened — closing the user's own tab would be rude and
// would lose whatever state made it usable.
async function findOrCreateTab(url, { settleMs = 1500, reuseMatch = null } = {}) {
  if (reuseMatch) {
    const open = await chrome.tabs.query({ url: reuseMatch });
    if (open.length) {
      return { tabId: open[open.length - 1].id, created: false };
    }
  }
  const tab = await chrome.tabs.create({ url, active: false });
  await waitForTabComplete(tab.id);
  // Heavy single-page apps keep initialising well past load "complete".
  await new Promise((r) => setTimeout(r, settleMs));
  return { tabId: tab.id, created: true };
}

function flowWorkspaceName(job) {
  const title = String(job.project_title || 'Du an khong ten').replace(/\s+/g, ' ').trim();
  return `YT Factory P${job.project_id} - ${title}`.slice(0, 100);
}

async function getFlowWorkspace(job) {
  const stored = await chrome.storage.local.get(FLOW_WORKSPACE_STORAGE_KEY);
  const workspaces = stored[FLOW_WORKSPACE_STORAGE_KEY] || {};
  const workspace = workspaces[String(job.project_id)] || null;
  // A restored/test database can reuse a numeric id for a different project.
  // In that case do not send its scenes into the old Flow project.
  if (workspace && workspace.projectTitle !== String(job.project_title || '')) return null;
  return workspace;
}

async function saveFlowWorkspace(job, tabId) {
  const tab = await chrome.tabs.get(tabId);
  const stored = await chrome.storage.local.get(FLOW_WORKSPACE_STORAGE_KEY);
  const workspaces = stored[FLOW_WORKSPACE_STORAGE_KEY] || {};
  workspaces[String(job.project_id)] = {
    tabId,
    url: String(tab.url || PROVIDER_URLS.flow_image),
    name: flowWorkspaceName(job),
    projectTitle: String(job.project_title || ''),
    updatedAt: Date.now(),
  };
  await chrome.storage.local.set({ [FLOW_WORKSPACE_STORAGE_KEY]: workspaces });
}

// One Flow project is reserved for one YT Factory project. The first scene
// opens Flow visibly and creates the workspace; later scenes reopen the
// stored project URL (or reuse its still-open tab) instead of drifting into
// whatever unrelated Flow project happens to be open.
async function findOrCreateFlowWorkspaceTab(job) {
  const workspace = await getFlowWorkspace(job);
  if (workspace?.tabId) {
    try {
      const tab = await chrome.tabs.get(workspace.tabId);
      if (String(tab.url || '').startsWith('https://labs.google/')) {
        const savedUrl = String(workspace.url || '');
        if (savedUrl.startsWith('https://labs.google/') && String(tab.url || '') !== savedUrl) {
          await chrome.tabs.update(tab.id, { url: savedUrl, active: true });
          await waitForTabComplete(tab.id);
          await sleep(8000);
        }
        return { tabId: tab.id, created: false, persistent: true, mustCreateProject: false };
      }
    } catch { /* the saved tab was closed; reopen its project URL below */ }
  }
  const savedUrl = String(workspace?.url || '');
  const targetUrl = savedUrl.startsWith('https://labs.google/')
    ? savedUrl
    : PROVIDER_URLS.flow_image;
  // Flow needs a rendered foreground tab for reliable layout/snapshots, and
  // the user explicitly expects the web workspace to open automatically.
  const tab = await chrome.tabs.create({ url: targetUrl, active: true });
  await waitForTabComplete(tab.id);
  await sleep(8000);
  return {
    tabId: tab.id,
    created: true,
    persistent: true,
    mustCreateProject: !workspace,
  };
}

async function prepareFlowWorkspace(tabId, job) {
  const workspaceName = flowWorkspaceName(job);
  await ensureContentScripts(tabId);
  await runAgentInTab(tabId, [
    'Chuan bi MOT DU AN GOOGLE FLOW rieng de chua TOAN BO cac canh cua mot video YouTube.',
    `Ten du an mong muon: "${workspaceName}".`,
    '',
    'Neu dang o trang thu vien/trang chu Flow, hay bam "Du an moi", "Tao du an" hoac nut tuong duong.',
    'Neu Flow hien o nhap ten khi tao/doi ten, hay dat dung ten tren. Neu Flow tu tao du an ma khong hoi',
    'ten thi van tiep tuc; khong duoc dung lai chi vi chua tim thay cho doi ten.',
    'Neu da o trong man hinh soan cua mot du an vua tao, KHONG tao them du an thu hai.',
    '',
    'Chi tra ve done khi da vao ben trong workspace va thay khu vuc soan co the chon "Hinh anh"/"Video"',
    'hoac o nhap prompt tao canh. Day chi la buoc CHUAN BI DU AN: TUYET DOI KHONG go prompt canh,',
    'KHONG bam nut gui/tao noi dung va KHONG tieu credit.',
    'Neu trang yeu cau dang nhap, bao loi quyen truy cap, hoac khong the tao du an, hay tra ve fail va noi ro.',
  ].join('\n'), { maxSteps: 20 });
  await saveFlowWorkspace(job, tabId);
}

// Providers that drive a shared, reused tab must take turns — two jobs
// typing into the same composer would interleave into nonsense.
const tabLocks = new Map();
function withProviderTabLock(provider, fn) {
  const previous = tabLocks.get(provider) || Promise.resolve();
  const run = previous.then(fn, fn);
  tabLocks.set(provider, run.then(() => {}, () => {}));
  return run;
}

// Fetches an existing scene image (image-to-video reference) as base64 so
// it can travel inside a chrome.tabs.sendMessage payload — content scripts
// can't read a local file path (F:\...), and fetching cross-origin from the
// content script itself risks the target page's CSP, so the background
// script does it and hands the bytes over already-encoded.
async function fetchReferenceImageBase64(assetId) {
  const response = await fetch(`${FACTORY}/api/assets/${assetId}/download`);
  if (!response.ok) throw new Error(`Tai anh tham chieu -> HTTP ${response.status}`);
  const blob = await response.blob();
  const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(new Error('Khong doc duoc anh tham chieu'));
    reader.readAsDataURL(blob);
  });
  return { base64, mimeType: blob.type || 'image/png' };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// Talks to the content script, tolerating the page navigating underneath us.
// Every navigation tears down the old content script and injects a fresh one,
// so a send that lands mid-transition throws; retrying is normal operation
// here, not an error path.
// Declarative content scripts only land on pages loaded after the extension
// started. A tab the user already had open — the whole point of reusing one
// — has no receiver, which surfaced as "Could not establish connection.
// Receiving end does not exist." Inject on demand, but only when a ping goes
// unanswered: re-injecting into a tab that already has them throws on the
// duplicate top-level declarations.
async function ensureContentScripts(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: 'ytf_agent_ping' });
    if (pong?.ok) return;
  } catch { /* nothing listening yet — inject below */ }
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ['content_common.js', 'content_agent.js'],
  });
  await sleep(500);
}

async function sendToTab(tabId, message, { retries = 6, gapMs = 2000 } = {}) {
  let lastError = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, message);
      if (response) return response;
      lastError = new Error('Content script khong tra loi');
    } catch (error) {
      lastError = error;
    }
    await sleep(gapMs);
    // Safety net for a page that came back without our scripts (e.g. it
    // navigated somewhere the declarative injection doesn't cover).
    if (attempt === 1) {
      try { await ensureContentScripts(tabId); } catch { /* keep retrying */ }
    }
  }
  throw new Error(`Tab khong phan hoi: ${String(lastError?.message || lastError)}`);
}

// Types by asking the browser itself to insert the text, over the DevTools
// protocol.
//
// This is the only route whose input events are genuinely trusted, and
// trusted input is what rich-text editors actually respond to. Everything
// else — assigning .value, execCommand, dispatching beforeinput, even
// running in the page's own world — left Flow's Lexical composer believing
// it was empty: the prompt was visible on screen with the placeholder still
// overlaid, and the send button never unlocked. The cost is the browser's
// "is being debugged" banner while a job runs, which is worth paying for a
// step that otherwise cannot be completed at all.
function debuggerCommand(target, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(target, method, params, (result) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(result);
    });
  });
}

function debuggerAttach(target) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach(target, '1.3', () => {
      const error = chrome.runtime.lastError;
      // Already attached is fine — another job in this run may hold it.
      if (error && !/already attached/i.test(error.message)) reject(new Error(error.message));
      else resolve();
    });
  });
}

function debuggerDetach(target) {
  return new Promise((resolve) => {
    chrome.debugger.detach(target, () => {
      void chrome.runtime.lastError; // detaching an already-gone target is fine
      resolve();
    });
  });
}

async function typeWithDebugger(tabId, index, text) {
  const target = { tabId };
  await debuggerAttach(target);
  try {
    // Focus the real editable host and select what's there, so the insert
    // replaces rather than appends.
    const focusResult = await debuggerCommand(target, 'Runtime.evaluate', {
      expression: `(() => {
        const target = document.querySelector('[data-ytf-idx="${index}"]');
        if (!target) return 'khong-thay-phan-tu';
        const el = target.isContentEditable
          ? (target.closest('[data-lexical-editor="true"]') || target)
          : (target.querySelector('[data-lexical-editor="true"], [contenteditable="true"]') || target);
        el.focus();
        if ('value' in el && typeof el.select === 'function') { el.select(); return 'ok'; }
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(el);
        selection.removeAllRanges();
        selection.addRange(range);
        return 'ok';
      })()`,
      returnByValue: true,
    });
    if (focusResult?.result?.value !== 'ok') {
      return String(focusResult?.result?.value || 'khong-focus-duoc');
    }
    await debuggerCommand(target, 'Input.insertText', { text });
    return 'ok';
  } finally {
    await debuggerDetach(target);
  }
}

// Clicks by having the browser dispatch a real mouse press at the element's
// position, over the DevTools protocol.
//
// Same reason as typeWithDebugger: Flow ignores synthetic activation. The
// prompt was typed, the options were right, and the agent clicked the send
// arrow — and nothing was ever submitted, through every synthetic variant
// (dispatched click, native .click(), pointer sequences, clicking the inner
// icon). A protocol-level press is indistinguishable from the user's own.
async function clickWithDebugger(tabId, index) {
  const target = { tabId };
  await debuggerAttach(target);
  try {
    const box = await debuggerCommand(target, 'Runtime.evaluate', {
      expression: `(() => {
        const el = document.querySelector('[data-ytf-idx="${index}"]');
        if (!el) return null;
        el.scrollIntoView({ block: 'center', inline: 'center' });
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return null;
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })()`,
      returnByValue: true,
    });
    const point = box?.result?.value;
    if (!point) return 'khong-thay-phan-tu-hoac-khong-nhin-thay';
    const common = { x: point.x, y: point.y, button: 'left', clickCount: 1, buttons: 1 };
    await debuggerCommand(target, 'Input.dispatchMouseEvent', { type: 'mouseMoved', ...common, buttons: 0 });
    await debuggerCommand(target, 'Input.dispatchMouseEvent', { type: 'mousePressed', ...common });
    await debuggerCommand(target, 'Input.dispatchMouseEvent', { type: 'mouseReleased', ...common, buttons: 0 });
    return 'ok';
  } finally {
    await debuggerDetach(target);
  }
}

// Types into a field from the PAGE's own JS world.
//
// A content script runs in an isolated world with its own DOM wrappers, so
// React's value tracker — which lives on the page's wrapper — never sees the
// assignment. Observed on Flow: the prompt text appeared in the textarea but
// React still believed it empty, leaving the "Tạo" button disabled through
// every retry. Running the same assignment in the main world puts it on the
// wrapper React is watching, so its onChange fires and the button unlocks.
async function typeIntoMainWorld(tabId, index, text) {
  const [injected] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    args: [String(index), text],
    func: (idx, value) => {
      const target = document.querySelector(`[data-ytf-idx="${idx}"]`);
      if (!target) return 'khong-thay-phan-tu';
      // Resolve to the editor's own root: a rich-text editor only listens on
      // its own element, so typing into a look-alike wrapper leaves its model
      // empty even though the characters show up.
      const el = target.isContentEditable
        ? (target.closest('[data-lexical-editor="true"]') || target)
        : (target.querySelector('[data-lexical-editor="true"], [contenteditable="true"]') || target);
      el.focus();
      if ('value' in el) {
        const proto = el instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(el, value); else el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return 'ok';
      }
      const selectAll = () => {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(el);
        selection.removeAllRanges();
        selection.addRange(range);
      };
      const landed = () => String(el.innerText || '').includes(value.slice(0, 30));
      selectAll();
      if (document.execCommand('insertText', false, value) && landed()) return 'ok';
      // Lexical builds its model from beforeinput, not from the DOM.
      selectAll();
      el.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true, cancelable: true, composed: true, inputType: 'insertText', data: value,
      }));
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true, composed: true, inputType: 'insertText', data: value,
      }));
      return landed() ? 'ok' : 'go-vao-nhung-editor-khong-nhan';
    },
  });
  return injected?.result || 'khong-co-ket-qua';
}

// Routes one action: typing goes through the page's own world (React only
// notices assignments made there), everything else through the content
// script, which holds the live element references.
async function performAction(tabId, action, referenceImage) {
  if (action.action === 'type' && typeof action.index === 'number') {
    const text = action.text || '';
    const notes = [];

    // Ordered by how convincing the input looks to the page: a real browser
    // insert, then the page's own world, then the isolated world.
    try {
      const outcome = await typeWithDebugger(tabId, action.index, text);
      if (outcome === 'ok') return { ok: true, via: 'debugger' };
      notes.push(`debugger: ${outcome}`);
    } catch (error) {
      notes.push(`debugger: ${String(error?.message || error)}`);
    }
    try {
      const outcome = await typeIntoMainWorld(tabId, action.index, text);
      if (outcome === 'ok') return { ok: true, via: `main-world (${notes.join('; ')})` };
      notes.push(`main-world: ${outcome}`);
    } catch (error) {
      notes.push(`main-world: ${String(error?.message || error)}`);
    }
    const fallback = await sendToTab(tabId, { type: 'ytf_agent_action', action });
    return { ...fallback, via: `content-script (${notes.join('; ')})` };
  }
  if (action.action === 'click' && typeof action.index === 'number') {
    try {
      const outcome = await clickWithDebugger(tabId, action.index);
      if (outcome === 'ok') return { ok: true, via: 'debugger-click' };
      const fallback = await sendToTab(tabId, { type: 'ytf_agent_action', action });
      return { ...fallback, via: `content-script-click (debugger: ${outcome})` };
    } catch (error) {
      const fallback = await sendToTab(tabId, { type: 'ytf_agent_action', action });
      return { ...fallback, via: `content-script-click (debugger: ${String(error?.message || error)})` };
    }
  }
  return sendToTab(tabId, {
    type: 'ytf_agent_action',
    action,
    referenceImage: action.action === 'attach_image' ? referenceImage : null,
  });
}

// Retries a failed decision instead of ending the run. The CLI behind this
// occasionally errors for one call, and losing a nearly-finished 30-step
// session to a single hiccup wastes both time and paid generation quota.
async function askOrchestratorForAction(payload, { attempts = 3 } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(`${FACTORY}/api/orchestrator/browser-action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (response.ok) return await response.json();
      const detail = await response.text().catch(() => '');
      lastError = new Error(`HTTP ${response.status} ${detail.slice(0, 200)}`);
    } catch (error) {
      lastError = error;
    }
    if (attempt < attempts) await sleep(5000);
  }
  throw new Error(`Hoi AI dieu phoi that bai sau ${attempts} lan: ${String(lastError?.message || lastError)}`);
}

// The observe → decide → act loop. Lives here rather than in the content
// script so it survives the page navigations the agent itself causes.
async function runAgentInTab(tabId, goal, { maxSteps = 30, referenceImage = null, onStep = null } = {}) {
  const history = [];
  // Filling a file input uploads a copy into the site's media library. When
  // that didn't visibly fill the frame slot, the agent kept retrying and
  // flooded the library with ~20 copies of the same reference image. One
  // upload per run is all that can ever be useful — after that the file is
  // already there and the job is to select it, not send it again.
  let attachCount = 0;
  for (let step = 1; step <= maxSteps; step += 1) {
    if (onStep && step === 1) await onStep('dang-chup-trang');
    const snapshot = await sendToTab(tabId, { type: 'ytf_agent_snapshot' });
    if (!snapshot.ok) throw new Error(snapshot.error || 'Khong chup duoc trang');

    const decision = await askOrchestratorForAction({
      goal,
      url: snapshot.url,
      elements: snapshot.elements,
      page_text: snapshot.pageText,
      history,
      step,
    });
    const label = `${step}. ${decision.action}${decision.index != null ? `(${decision.index})` : ''} — ${decision.reason}`;
    history.push(label);
    if (onStep) await onStep(label);

    if (decision.action === 'done') return { index: decision.index, history };
    if (decision.action === 'fail') throw new Error(`AI dieu phoi dung lai: ${decision.reason}`);
    if (decision.action === 'reload') {
      // Recovery from a crashed SPA — Flow died with "Application error: a
      // client-side exception" and the agent could correctly diagnose it but
      // had no way to act, so the run was lost.
      await chrome.tabs.reload(tabId);
      await waitForTabComplete(tabId);
      await sleep(5000);
      continue;
    }

    if (decision.action === 'attach_image') {
      attachCount += 1;
      if (attachCount > 1) {
        history.push(
          '   BI CHAN: anh tham chieu DA duoc tai len o buoc truoc roi. Tai len lan nua chi tao them ban sao '
          + 'thua trong thu vien. Hay bam vao khe "Bat dau" va CHON anh do TU THU VIEN, dung tai len nua.',
        );
        continue;
      }
    }

    const result = await performAction(tabId, decision, referenceImage);
    if (!result.ok) history.push(`   loi khi thuc hien: ${result.error}`);
    else if (result.via) history.push(`   (thuc hien qua: ${result.via})`);

    // Follow-up steps the orchestrator was confident enough to decide without
    // seeing the page again — each one skipped saves ~11s of CLI time. They
    // stop at the first failure, since anything unexpected means the page no
    // longer matches what those steps assumed.
    for (const followUp of Array.isArray(decision.then) ? decision.then.slice(0, 4) : []) {
      if (followUp.action === 'attach_image') continue; // one upload per run, enforced above
      const followResult = await performAction(tabId, followUp, null);
      const tag = `   + ${followUp.action}${followUp.index != null ? `(${followUp.index})` : ''}`;
      if (!followResult.ok) {
        history.push(`${tag}: dung lai - ${followResult.error}`);
        break;
      }
      history.push(tag);
    }
  }
  throw new Error(`Het ${maxSteps} buoc ma chua xong. Da lam:\n${history.join('\n')}`);
}

function buildAgentGoal(provider, job, hasReference) {
  if (provider === 'gemini_web_image' || provider === 'chatgpt_web_image' || provider === 'meta_ai_image') {
    const site = provider === 'gemini_web_image' ? 'Gemini' : provider === 'meta_ai_image' ? 'Meta AI' : 'ChatGPT';
    return [
      `Tao MOT ANH TINH bang ${site} (giao dien chat web).`,
      '',
      'Cach lam: go doan prompt duoi day vao o nhap cua khung chat, gui di, roi cho AI ve xong anh.',
      'Neu trang hoi lai de xac nhan bo cuc/phong cach, hay tra loi khang dinh chon phuong an hop ly',
      'nhat va yeu cau tao ngay, dung hoi them.',
      hasReference
        ? 'Co san mot anh tham chieu: khi thay o dinh kem file, dung attach_image de gan vao truoc khi gui.'
        : '',
      '',
      'Neu nut gui dang DISABLED, hay wait roi thu lai.',
      'Chi tra ve done khi anh KET QUA cua luot tao nay da xuat hien, kem index cua phan tu <img> do.',
      'Anh cu o phia tren doan chat KHONG phai ket qua.',
      '',
      'PROMPT CAN GUI:',
      job.prompt,
    ].filter(Boolean).join('\n');
  }
  if (provider === 'flow_image') {
    const aspect = FLOW_ASPECT_LABELS[job.ratio] || '16:9';
    return [
      `Tao MOT ANH TINH bang Google Flow trong project "${flowWorkspaceName(job)}" dang mo.`,
      'Tat ca canh cua video nay phai nam trong CUNG project Flow nay; khong tao them project moi.',
      '',
      'GIAO DIEN: khung soan nam o DUOI CUNG giua man hinh. Ngay tren o nhap co bang tuy chon voi:',
      '- Hai the: "Hinh anh" va "Video" -> phai chon the "Hinh anh"',
      `- Day ti le khung hinh: 16:9, 4:3, 1:1, 3:4, 9:16 -> chon ${aspect}`,
      '- Bo chon model (vi du "Nano Banana 2")',
      '- So luong: x1, x2, x3, x4 -> chon x1 (chi can 1 anh)',
      'Neu bang tuy chon chua hien, hay bam vao nhan che do canh o nhap de mo no ra.',
      '',
      'Sau khi dat dung cac tuy chon, go prompt vao o nhap roi bam nut mui ten gui o goc phai-duoi.',
      'Dong chu "Qua trinh tao se ton 0 tin dung" xac nhan dang o che do anh (khong ton tin dung).',
      'Neu no bao ton tin dung thi ban dang o che do VIDEO — hay chuyen lai ve the "Hinh anh".',
      '',
      'Anh tao xong sau vai giay. Chi tra ve done khi anh KET QUA cua luot tao nay da xuat hien,',
      'kem index cua phan tu <img> do. Cac anh cu trong thu vien KHONG phai ket qua.',
      '',
      'PROMPT CAN GUI:',
      job.prompt,
    ].join('\n');
  }
  if (provider === 'flow_veo') {
    return [
      `Tao MOT VIDEO NGAN bang Google Flow (Veo) trong project "${flowWorkspaceName(job)}" dang mo san.`,
      'Tat ca canh cua video nay phai nam trong CUNG project Flow nay; khong tao them project moi.',
      '',
      'CANH BAO QUAN TRONG: Flow co ca chuc nang tao ANH va tao VIDEO. Lan truoc agent da lac vao chuc nang',
      'tao anh va bam lap lai, sinh ra 7 tam anh tinh giong nhau, tieu ton luot tra phi cua nguoi dung ma',
      'khong duoc video nao. TUYET DOI khong dung cac muc lien quan den anh ("Hinh anh", "Nhan vat", "Canh",',
      '"Chinh sua hinh anh", "Nano Banana", "Tao ban ve y tuong"). Neu ket qua hien ra la ANH TINH thi ban',
      'dang o sai cho — dung bam tiep, hay tim lai khu vuc tao video.',
      '',
      'GIAO DIEN THAT (da xem tan mat): khung soan nam o DUOI CUNG giua man hinh, gom:',
      '- Hai khe khung hinh o tren cung khung soan: "Bat dau" va "Ket thuc" (start/end frame)',
      '- O nhap prompt lon o giua',
      '- Goc trai duoi: nut "Tac nhan"',
      '- Goc phai duoi: nhan che do dang la "Video - 720p - 8s" va NUT MUI TEN GUI (->). Bam mui ten nay',
      '  chinh la lenh tao video. Day la nut can bam sau khi da go prompt.',
      '',
      'Cac tam ANH trong thu vien phia tren la RAC tu nhung lan chay hong truoc, KHONG phai ket qua.',
      'Dung coi chung la ket qua va dung bam vao chung.',
      '',
      hasReference
        ? [
          'CO san mot anh tham chieu can dua vao khe "Bat dau" (khung hinh dau tien).',
          'Cach lam: bam vao khe "Bat dau" -> se hien cac lua chon (vi du tai len tu may / chon tu thu vien)',
          '-> chon muc TAI LEN tu may -> khi snapshot xuat hien "O DINH KEM FILE" thi dung attach_image vao do.',
          'CANH BAO DA XAY RA: attach_image do vao o file cua THU VIEN chu khong vao khe "Bat dau", nen khe',
          'van trong va viec thu lai da tao ra hang chuc ban sao thua trong thu vien. Vi vay attach_image chi',
          'duoc dung DUNG MOT LAN trong ca luot chay; lan thu hai se bi chan.',
          '',
          'Anh mau nhieu kha nang DA CO SAN trong thu vien (tu cac lan truoc). Hay uu tien: bam khe "Bat dau"',
          '-> chon anh do TU THU VIEN, thay vi tai len moi. Chi dung attach_image neu that su khong tim thay',
          'anh nao trong thu vien.',
          '',
          'BAT BUOC: canh nay DA CO anh mau, nen video PHAI duoc dung tu chinh anh do.',
          'TUYET DOI KHONG duoc chuyen sang che do van ban thanh video (text-to-video) de tao khong co anh —',
          'video tao kieu do se khac han anh storyboard, khong dung duoc, va con ton luot tra phi vo ich.',
          'Neu khong dua duoc anh vao sau khi da thu cac o dinh kem khac nhau, hay tra ve fail va mo ta ro',
          'da thu nhung gi, trang bao loi gi. KHONG bam tao video khi khe "Bat dau" con trong.',
        ].join('\n')
        : 'Khong co anh tham chieu — tao hoan toan tu prompt.',
      '',
      'Tab nay co the la tab nguoi dung DA mo san va da o dung man hinh tao video — hay xem ky snapshot',
      'truoc khi dieu huong di dau. Neu da thay o nhap prompt video va nut tao thi cu dung luon, khong can',
      'tim kiem them.',
      '',
      'Veo tao video mat vai phut. Sau khi bam tao, hay dung wait nhieu lan de cho, dung voi ket luan that bai.',
      'Chi tra ve done khi video KET QUA cua luot tao nay da xuat hien, kem index cua phan tu <video> do.',
      'Neu nut tao dang DISABLED, hay wait roi thu lai.',
      '',
      'PROMPT CAN GUI:',
      job.prompt,
    ].join('\n');
  }
  if (provider !== 'meta_ai_video') return null;
  return [
    'Tao MOT VIDEO NGAN co chuyen dong (KHONG phai anh tinh) bang tinh nang tao video cua Meta AI.',
    '',
    'LUU Y QUAN TRONG: khung chat thong thuong cua Meta AI KHONG tao duoc video — da thu va no tu choi, '
    + 'chi giai thich han che roi de xuat phuong an khac. Tinh nang tao video nam o muc "Vibes". '
    + 'Hay tim dung nut/man hinh TAO video moi (vi du nut "Tao", "Create", dau cong, hoac o nhap prompt '
    + 'cua man tao video) truoc khi go prompt.',
    '',
    hasReference
      ? 'CO san mot anh tham chieu. Khi da mo dung man tao video va thay o dinh kem file, hay dung '
        + 'attach_image de gan anh do lam khung hinh dau tien. Neu man tao video khong ho tro dinh kem anh '
        + 'thi cu tao tu prompt cung duoc.'
      : 'Khong co anh tham chieu — tao hoan toan tu prompt.',
    '',
    'CANH BAO: trang Vibes hien thi feed video cua NGUOI KHAC. Tuyet doi khong coi video trong feed la '
    + 'ket qua. Chi tra ve done khi video do CHINH luot tao nay sinh ra da xuat hien, kem index cua '
    + 'phan tu <video> do.',
    '',
    'Neu nut gui dang DISABLED, hay wait roi thu lai.',
    '',
    'PROMPT CAN GUI:',
    job.prompt,
  ].join('\n');
}

// Sites whose tab we reuse instead of opening a fresh one, and therefore
// must run one job at a time.
const REUSE_TAB_MATCH = {
  flow_veo: 'https://labs.google/*',
  flow_image: 'https://labs.google/*',
};

// Longest a single job may occupy the extension. Veo needs minutes, so this
// is generous — it exists only to stop a run that has silently wedged, which
// has happened at several different points (a suspended worker, a message
// that never gets a reply). Without it such a job holds its tab and, for
// shared-tab providers, blocks every job behind it until the server-side
// watchdog reclaims it many minutes later.
const JOB_TIMEOUT_MS = 12 * 60 * 1000;

async function withJobTimeout(job, promise) {
  let timer = null;
  const guard = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`Job ${job.id} quá ${Math.round(JOB_TIMEOUT_MS / 60000)} phút chưa xong — dừng để không giữ tab`)),
      JOB_TIMEOUT_MS,
    );
  });
  try {
    return await Promise.race([promise, guard]);
  } catch (error) {
    // runJob reports its own failures; this path is only reached when the
    // guard fired, so the server still believes the job is running.
    const message = String(error?.message || error);
    await setJobStatus(job.id, `job ${job.id}: LỖI - ${message}`);
    try {
      await fetch(
        `${FACTORY}/api/browser-scene-jobs/${job.id}/fail?error=${encodeURIComponent(message.slice(0, 2000))}`
        + `&claim_token=${encodeURIComponent(job.claim_token || '')}`,
        { method: 'POST' },
      );
    } catch { /* best-effort */ }
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

async function processOneJob(provider, job) {
  const shared = REUSE_TAB_MATCH[provider];
  // Keyed by the shared tab, not the provider: flow_image and flow_veo drive
  // the same Flow tab, so locking per provider would let them collide.
  if (shared) return withProviderTabLock(shared, () => withJobTimeout(job, runJob(provider, job)));
  return withJobTimeout(job, runJob(provider, job));
}

// Breadcrumbs to the app's access log. A stalled run leaves no trace at all
// otherwise — the job sits at "running" with no error and no requests, and
// the reason lives only in the service worker's own console.
function trace(jobId, stage, claimToken = '') {
  return fetch(
    `${FACTORY}/api/browser/trace?job=${jobId}&stage=${encodeURIComponent(stage)}&claim_token=${encodeURIComponent(claimToken)}`,
  )
    .catch(() => { /* tracing must never break the run */ });
}

async function runJob(provider, job) {
  const jobId = job.id;
  const projectId = job.project_id;
  let tabId = null;
  let createdTab = false;
  let persistentTab = false;
  try {
    await trace(jobId, `bat-dau-${provider}`, job.claim_token);
    let referenceImage = null;
    if (job.reference_asset_id) {
      try {
        referenceImage = await fetchReferenceImageBase64(job.reference_asset_id);
      } catch (error) {
        if (job.requires_reference_image) {
          throw new Error(
            `Image-to-video bị dừng vì không tải được ảnh nguồn; không chuyển ngầm sang text-to-video: ${String(error?.message || error)}`,
          );
        }
        console.warn('YT Factory: could not fetch optional reference image', error);
      }
    }
    if (job.requires_reference_image && !referenceImage) {
      throw new Error('Image-to-video bắt buộc có ảnh nguồn hợp lệ; job bị dừng trước khi gửi provider.');
    }
    await setJobStatus(jobId, `[${provider}] job ${jobId}: mở tab và gửi prompt${referenceImage ? ' (kèm ảnh tham chiếu)' : ''}...`);
    // Flow gets a project-scoped persistent tab. Other providers retain the
    // short-lived/reused tab behaviour they already had.
    const opened = provider.startsWith('flow_')
      ? await findOrCreateFlowWorkspaceTab(job)
      : await findOrCreateTab(PROVIDER_URLS[provider], {
        settleMs: 1500,
        reuseMatch: REUSE_TAB_MATCH[provider] || null,
      });
    tabId = opened.tabId;
    createdTab = opened.created;
    persistentTab = Boolean(opened.persistent);
    await trace(jobId, createdTab ? 'da-mo-tab-moi' : 'dung-lai-tab-co-san', job.claim_token);
    if (!createdTab || provider.startsWith('flow_')) {
      await setJobStatus(jobId, `[${provider}] job ${jobId}: dùng lại tab đang mở sẵn`);
      await ensureContentScripts(tabId);
      await trace(jobId, 'da-tiem-content-script', job.claim_token);
    }
    if (provider.startsWith('flow_') && opened.mustCreateProject) {
      await setJobStatus(jobId, `[${provider}] job ${jobId}: đang tạo project Flow riêng cho bộ cảnh...`);
      await trace(jobId, 'bat-dau-tao-project-flow', job.claim_token);
      await prepareFlowWorkspace(tabId, job);
      await trace(jobId, 'da-san-sang-project-flow', job.claim_token);
    } else if (provider.startsWith('flow_')) {
      // Refresh tab id/URL when a saved Flow project had to be reopened.
      await saveFlowWorkspace(job, tabId);
    }

    const goal = buildAgentGoal(provider, job, Boolean(referenceImage));
    // Separate trace either side of the tab work, so "stuck right after
    // opening the tab" can be told apart from "stuck deciding what to do".
    await trace(jobId, goal ? 'da-co-nhiem-vu' : 'khong-co-nhiem-vu', job.claim_token);
    let result;
    if (goal) {
      await trace(jobId, 'bat-dau-vong-lap-agent', job.claim_token);
      const finished = await runAgentInTab(tabId, goal, {
        // Veo takes minutes, so its run needs room for many wait steps.
        maxSteps: provider === 'flow_veo' ? 50 : 30,
        referenceImage,
        onStep: async (label) => {
          await setJobStatus(jobId, `[${provider}] job ${jobId}: ${label}`);
          await trace(jobId, label.slice(0, 100), job.claim_token);
        },
      });
      if (typeof finished.index !== 'number') {
        throw new Error('AI điều phối báo xong nhưng không chỉ ra phần tử kết quả');
      }
      result = await sendToTab(tabId, { type: 'ytf_agent_grab', index: finished.index });
      if (!result.ok) throw new Error(result.error || 'Không lấy được kết quả');
    } else {
      // Every browser provider now runs through the agent. A provider with no
      // goal would otherwise sit silently until the watchdog reclaimed it,
      // which is the failure mode this whole trace/heartbeat layer exists to
      // avoid — so say so immediately instead.
      throw new Error(`Chưa có mô tả nhiệm vụ (goal) cho provider ${provider}`);
    }

    await setJobStatus(jobId, `[${provider}] job ${jobId}: đang tải kết quả lên...`);
    let assetId;
    if (result.needsDownload) {
      await setJobStatus(jobId, `[${provider}] job ${jobId}: đang lưu video về máy...`);
      const filePath = await withDownloadGate(() => waitForNextDownload(
        () => runAgentInTab(tabId, [
          'Tai video vua tao ve may.',
          'Tim va bam nut/menu tai xuong (co the nam trong menu "Lua chon khac" hoac "...") cua DUNG video',
          'vua tao. Sau khi da bam vao muc tai xuong, tra ve done.',
        ].join('\n'), { maxSteps: 12 }),
        { timeoutMs: 240000 },
      ));
      assetId = await importLocalFile(projectId, filePath, 'video');
    } else {
      assetId = await uploadAsset(projectId, result.base64, result.mimeType, result.kind);
    }
    const completeResponse = await fetch(
      `${FACTORY}/api/browser-scene-jobs/${jobId}/complete?asset_id=${assetId}&claim_token=${encodeURIComponent(job.claim_token || '')}`,
      { method: 'POST' },
    );
    if (!completeResponse.ok) {
      const detail = await completeResponse.text().catch(() => '');
      throw new Error(`App từ chối hoàn tất job: HTTP ${completeResponse.status} ${detail.slice(0, 300)}`);
    }
    await setJobStatus(jobId, `[${provider}] job ${jobId}: xong -> asset ${assetId}`);
  } catch (error) {
    const message = String(error?.message || error);
    await setJobStatus(jobId, `[${provider}] job ${jobId}: LỖI - ${message}`);
    try {
      // These reports are the only window into what actually happened on the
      // page — 500 chars kept cutting them off mid-diagnosis.
      await fetch(
        `${FACTORY}/api/browser-scene-jobs/${jobId}/fail?error=${encodeURIComponent(message.slice(0, 2000))}&claim_token=${encodeURIComponent(job.claim_token || '')}`,
        { method: 'POST' },
      );
    } catch { /* best-effort */ }
  } finally {
    // Only close tabs we opened — the user's own tab carries the state that
    // made it usable in the first place.
    if (tabId != null && createdTab && !persistentTab) {
      try { await chrome.tabs.remove(tabId); } catch { /* tab may already be closed */ }
    }
  }
}

// Called only in reaction to a server push (see WebSocket onmessage below)
// — never on a timer. Claims and starts jobs (one atomic claim at a time,
// so concurrent notifications for the same provider can't double-claim)
// up to MAX_CONCURRENT_JOBS across all providers combined; each claimed
// job runs in its own tab without blocking the others.
async function handleProviderNotified(provider) {
  const enabled = await getEnabledProviders();
  if (!enabled.includes(provider)) return;
  while (activeJobs < MAX_CONCURRENT_JOBS) {
    let job;
    try {
      ({ job } = await apiGet(`/api/browser-scene-jobs/next?provider=${provider}`));
    } catch (error) {
      await setStatus(`Lỗi khi lấy job (${provider}): ${String(error?.message || error)}`);
      return;
    }
    if (!job) return; // queue empty for this provider
    activeJobs += 1;
    startKeepAlive();
    void processOneJob(provider, job).finally(() => {
      activeJobs -= 1;
      stopKeepAliveIfIdle();
    });
    if (activeJobs < MAX_CONCURRENT_JOBS) await new Promise((r) => setTimeout(r, CLAIM_STAGGER_MS));
  }
}

// ---- Đọc trang sản phẩm bằng phiên đã đăng nhập của trình duyệt này ----
//
// The app asks for one listing; it is opened in a background tab, read, and
// the tab is closed. Only what the page shows goes back: its text, its
// structured data, the prices on screen. No cookie, no password, no storage.
// The list below is the whole of what may be read this way - it is checked
// here, in the browser, whatever the app asks for.
const PAGE_READ_SITES = ['shopee.vn', 'lazada.vn', 'shop.tiktok.com', 'tiki.vn', 'sendo.vn'];
const PAGE_LOAD_TIMEOUT_MS = 45000;
const PAGE_SETTLE_MIN_MS = 2000;
const PAGE_SETTLE_MAX_MS = 12000;

function pageReadSite(url) {
  let host = '';
  try { host = new URL(url).hostname.toLowerCase(); } catch { return ''; }
  return PAGE_READ_SITES.find((site) => host === site || host.endsWith(`.${site}`)) || '';
}

// Same function as PROBE_JS in youtube_monitor/browser_sessions.py; keep the two identical.
function probePage() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const text = clean(document.body ? document.body.innerText : '').slice(0, 40000);
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .map((node) => (node.textContent || '').slice(0, 100000)).filter(Boolean).slice(0, 20);
  const meta = {};
  for (const node of document.querySelectorAll('meta')) {
    const key = (node.getAttribute('property') || node.getAttribute('name') || node.getAttribute('itemprop') || '').toLowerCase();
    if (!key || key in meta) continue;
    if (/^(og:|product:|twitter:)/.test(key) || ['description', 'title', 'price', 'pricecurrency'].includes(key)) {
      meta[key] = clean(node.getAttribute('content')).slice(0, 500);
    }
  }
  const money = /(₫\s?\d{1,3}(?:[.,]\d{3})+|\d{1,3}(?:[.,]\d{3})+\s?(?:₫|đ|vnđ|vnd)(?![a-z]))/i;
  const prices = [];
  for (const el of document.querySelectorAll('body *')) {
    if (prices.length >= 80) break;
    if (el.childElementCount > 3) continue;
    const raw = el.textContent || '';
    if (!raw || raw.length > 80) continue;
    const own = clean(el.innerText);
    if (!own || own.length > 40) continue;
    const found = own.match(money);
    if (!found) continue;
    if (Array.from(el.children).some((child) => clean(child.innerText) === own)) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    // A price is often a small wrapper around large digits: measure the largest
    // type inside it, and count it struck if any part of it is.
    const parts = [el, ...Array.from(el.querySelectorAll('*'))].map((node) => getComputedStyle(node));
    const size = Math.max(...parts.map((part) => parseFloat(part.fontSize) || 0));
    const struck = parts.some((part) => String(part.textDecorationLine || '').includes('line-through')) || !!el.closest('del, s, strike');
    const context = clean(el.parentElement ? el.parentElement.innerText : '').slice(0, 120);
    prices.push({ text: found[0], size, top: Math.round(box.top + window.scrollY), struck, context });
  }
  const images = Array.from(document.images)
    .filter((img) => (img.naturalWidth || img.width) >= 300 && (img.naturalHeight || img.height) >= 300)
    .map((img) => img.currentSrc || img.src)
    .filter((src) => /^https?:/.test(src));
  return { url: location.href, title: document.title || '', text, ld, meta, prices, images: Array.from(new Set(images)).slice(0, 12) };
}

function pageShowsAPrice() {
  return /(₫\s?\d|\d[.,]\d{3}\s?(₫|đ))/i.test(document.body ? document.body.innerText : '');
}

function waitForTabLoaded(tabId) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { chrome.tabs.onUpdated.removeListener(listener); resolve(); }, PAGE_LOAD_TIMEOUT_MS);
    function listener(updatedId, info) {
      if (updatedId === tabId && info.status === 'complete') {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function runInTab(tabId, func) {
  const [injection] = await chrome.scripting.executeScript({ target: { tabId }, func });
  return injection ? injection.result : null;
}

async function handlePageRead(message) {
  const requestId = message.request_id;
  const url = String(message.url || '');
  const reply = (payload) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'page_read_result', request_id: requestId, ...payload }));
    }
  };
  if (!pageReadSite(url)) {
    reply({ ok: false, error: `Extension chỉ đọc trang của: ${PAGE_READ_SITES.join(', ')}` });
    return;
  }
  let tabId = null;
  let windowId = null;
  activeJobs += 1;
  startKeepAlive();
  try {
    await setStatus(`Đang đọc trang sản phẩm: ${url.slice(0, 80)}`);
    // Its own window, not a background tab: measured on Shopee 29/09, a
    // listing in a hidden tab never fetches its price or its title. The page
    // is really shown - nothing about its visibility is faked.
    const win = await chrome.windows.create({ url, focused: false, type: 'normal', width: 1280, height: 900 });
    windowId = win.id;
    tabId = win.tabs && win.tabs[0] ? win.tabs[0].id : null;
    if (tabId == null) throw new Error('Không mở được cửa sổ đọc trang');
    await waitForTabLoaded(tabId);
    let visibility = '';
    try { visibility = await runInTab(tabId, () => document.visibilityState); } catch { /* still navigating */ }
    if (visibility !== 'visible') {
      // Covered by other windows the page counts as hidden; bring it forward
      // for the few seconds the read takes.
      await chrome.windows.update(windowId, { focused: true });
    }
    await new Promise((resolve) => setTimeout(resolve, PAGE_SETTLE_MIN_MS));
    for (let waited = PAGE_SETTLE_MIN_MS; waited < PAGE_SETTLE_MAX_MS; waited += 1000) {
      let ready = false;
      try { ready = await runInTab(tabId, pageShowsAPrice); } catch { /* page still navigating */ }
      if (ready) break;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    const current = await chrome.tabs.get(tabId);
    if (current.url && !pageReadSite(current.url)) {
      // Sent off the marketplace (a sign-in provider, say): report where, read nothing.
      reply({ ok: true, result: { url: current.url, title: current.title || '', text: '', ld: [], meta: {}, prices: [], images: [] } });
      return;
    }
    const result = (await runInTab(tabId, probePage)) || {};
    try { result.visibility = await runInTab(tabId, () => document.visibilityState); } catch { /* reported as unknown */ }
    reply({ ok: true, result });
    await setStatus('Đã đọc xong trang sản phẩm.');
  } catch (error) {
    reply({ ok: false, error: String(error?.message || error).slice(0, 500) });
  } finally {
    if (windowId != null) {
      try { await chrome.windows.remove(windowId); } catch { /* already closed */ }
    } else if (tabId != null) {
      try { await chrome.tabs.remove(tabId); } catch { /* already closed */ }
    }
    activeJobs -= 1;
    stopKeepAliveIfIdle();
  }
}

// Shows a marketplace page to the person as an ordinary tab, when the app
// asks - so they can sign in the way they always do. Nothing is read or typed.
async function handleOpenTab(message) {
  const url = String(message.url || '');
  const reply = (payload) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'open_tab_result', request_id: message.request_id, ...payload }));
    }
  };
  if (!pageReadSite(url)) {
    reply({ ok: false, error: `Extension chỉ mở trang của: ${PAGE_READ_SITES.join(', ')}` });
    return;
  }
  try {
    const tab = await chrome.tabs.create({ url, active: true });
    if (tab.windowId != null) await chrome.windows.update(tab.windowId, { focused: true });
    reply({ ok: true });
  } catch (error) {
    reply({ ok: false, error: String(error?.message || error).slice(0, 300) });
  }
}

function connectSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  socket = new WebSocket(WS_URL);
  socket.onopen = () => {
    reconnectDelayMs = 2000;
    // A service worker's user agent does not always carry Cốc Cốc's own token;
    // the client-hint brands name the browser either way.
    const agent = String(navigator.userAgent || '');
    const brands = (navigator.userAgentData?.brands || []).map((item) => String(item.brand || ''));
    const named = brands.find((brand) => !/chromium|not.?a.?brand/i.test(brand)) || '';
    const browser = /coc/i.test(named) || /coc_coc_browser/i.test(agent) ? 'Cốc Cốc'
      : /edge/i.test(named) || /Edg\//.test(agent) ? 'Edge' : named || 'Chrome';
    socket.send(JSON.stringify({
      type: 'hello',
      version: chrome.runtime.getManifest().version,
      capabilities: ['page_read', 'open_tab'],
      browser,
      sites: PAGE_READ_SITES,
    }));
    setStatus('Đã kết nối app — chờ job (không tự poll).');
  };
  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data && data.type === 'page_read') { void handlePageRead(data); return; }
    if (data && data.type === 'open_tab') { void handleOpenTab(data); return; }
    if (data && data.provider) handleProviderNotified(data.provider);
  };
  socket.onclose = () => {
    setStatus('Mất kết nối app — sẽ tự kết nối lại.');
    setTimeout(connectSocket, reconnectDelayMs);
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 60000);
  };
  socket.onerror = () => { try { socket.close(); } catch { /* already closing */ } };
}

// Relays a content script's "the AI asked a clarifying question" request to
// the app's orchestrator endpoint. Routed through here rather than fetched
// directly from the content script because page CSPs (chatgpt.com,
// gemini.google.com) can block a content-script-initiated fetch to an
// arbitrary origin even with host_permissions declared; a background
// service worker's fetch is a separate context, unaffected by the page's
// CSP either way.
// Converts via arrayBuffer rather than FileReader.readAsDataURL: a
// generated video can be tens of MB and building one giant data: URL
// string to then slice apart is wasteful, and chunked btoa keeps the call
// stack safe (String.fromCharCode applied to a whole multi-MB array
// overflows it).
async function blobToBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

// Downloads a generated result on behalf of a content script whose own
// fetch was blocked by CORS (see ytfImageToBase64 in content_common.js).
// Works only for hosts declared in manifest host_permissions.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_fetch_media') return false;
  (async () => {
    try {
      const response = await fetch(message.url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      sendResponse({ base64: await blobToBase64(blob), mimeType: blob.type || 'image/png' });
    } catch (error) {
      sendResponse({ base64: null, error: String(error?.message || error) });
    }
  })();
  return true;
});

// Relays the agent loop's "what should I do next?" to the orchestrator.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_browser_action') return false;
  (async () => {
    try {
      const response = await fetch(`${FACTORY}/api/orchestrator/browser-action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(message.payload || {}),
      });
      if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(`HTTP ${response.status} ${detail.slice(0, 200)}`);
      }
      sendResponse(await response.json());
    } catch (error) {
      sendResponse({ error: String(error?.message || error) });
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_craft_answer') return false;
  (async () => {
    try {
      const response = await fetch(`${FACTORY}/api/orchestrator/answer-prompt-question`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          original_prompt: message.originalPrompt || '',
          page_text: message.pageText || '',
          kind: message.kind || 'image',
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      sendResponse({ answer: data.answer || null });
    } catch (error) {
      sendResponse({ answer: null, error: String(error?.message || error) });
    }
  })();
  return true;
});

chrome.alarms.create('ytf-keepalive', { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'ytf-keepalive') connectSocket(); });
chrome.runtime.onInstalled.addListener(connectSocket);
chrome.runtime.onStartup.addListener(connectSocket);
connectSocket();
