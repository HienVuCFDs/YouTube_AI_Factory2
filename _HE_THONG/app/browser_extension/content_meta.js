// Best-effort selectors for meta.ai — NOT verified against the live DOM
// (see popup.html troubleshooting note). Edit + reload extension (no
// re-login) if these stop matching after a Meta AI UI change.
// Meta AI can return either an image or a video reply depending on the
// prompt, so this checks for both and uploads whichever shows up first.
const YTF_META_PROMPT_SELECTORS = [
  "textarea[placeholder*='Describe' i]",
  "textarea[placeholder*='Imagine' i]",
  "textarea[placeholder*='Message' i]",
  "input[placeholder*='Describe' i]",
  "div[contenteditable='true']",
  "textarea",
];
// /vibes opens on a feed rather than a composer, so the prompt box may not
// exist until a "Create" affordance is clicked.
const YTF_META_CREATE_SELECTORS = [
  "button[aria-label*='Create' i]",
  "div[role='button'][aria-label*='Create' i]",
  "a[href*='/vibes/create' i]",
  "button[aria-label*='Make' i]",
  "button[aria-label*='Tạo' i]",
];
const YTF_META_SUBMIT_SELECTORS = [
  "button[aria-label*='Send' i]",
  "button[aria-label*='Gửi' i]",
  "button[data-testid*='send' i]",
  "button[type='submit']",
];
const YTF_META_IMAGE_SELECTORS = [
  "img[alt*='Generated' i]",
  "div[role='img']",
];
const YTF_META_VIDEO_SELECTORS = ["video"];
// Matched against aria-label AND visible text, in both languages: the live
// UI renders in Vietnamese ("Lựa chọn khác" for the overflow menu), and menu
// entries carry plain text rather than an aria-label, so CSS-only selectors
// missed them entirely.
const YTF_META_DOWNLOAD_TEXTS = ['tải xuống', 'tải về', 'download', 'save video'];
const YTF_META_MORE_TEXTS = ['lựa chọn khác', 'tùy chọn khác', 'more options', 'more'];
const YTF_META_CLICKABLE = "button, a, [role='button'], [role='menuitem'], [role='menuitemradio']";
const YTF_META_IMAGE_UPLOAD_SELECTORS = [
  "input[type='file']",
  "button[aria-label*='Add photo' i]",
  "button[aria-label*='Upload' i]",
  "button[aria-label*='Attach' i]",
];

function ytfCollectExistingVideoSrcs() {
  const set = new Set();
  document.querySelectorAll(YTF_META_VIDEO_SELECTORS.join(',')).forEach((v) => { if (v.src) set.add(v.src); });
  return set;
}

// Same rationale as ytfDescribeTimeoutState in content_common.js — on a
// meta.ai timeout we have no way to see the actual tab, so this reports
// what the selectors actually found (or didn't) instead of a bare "no
// result" message. Confirmed needed live: 3/3 meta_ai_video jobs timed out
// with only "Khong thay ket qua moi sau 135s" and no way to tell whether
// the image/video selectors never matched anything, matched a stale
// element, or a video appeared but never reached readyState >= 2.
function ytfDescribeMetaTimeoutState(priorImageSrcs, priorVideoSrcs) {
  let imgMatched = 0;
  let imgNew = 0;
  for (const selector of YTF_META_IMAGE_SELECTORS) {
    let found;
    try { found = document.querySelectorAll(selector); } catch { continue; }
    for (const img of found) {
      imgMatched += 1;
      if (ytfIsRealImageSrc(img.src) && !priorImageSrcs.has(img.src)) imgNew += 1;
    }
  }
  let videoMatched = 0;
  let videoNew = 0;
  let videoReady = 0;
  for (const video of document.querySelectorAll(YTF_META_VIDEO_SELECTORS.join(','))) {
    videoMatched += 1;
    if (video.src && !priorVideoSrcs.has(video.src)) {
      videoNew += 1;
      if (video.readyState >= 2) videoReady += 1;
    }
  }
  const lastText = (document.body?.innerText || '').trim().slice(-300).replace(/\s+/g, ' ');
  return `img selectors: ${imgMatched} phan tu (${imgNew} moi). video selectors: ${videoMatched} phan tu (${videoNew} moi, ${videoReady} san sang). Cuoi trang: "${lastText}"`;
}

