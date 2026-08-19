// Generic "hands" for the orchestrator: reports what is on the page and
// performs one action, without knowing anything about a specific site's
// layout.
//
// This replaces per-site hardcoded selector scripts. Those had to guess, up
// front, which element was the send button, where the download control hid,
// and what order to touch things in — and every guess that missed cost a
// full generate-and-fail cycle to discover. The site knows its own layout
// and the orchestrator can read it, so the decisions belong there.
//
// Deliberately stateless per message: the decide/act loop lives in
// background.js instead of here. A loop running inside the content script
// died the moment the page navigated ("the page keeping the extension port
// is moved into back/forward cache"), which is exactly what happens when
// the agent opens Vibes' create screen. The background worker survives
// navigation, and the content script is re-injected into the new page.

const YTF_INTERACTIVE_SELECTOR = [
  'button',
  '[role="button"]',
  '[role="menuitem"]',
  'a[href]',
  'textarea',
  'input:not([type="hidden"])',
  '[contenteditable="true"]',
  'select',
].join(',');

// Indices in a snapshot refer to this array until the next snapshot.
let ytfSnapshotElements = [];

function ytfIsVisible(el) {
  const rect = el.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return false;
  const style = window.getComputedStyle(el);
  return style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
}

function ytfDescribeElement(el) {
  const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
  const text = (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT')
    ? String(el.value || '').trim()
    : String(el.innerText || '').trim().replace(/\s+/g, ' ');
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role') || (el.tagName === 'INPUT' ? el.type || '' : ''),
    label: label.slice(0, 120),
    text: text.slice(0, 120),
    disabled: Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true',
  };
}

// Media is included so the orchestrator can tell "the result has arrived"
// from "still generating" — a judgement that used to be a fixed timeout.
function ytfTakeSnapshot() {
  ytfSnapshotElements = [];
  const described = [];
  const seen = new Set();
  const push = (el, extra = {}) => {
    if (seen.has(el)) return;
    seen.add(el);
    described.push({ i: ytfSnapshotElements.length, ...ytfDescribeElement(el), ...extra });
    ytfSnapshotElements.push(el);
  };

  const interactive = [...document.querySelectorAll(YTF_INTERACTIVE_SELECTOR)];
  let visible = interactive.filter(ytfIsVisible);
  // Chrome can defer layout in a tab that was never rendered (ours open with
  // active:false), making every rect 0x0 — an empty report would be
  // indistinguishable from a genuine load failure, so fall back to the
  // unfiltered list rather than claiming the page is blank.
  if (!visible.length && interactive.length) visible = interactive;
  for (const el of visible) {
    push(el);
    if (described.length >= 60) break;
  }

  // File inputs are almost always styled invisible (a button acts as their
  // label), yet they're the one element the orchestrator must target by index.
  for (const el of document.querySelectorAll("input[type='file']")) {
    push(el, { text: 'O DINH KEM FILE' });
  }

  for (const el of document.querySelectorAll('video, img')) {
    if (!ytfIsVisible(el)) continue;
    const src = el.currentSrc || el.src || '';
    if (!src) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 120 || rect.height < 120) continue; // skip icons/avatars
    push(el, { text: `src=${src.slice(0, 60)}` });
    if (described.length >= 80) break;
  }
  return described;
}

// Fills a specific file input the orchestrator picked. If it aimed at the
// button fronting a hidden input instead, click that and take whichever input
// it reveals — either is a reasonable thing for it to point at.
async function ytfAttachReferenceImageTo(el, base64, mimeType) {
  if (!el || !base64) return false;
  let input = el.tagName === 'INPUT' && el.type === 'file' ? el : null;
  if (!input) {
    ytfClick(el);
    await new Promise((r) => setTimeout(r, 800));
    input = document.querySelector("input[type='file']");
  }
  if (!input) return false;
  try {
    const byteChars = atob(base64);
    const bytes = new Uint8Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i += 1) bytes[i] = byteChars.charCodeAt(i);
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(new File([bytes], 'reference.png', { type: mimeType || 'image/png' }));
    input.files = dataTransfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  } catch {
    return false;
  }
}

async function ytfPerformAction(action, referenceImage) {
  const el = typeof action.index === 'number' ? ytfSnapshotElements[action.index] : null;
  switch (action.action) {
    case 'type':
      if (!el) throw new Error(`type: khong co phan tu index ${action.index}`);
      ytfTypeInto(el, action.text || '');
      await new Promise((r) => setTimeout(r, 600));
      return;
    case 'click':
      if (!el) throw new Error(`click: khong co phan tu index ${action.index}`);
      ytfClick(el);
      // Some controls only respond to the element's own activation path.
      if (el.tagName === 'BUTTON' && typeof el.click === 'function') {
        await new Promise((r) => setTimeout(r, 200));
        if (el.isConnected) el.click();
      }
      await new Promise((r) => setTimeout(r, 1500));
      return;
    case 'attach_image': {
      if (!referenceImage?.base64) throw new Error('attach_image: khong co anh tham chieu cho job nay');
      const ok = await ytfAttachReferenceImageTo(el, referenceImage.base64, referenceImage.mimeType);
      if (!ok) throw new Error('attach_image: khong gan duoc anh vao phan tu nay');
      await new Promise((r) => setTimeout(r, 2000));
      return;
    }
    case 'wait':
      await new Promise((r) => setTimeout(r, 5000));
      return;
    default:
      throw new Error(`Hanh dong khong ho tro: ${action.action}`);
  }
}

// A <video> playing through MediaSource exposes only a blob: URL that can't
// be fetched, but the page sometimes also carries a plain progressive URL.
function ytfFindDirectMediaUrl() {
  for (const el of document.querySelectorAll("video source[src], a[href*='.mp4'], a[download][href^='http']")) {
    const url = el.getAttribute('src') || el.getAttribute('href') || '';
    if (/^https?:/i.test(url)) return url;
  }
  return null;
}

async function ytfGrabMedia(index) {
  const el = ytfSnapshotElements[index];
  if (!el) throw new Error(`Khong co phan tu index ${index} de lay ket qua`);
  const isVideo = el.tagName === 'VIDEO';
  let src = el.currentSrc || el.src || '';
  if (!src) throw new Error('Phan tu ket qua khong co src');
  if (isVideo && src.startsWith('blob:')) src = ytfFindDirectMediaUrl() || src;
  if (src.startsWith('blob:')) {
    // Bytes live inside the player; background.js drives the site's own
    // download control and imports the file from disk instead.
    return { needsDownload: true, kind: 'video' };
  }
  const { base64, mimeType } = await ytfImageToBase64(src);
  return { base64, mimeType, kind: isVideo ? 'video' : 'image' };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message?.type?.startsWith('ytf_agent_')) return false;
  (async () => {
    try {
      if (message.type === 'ytf_agent_snapshot') {
        sendResponse({
          ok: true,
          url: location.href,
          elements: ytfTakeSnapshot(),
          pageText: (document.body?.innerText || '').trim().slice(-1200).replace(/\s+/g, ' '),
        });
        return;
      }
      if (message.type === 'ytf_agent_action') {
        await ytfPerformAction(message.action, message.referenceImage);
        sendResponse({ ok: true });
        return;
      }
      if (message.type === 'ytf_agent_grab') {
        sendResponse({ ok: true, ...(await ytfGrabMedia(message.index)) });
        return;
      }
      sendResponse({ ok: false, error: `Khong hieu lenh: ${message.type}` });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true;
});
