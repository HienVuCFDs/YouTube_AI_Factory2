const CHECKBOXES = { gemini_web_image: 'p-gemini', chatgpt_web_image: 'p-chatgpt', meta_ai_video: 'p-meta' };

async function loadState() {
  const stored = await chrome.storage.local.get(['enabledProviders', 'lastStatus', 'lastStatusAt']);
  const enabled = new Set(stored.enabledProviders || Object.keys(CHECKBOXES));
  for (const [provider, id] of Object.entries(CHECKBOXES)) {
    document.getElementById(id).checked = enabled.has(provider);
  }
  const statusEl = document.getElementById('status');
  if (stored.lastStatus) {
    const secondsAgo = stored.lastStatusAt ? Math.round((Date.now() - stored.lastStatusAt) / 1000) : null;
    statusEl.textContent = `${stored.lastStatus}${secondsAgo != null ? ` (${secondsAgo}s trước)` : ''}`;
  } else {
    statusEl.textContent = 'Chưa có hoạt động nào — đang chờ app báo có job (không tự poll).';
  }
}

async function saveEnabledProviders() {
  const enabled = Object.entries(CHECKBOXES)
    .filter(([, id]) => document.getElementById(id).checked)
    .map(([provider]) => provider);
  await chrome.storage.local.set({ enabledProviders: enabled });
}

for (const id of Object.values(CHECKBOXES)) {
  document.getElementById(id).addEventListener('change', saveEnabledProviders);
}

loadState();
setInterval(loadState, 3000);
