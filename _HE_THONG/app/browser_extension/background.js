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
};
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

async function getEnabledProviders() {
  const stored = await chrome.storage.local.get('enabledProviders');
  return stored.enabledProviders || Object.keys(PROVIDER_URLS);
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

async function findOrCreateTab(url) {
  const tab = await chrome.tabs.create({ url, active: false });
  await new Promise((resolve) => {
    const listener = (tabId, info) => {
      if (tabId === tab.id && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(resolve, 15000);
  });
  await new Promise((r) => setTimeout(r, 1500));
  return tab.id;
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
  }
  throw new Error(`Tab khong phan hoi: ${String(lastError?.message || lastError)}`);
}

async function askOrchestratorForAction(payload) {
  const response = await fetch(`${FACTORY}/api/orchestrator/browser-action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(`Hoi AI dieu phoi -> HTTP ${response.status} ${detail.slice(0, 200)}`);
  }
  return response.json();
}

// The observe → decide → act loop. Lives here rather than in the content
// script so it survives the page navigations the agent itself causes.
async function runAgentInTab(tabId, goal, { maxSteps = 30, referenceImage = null, onStep = null } = {}) {
  const history = [];
  for (let step = 1; step <= maxSteps; step += 1) {
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

    const result = await sendToTab(tabId, {
      type: 'ytf_agent_action',
      action: decision,
      referenceImage: decision.action === 'attach_image' ? referenceImage : null,
    });
    if (!result.ok) history.push(`   loi khi thuc hien: ${result.error}`);
  }
  throw new Error(`Het ${maxSteps} buoc ma chua xong. Da lam:\n${history.join('\n')}`);
}

function buildAgentGoal(provider, job, hasReference) {
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

async function processOneJob(provider, job) {
  const jobId = job.id;
  const projectId = job.project_id;
  let tabId = null;
  try {
    let referenceImage = null;
    if (job.reference_asset_id) {
      try {
        referenceImage = await fetchReferenceImageBase64(job.reference_asset_id);
      } catch (error) {
        // Image-to-video is a nice-to-have on top of a working text-to-X
        // job — a failed reference fetch shouldn't abort the whole job.
        console.warn('YT Factory: could not fetch reference image', error);
      }
    }
    await setJobStatus(jobId, `[${provider}] job ${jobId}: mở tab và gửi prompt${referenceImage ? ' (kèm ảnh tham chiếu)' : ''}...`);
    tabId = await findOrCreateTab(PROVIDER_URLS[provider]);

    const goal = buildAgentGoal(provider, job, Boolean(referenceImage));
    let result;
    if (goal) {
      const finished = await runAgentInTab(tabId, goal, {
        maxSteps: 30,
        referenceImage,
        onStep: (label) => setJobStatus(jobId, `[${provider}] job ${jobId}: ${label}`),
      });
      if (typeof finished.index !== 'number') {
        throw new Error('AI điều phối báo xong nhưng không chỉ ra phần tử kết quả');
      }
      result = await sendToTab(tabId, { type: 'ytf_agent_grab', index: finished.index });
      if (!result.ok) throw new Error(result.error || 'Không lấy được kết quả');
    } else {
      // Providers still on their own scripted flow (Gemini/ChatGPT images,
      // which already work end to end) keep the original message contract.
      result = await chrome.tabs.sendMessage(tabId, {
        type: 'ytf_generate', provider, jobId, prompt: job.prompt, ratio: job.ratio,
        referenceImageBase64: referenceImage?.base64 || null,
        referenceImageMimeType: referenceImage?.mimeType || null,
      });
      if (!result || !result.ok) {
        throw new Error(result?.error || 'Content script không trả kết quả (có thể selector chưa khớp giao diện thật)');
      }
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
    await fetch(`${FACTORY}/api/browser-scene-jobs/${jobId}/complete?asset_id=${assetId}`, { method: 'POST' });
    await setJobStatus(jobId, `[${provider}] job ${jobId}: xong -> asset ${assetId}`);
  } catch (error) {
    const message = String(error?.message || error);
    await setJobStatus(jobId, `[${provider}] job ${jobId}: LỖI - ${message}`);
    try {
      await fetch(`${FACTORY}/api/browser-scene-jobs/${jobId}/fail?error=${encodeURIComponent(message.slice(0, 500))}`, { method: 'POST' });
    } catch { /* best-effort */ }
  } finally {
    if (tabId != null) {
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
    void processOneJob(provider, job).finally(() => { activeJobs -= 1; });
    if (activeJobs < MAX_CONCURRENT_JOBS) await new Promise((r) => setTimeout(r, CLAIM_STAGGER_MS));
  }
}

function connectSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  socket = new WebSocket(WS_URL);
  socket.onopen = () => {
    reconnectDelayMs = 2000;
    setStatus('Đã kết nối app — chờ job (không tự poll).');
  };
  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
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