// See ytfWaitForNewImage's comment in content_common.js: background
// (inactive) tabs never finish decoding images, so img.complete/
// naturalWidth is unreliable there — this uses the same
// src-persists-for-settleMs debounce instead. Video elements don't have
// that decode-throttling issue (readyState reflects metadata load, not
// paint), so the video branch keeps its original check.
function ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs = 180000, intervalMs = 1500, settleMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let candidate = null; // { src, firstSeenAt }
    const tick = () => {
      let foundSrc = null;
      for (const selector of YTF_META_IMAGE_SELECTORS) {
        for (const img of document.querySelectorAll(selector)) {
          if (ytfIsRealImageSrc(img.src) && !priorImageSrcs.has(img.src)) { foundSrc = img.src; break; }
        }
        if (foundSrc) break;
      }
      if (foundSrc) {
        if (candidate && candidate.src === foundSrc) {
          if (Date.now() - candidate.firstSeenAt >= settleMs) return resolve({ kind: 'image', src: foundSrc });
        } else {
          candidate = { src: foundSrc, firstSeenAt: Date.now() };
        }
      } else {
        candidate = null;
      }
      for (const video of document.querySelectorAll(YTF_META_VIDEO_SELECTORS.join(','))) {
        if (video.src && !priorVideoSrcs.has(video.src) && video.readyState >= 2) {
          return resolve({ kind: 'video', src: video.src });
        }
      }
      if (Date.now() > deadline) {
        return reject(new Error(`Khong thay ket qua moi sau ${Math.round(timeoutMs / 1000)}s. ${ytfDescribeMetaTimeoutState(priorImageSrcs, priorVideoSrcs)}`));
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

async function ytfWaitForNewImageOrVideoWithFollowup(priorImageSrcs, priorVideoSrcs, originalPrompt, { totalTimeoutMs = 180000, firstWaitMs = 45000 } = {}) {
  try {
    return await ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs: firstWaitMs });
  } catch (firstError) {
    const followupText = (await ytfAskOrchestratorForAnswer(originalPrompt, 'video'))
      || YTF_GENERIC_VIDEO_FOLLOWUP_TEXT;
    try {
      const promptBox = await ytfWaitFor(YTF_META_PROMPT_SELECTORS, { timeoutMs: 5000 });
      ytfTypeInto(promptBox, followupText);
      await new Promise((r) => setTimeout(r, 300));
      await ytfSubmitPrompt(promptBox, YTF_META_SUBMIT_SELECTORS, { timeoutMs: 5000 });
    } catch { /* fall through to the remaining wait / original timeout */ }
    return ytfWaitForNewImageOrVideo(priorImageSrcs, priorVideoSrcs, { timeoutMs: Math.max(totalTimeoutMs - firstWaitMs, 30000) });
  }
}

// Returns the prompt box, opening the composer first if /vibes landed on a
// feed with no input visible. Its failure message carries a page dump —
// without eyes on the tab, "khong tim thay phan tu khop" alone gives no way
// to tell "wrong selector" from "not on the composer screen at all".
async function ytfOpenMetaComposer() {
  try {
    return await ytfWaitFor(YTF_META_PROMPT_SELECTORS, { timeoutMs: 8000 });
  } catch {
    try {
      const createBtn = await ytfWaitFor(YTF_META_CREATE_SELECTORS, { timeoutMs: 8000 });
      ytfClick(createBtn);
      await new Promise((r) => setTimeout(r, 1500));
    } catch { /* no create affordance either — fall through to the retry below */ }
  }
  try {
    return await ytfWaitFor(YTF_META_PROMPT_SELECTORS, { timeoutMs: 15000 });
  } catch (error) {
    const buttons = [...document.querySelectorAll("button, div[role='button'], a")]
      .map((b) => (b.getAttribute('aria-label') || b.innerText || '').trim())
      .filter(Boolean).slice(0, 25).join(' | ');
    const lastText = (document.body?.innerText || '').trim().slice(-300).replace(/\s+/g, ' ');
    throw new Error(`${error.message} | URL: ${location.href} | Nut tren trang: ${buttons} | Cuoi trang: "${lastText}"`);
  }
}

