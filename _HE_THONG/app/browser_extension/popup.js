const CHECKBOXES = {
  gemini_web_image: 'p-gemini',
  chatgpt_web_image: 'p-chatgpt',
  meta_ai_video: 'p-meta',
  flow_veo: 'p-flow',
  flow_image: 'p-flow-image',
};

async function loadState() {
  const stored = await chrome.storage.local.get(['enabledProviders', 'lastStatus', 'lastStatusAt', 'jobStatuses']);
  const enabled = new Set(stored.enabledProviders || Object.keys(CHECKBOXES));
  for (const [provider, id] of Object.entries(CHECKBOXES)) {
    document.getElementById(id).checked = enabled.has(provider);
  }
  const statusEl = document.getElementById('status');
  const jobEntries = Object.values(stored.jobStatuses || {}).sort((a, b) => b.at - a.at);
  if (jobEntries.length) {
    // Several jobs can run at once (see background.js MAX_CONCURRENT_JOBS)
    // — show the recent handful, not just one overwritten line.
    statusEl.innerHTML = jobEntries
      .map((entry) => {
        const secondsAgo = Math.round((Date.now() - entry.at) / 1000);
        return `<div>${entry.text.replace(/</g, '&lt;')} <span style="color:#999">(${secondsAgo}s)</span></div>`;
      })
      .join('');
  } else if (stored.lastStatus) {
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
