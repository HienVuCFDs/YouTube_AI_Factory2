// Best-effort selectors for meta.ai — NOT verified against the live DOM
// (see popup.html troubleshooting note). Edit + reload extension (no
// re-login) if these stop matching after a Meta AI UI change.
// Meta AI can return either an image or a video reply depending on the
// prompt, so this checks for both and uploads whichever shows up first.
const YTF_META_PROMPT_SELECTORS = [
  "textarea[placeholder*='Imagine' i]",
  "textarea[placeholder*='Message' i]",
  "div[contenteditable='true']",
  "textarea",
];
const YTF_META_SUBMIT_SELECTORS = [
  "button[aria-label*='Send' i]",
  "button[type='submit']",
];
const YTF_META_IMAGE_SELECTORS = [
  "img[alt*='Generated' i]",
  "div[role='img']",
];
const YTF_META_VIDEO_SELECTORS = ["video"];

function ytfCollectExistingVideoSrcs() {
  const set = new Set();
  document.querySelectorAll(YTF_META_VIDEO_SELECTORS.join(',')).forEach((v) => { if (v.src) set.add(v.src); });
  return set;
}

function ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs = 180000, intervalMs = 1500 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      for (const selector of YTF_META_IMAGE_SELECTORS) {
        for (const img of document.querySelectorAll(selector)) {
          if (img.src && !priorImageSrcs.has(img.src) && img.complete && img.naturalWidth > 64) {
            return resolve({ kind: 'image', src: img.src });
          }
        }
      }
      for (const video of document.querySelectorAll(YTF_META_VIDEO_SELECTORS.join(','))) {
        if (video.src && !priorVideoSrcs.has(video.src) && video.readyState >= 2) {
          return resolve({ kind: 'video', src: video.src });
        }
      }
      if (Date.now() > deadline) return reject(new Error(`Khong thay ket qua moi sau ${Math.round(timeoutMs / 1000)}s`));
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

async function ytfWaitForNewImageOrVideoWithFollowup(priorImageSrcs, priorVideoSrcs, { totalTimeoutMs = 180000, firstWaitMs = 45000 } = {}) {
  try {
    return await ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs: firstWaitMs });
  } catch (firstError) {
    try {
      const promptBox = await ytfWaitFor(YTF_META_PROMPT_SELECTORS, { timeoutMs: 5000 });
      ytfTypeInto(promptBox, 'Yes, please go ahead and generate it directly now based on the description above. No need to ask anything further — just pick the best composition/style yourself and proceed.');
      await new Promise((r) => setTimeout(r, 300));
      const submitBtn = await ytfWaitFor(YTF_META_SUBMIT_SELECTORS, { timeoutMs: 5000 });
      ytfClick(submitBtn);
    } catch { /* fall through to the remaining wait / original timeout */ }
    return ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs: Math.max(totalTimeoutMs - firstWaitMs, 30000) });
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_generate' || message.provider !== 'meta_ai_video') return false;
  (async () => {
    try {
      const priorImageSrcs = ytfCollectExistingImageSrcs(YTF_META_IMAGE_SELECTORS);
      const priorVideoSrcs = ytfCollectExistingVideoSrcs();
      const promptBox = await ytfWaitFor(YTF_META_PROMPT_SELECTORS, { timeoutMs: 20000 });
      ytfTypeInto(promptBox, message.prompt);
      await new Promise((r) => setTimeout(r, 300));
      const submitBtn = await ytfWaitFor(YTF_META_SUBMIT_SELECTORS, { timeoutMs: 10000 });
      ytfClick(submitBtn);
      const result = await ytfWaitForNewImageOrVideoWithFollowup(priorImageSrcs, priorVideoSrcs);
      const { base64, mimeType } = await ytfImageToBase64(result.src);
      sendResponse({ ok: true, base64, mimeType, kind: result.kind });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true;
});