// A <video> whose src is a MediaSource blob can't be fetched, but the page
// sometimes also carries a plain progressive URL (a <source> child, or a
// download link) that can — cheaper and more reliable than driving the UI,
// so it's worth one look before falling back to the download button.
function ytfFindDirectMediaUrl() {
  for (const el of document.querySelectorAll("video source[src], a[href*='.mp4'], a[download][href^='http']")) {
    const url = el.getAttribute('src') || el.getAttribute('href') || '';
    if (/^https?:/i.test(url)) return url;
  }
  return null;
}

function ytfMatchesText(el, patterns) {
  const label = `${el.getAttribute('aria-label') || ''} ${el.innerText || ''}`.toLowerCase();
  return patterns.some((pattern) => label.includes(pattern));
}

function ytfFindClickableByText(patterns, root = document) {
  for (const el of root.querySelectorAll(YTF_META_CLICKABLE)) {
    if (ytfMatchesText(el, patterns)) return el;
  }
  return null;
}

// Clicks the site's own Download control so the browser writes the real file
// to disk (background.js then hands its path to the app).
//
// /vibes is a feed of many videos, each with its own "Lựa chọn khác" menu,
// so this walks up from the <video> we actually generated and searches its
// nearest containers first — clicking the first overflow button on the page
// would open some unrelated video's menu and download the wrong clip.
function ytfClickableLabels(root = document) {
  return [...root.querySelectorAll(YTF_META_CLICKABLE)]
    .map((b) => (b.getAttribute('aria-label') || b.innerText || '').trim())
    .filter(Boolean);
}

