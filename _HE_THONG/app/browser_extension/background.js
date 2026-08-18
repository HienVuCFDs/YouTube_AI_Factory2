// YT Factory AI Web Bridge — background service worker.
//
// Polls the local app's existing browser-sidecar queue (the same API
// web_video_sidecar.py uses: GET/POST /api/browser-scene-jobs/...) and, for
// each queued job, opens a background tab on the target AI site, asks that
// tab's content script to type the prompt and grab the result, then
// uploads it back. Runs inside the user's own already-logged-in browser
// profile — no separate Playwright browser, no separate login, ever.

const FACTORY = 'http://127.0.0.1:8787';
const POLL_PERIOD_MINUTES = 0.5; // 30s — chrome.alarms minimum period
const PROVIDER_URLS = {
  gemini_web_image: 'https://gemini.google.com/app',
  chatgpt_web_image: 'https://chatgpt.com/',
  meta_ai_video: 'https://www.meta.ai/',
};

let processing = false;

async function getEnabledProviders() {
  const stored = await chrome.storage.local.get('enabledProviders');
  return stored.enabledProviders || Object.keys(PROVIDER_URLS);
}

async function setStatus(text) {
  await chrome.storage.local.set({ lastStatus: text, lastStatusAt: Date.now() });
}

async function apiGet(path) {
  const response = await fetch(`${FACTORY}${path}`);
  if (!response.ok) throw new Error(`GET ${path} -> HTTP ${response.status}`);
  return response.json();
}

async function apiPost(path) {
  const response = await fetch(`${FACTORY}${path}`, { method: 'POST' });
  if (!response.ok) throw new Error(`POST ${path} -> HTTP ${response.status}`);
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

async function findOrCreateTab(url) {
  const tab = await chrome.tabs.create({ url, active: false });
  // Give the SPA a moment to boot before the content script's own element
  // waits kick in — most of these chat UIs render their shell fast but
  // hydrate interactivity a beat later.
  await new Promise((resolve) => {
    const listener = (tabId, info) => {
      if (tabId === tab.id && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(resolve, 15000); // don't wait forever if 'complete' never fires cleanly
  });
  await new Promise((r) => setTimeout(r, 1500));
  return tab.id;
}

async function processOneJob(provider, job) {
  const jobId = job.id;
  const projectId = job.project_id;
  let tabId = null;
  try {
    await setStatus(`[${provider}] job ${jobId}: mở tab và gửi prompt...`);
    tabId = await findOrCreateTab(PROVIDER_URLS[provider]);
    const result = await chrome.tabs.sendMessage(tabId, {
      type: 'ytf_generate', provider, jobId, prompt: job.prompt, ratio: job.ratio,
    });
    if (!result || !result.ok) {
      throw new Error(result?.error || 'Content script không trả kết quả (có thể selector chưa khớp giao diện thật)');
    }
    await setStatus(`[${provider}] job ${jobId}: đang tải kết quả lên...`);
    const assetId = await uploadAsset(projectId, result.base64, result.mimeType, result.kind);
    await apiPost(`/api/browser-scene-jobs/${jobId}/complete?asset_id=${assetId}`);
    await setStatus(`[${provider}] job ${jobId}: xong -> asset ${assetId}`);
  } catch (error) {
    const message = String(error?.message || error);
    await setStatus(`[${provider}] job ${jobId}: LỖI - ${message}`);
    try {
      await fetch(`${FACTORY}/api/browser-scene-jobs/${jobId}/fail?error=${encodeURIComponent(message.slice(0, 500))}`, { method: 'POST' });
    } catch { /* best-effort */ }
  } finally {
    if (tabId != null) {
      try { await chrome.tabs.remove(tabId); } catch { /* tab may already be closed */ }
    }
  }
}

async function pollOnce() {
  if (processing) return;
  processing = true;
  try {
    const providers = await getEnabledProviders();
    for (const provider of providers) {
      let job;
      try {
        const result = await apiGet(`/api/browser-scene-jobs/next?provider=${provider}`);
        job = result.job;
      } catch (error) {
        await setStatus(`Không kết nối được app (${FACTORY}): ${String(error?.message || error)}`);
        continue;
      }
      if (job) {
        await processOneJob(provider, job);
        return; // one job per poll tick, human-paced like the Python sidecar
      }
    }
    await setStatus('Đang chờ job (không có gì trong hàng đợi).');
  } finally {
    processing = false;
  }
}

chrome.alarms.create('ytf-poll', { periodInMinutes: POLL_PERIOD_MINUTES });
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'ytf-poll') pollOnce(); });
// Also fire once on install/startup instead of waiting a full period.
chrome.runtime.onInstalled.addListener(() => pollOnce());
chrome.runtime.onStartup.addListener(() => pollOnce());