async function ytfTriggerMetaDownload(videoSrc) {
  let video = null;
  for (const candidate of document.querySelectorAll('video')) {
    if (candidate.src === videoSrc) { video = candidate; break; }
  }
  const scopes = [];
  let node = video;
  for (let i = 0; node && i < 8; i += 1) { scopes.push(node); node = node.parentElement; }
  scopes.push(document.body);
  // Records what each interaction actually revealed. Clicking the overflow
  // menu and still not matching anything told us nothing about what the menu
  // contained — this diffs the clickable labels before/after each step so a
  // failure reports the real menu contents instead of the same static page
  // list every time.
  const trace = [];

  if (video) {
    const before = new Set(ytfClickableLabels());
    video.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    video.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    video.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 800));
    const appeared = ytfClickableLabels().filter((label) => !before.has(label));
    trace.push(`hover: ${appeared.slice(0, 15).join(' / ') || '(khong co gi moi)'}`);
  }

  for (const scope of scopes) {
    const direct = ytfFindClickableByText(YTF_META_DOWNLOAD_TEXTS, scope);
    if (direct) { ytfClick(direct); return true; }
  }

  // Feed tiles often expose only reactions; the download control lives in the
  // detail/lightbox view you get by opening the item.
  if (video) {
    const before = new Set(ytfClickableLabels());
    ytfClick(video);
    await new Promise((r) => setTimeout(r, 2500));
    const opened = ytfFindClickableByText(YTF_META_DOWNLOAD_TEXTS);
    if (opened) { ytfClick(opened); return true; }
    const appeared = ytfClickableLabels().filter((label) => !before.has(label));
    trace.push(`mo video: ${appeared.slice(0, 20).join(' / ') || '(khong mo ra gi)'}`);
  }

  let menuIndex = 0;
  for (const scope of scopes) {
    const more = ytfFindClickableByText(YTF_META_MORE_TEXTS, scope);
    if (!more) continue;
    menuIndex += 1;
    const before = new Set(ytfClickableLabels());
    ytfClick(more);
    await new Promise((r) => setTimeout(r, 2000));
    const item = ytfFindClickableByText(YTF_META_DOWNLOAD_TEXTS);
    if (item) { ytfClick(item); return true; }
    const appeared = ytfClickableLabels().filter((label) => !before.has(label));
    trace.push(`menu${menuIndex}: ${appeared.slice(0, 20).join(' / ') || '(khong mo ra gi)'}`);
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
    if (menuIndex >= 3) break; // enough evidence; don't keep poking the page
  }

  throw new Error(`Khong tim thay nut Download (video ${video ? 'tim thay' : 'KHONG tim thay'}). ${trace.join(' || ')}`);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_download' || message.provider !== 'meta_ai_video') return false;
  (async () => {
    try {
      await ytfRunAgent([
        'Tai video vua tao ve may.',
        'Tim va bam nut/menu tai xuong (co the nam trong menu "Lua chon khac") cua DUNG video vua tao o cuoi doan chat.',
        'Sau khi da bam vao muc tai xuong, tra ve done.',
      ].join('\n'), { maxSteps: 12 });
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_generate' || message.provider !== 'meta_ai_video') return false;
  (async () => {
    try {
      // The reference image still goes in mechanically: a file input can only
      // be filled by code, never by an instruction the orchestrator issues.
      let attached = false;
      if (message.referenceImageBase64) {
        attached = await ytfAttachReferenceImage(
          YTF_META_IMAGE_UPLOAD_SELECTORS, message.referenceImageBase64, message.referenceImageMimeType,
        );
        await new Promise((r) => setTimeout(r, 1500));
      }
      const goal = [
        'Tao MOT VIDEO NGAN co chuyen dong (khong phai anh tinh) tren trang nay.',
        attached
          ? 'Mot anh tham chieu DA duoc dinh kem san vao khung soan — dung no lam khung hinh dau tien.'
          : 'Khong co anh tham chieu.',
        '',
        'Cach lam: go doan prompt duoi day vao o nhap cua khung chat, gui di, roi cho AI tao xong video.',
        'Neu trang hoi lai de xac nhan, hay tra loi khang dinh rang muon VIDEO co chuyen dong va yeu cau tao ngay.',
        'Neu nut gui dang DISABLED, hay wait cho anh tai xong roi thu lai.',
        'Khi thay phan tu <video> ket qua xuat hien, tra ve done kem index cua chinh phan tu <video> do.',
        '',
        'PROMPT CAN GUI:',
        message.prompt,
      ].join('\n');

      const { element } = await ytfRunAgent(goal, { maxSteps: 30 });
      const src = element?.currentSrc || element?.src || '';
      if (!src) throw new Error('AI dieu phoi bao xong nhung khong chi ra phan tu ket qua');

      const isVideo = element.tagName === 'VIDEO';
      let mediaSrc = src;
      if (isVideo && mediaSrc.startsWith('blob:')) {
        mediaSrc = ytfFindDirectMediaUrl() || mediaSrc;
      }
      if (isVideo && mediaSrc.startsWith('blob:')) {
        // MediaSource blob: the bytes live inside the player and can't be
        // fetched, so background.js drives the site's own Download control
        // and imports the file from disk instead.
        sendResponse({ ok: true, kind: 'video', needsDownload: true, videoSrc: mediaSrc });
        return;
      }
      const { base64, mimeType } = await ytfImageToBase64(mediaSrc);
      sendResponse({ ok: true, base64, mimeType, kind: isVideo ? 'video' : 'image' });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true;
});
