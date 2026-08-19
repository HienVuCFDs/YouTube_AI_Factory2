// Shared helpers loaded before every site-specific content script (see
// manifest.json's "js" arrays). Kept selector-agnostic on purpose — each
// site script supplies its own selector list and calls into these.

function ytfWaitFor(selectors, { timeoutMs = 20000, intervalMs = 400 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      for (const selector of selectors) {
        const el = document.querySelector(selector);
        if (el) return resolve(el);
      }
      if (Date.now() > deadline) return reject(new Error(`Khong tim thay phan tu khop: ${selectors.join(', ')}`));
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

// Types into either a <textarea>/<input> or a contenteditable element,
// dispatching the input events these React/Angular-style chat UIs listen
// for (a plain .value= assignment is usually silently ignored by them).
//
// The contenteditable branch must go through execCommand('insertText')
// rather than assigning .textContent: meta.ai (and Messenger/Facebook)
// run Lexical, which keeps its own editor model and only updates it from
// real beforeinput/input events the browser generates. A .textContent
// assignment paints the text on screen while Lexical still believes the
// box is empty — which is exactly what was observed live: prompt visible
// in the chat box, never sent, and the Send button absent entirely
// (these UIs only render/enable it once their model has content, so the
// earlier "khong tim thay button[aria-label*='Send']" failure was this
// same bug, not a wrong selector).
// Rich-text editors listen for beforeinput on their OWN root element. Typing
// into a wrapper that merely looks like the field puts the characters in the
// DOM — visible on screen — while the editor never hears about them: on Flow
// the prompt showed with its placeholder still overlaid and the send button
// never unlocked. Resolve to the real editable host first.
function ytfResolveEditable(el) {
  if (!el) return el;
  if (el.isContentEditable) {
    return el.closest('[data-lexical-editor="true"]') || el;
  }
  return el.querySelector('[data-lexical-editor="true"], [contenteditable="true"]') || el;
}

function ytfTypeInto(target, text) {
  const el = ytfResolveEditable(target);
  el.focus();
  if ('value' in el) {
    // execCommand goes through the browser's own editing pipeline, so the
    // resulting input event is TRUSTED and carries the change the way a real
    // keystroke would — which is what React's value tracker actually
    // responds to. Assigning .value from a content script only produces a
    // synthetic event against an isolated-world wrapper, and React kept
    // treating the box as empty: on Flow the prompt text was visible while
    // the placeholder still showed over it and the "Tạo" button stayed
    // disabled through every retry.
    try {
      el.select();
      if (document.execCommand('insertText', false, text) && el.value === text) return;
    } catch {
      // execCommand can be unavailable/disabled — fall through.
    }
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set
      || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(el, text); else el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }
  const selectAll = () => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    selection.removeAllRanges();
    selection.addRange(range);
  };
  const landed = () => String(el.innerText || '').includes(text.slice(0, 30));

  selectAll();
  try {
    if (document.execCommand('insertText', false, text) && landed()) return;
  } catch { /* fall through to the beforeinput route */ }

  // Lexical (Flow's composer, and Meta's) drives its model from beforeinput
  // rather than from the DOM, so hand it one directly. Without this the text
  // lands in the DOM while the editor still believes it is empty — the
  // placeholder stayed visible over the prompt and the send control never
  // appeared.
  selectAll();
  el.dispatchEvent(new InputEvent('beforeinput', {
    bubbles: true, cancelable: true, composed: true, inputType: 'insertText', data: text,
  }));
  el.dispatchEvent(new InputEvent('input', {
    bubbles: true, composed: true, inputType: 'insertText', data: text,
  }));
  if (landed()) return;

  el.textContent = text;
  el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
}

// Sends one full pointer+mouse activation sequence, exactly once.
//
// The previous version dispatched mousedown/mouseup AND called el.click().
// Menus on meta.ai open on pointer/mouse-down, so the extra native click
// counted as a second activation and toggled them shut again — the observed
// result was "clicked the overflow button, nothing opened at all". Meta's UI
// also listens for PointerEvents, which plain MouseEvents never triggered.
function ytfClick(el) {
  const base = { bubbles: true, cancelable: true, composed: true, view: window, button: 0 };
  const down = { ...base, buttons: 1 };
  const up = { ...base, buttons: 0 };
  el.dispatchEvent(new PointerEvent('pointerover', down));
  el.dispatchEvent(new MouseEvent('mouseover', down));
  el.dispatchEvent(new PointerEvent('pointerdown', down));
  el.dispatchEvent(new MouseEvent('mousedown', down));
  if (typeof el.focus === 'function') el.focus();
  el.dispatchEvent(new PointerEvent('pointerup', up));
  el.dispatchEvent(new MouseEvent('mouseup', up));
  el.dispatchEvent(new MouseEvent('click', up));
}

// Fetches an <img>/media src the page has already loaded (same-origin
// session cookies apply automatically since this runs as a page fetch, not
// a background-script cross-origin one) and returns {base64, mimeType}.
function ytfBlobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(new Error('Khong doc duoc du lieu anh'));
    reader.readAsDataURL(blob);
  });
}

async function ytfImageToBase64(url) {
  try {
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    return { base64: await ytfBlobToBase64(blob), mimeType: blob.type || 'image/png' };
  } catch (pageError) {
    // A content-script fetch is subject to CORS against the media host, and
    // results live on separate CDNs (fbcdn.net, oaiusercontent.com, ...) that
    // don't send permissive CORS headers — that surfaced as a bare
    // "Failed to fetch" after generation had actually succeeded. The
    // background service worker's fetch bypasses CORS for hosts listed in
    // manifest host_permissions, so retry there. blob:/data: URLs are the
    // reverse case (page-scoped, invisible to the worker), hence page-first.
    if (/^https?:/i.test(url)) {
      const relayed = await new Promise((resolve) => {
        try {
          chrome.runtime.sendMessage({ type: 'ytf_fetch_media', url }, (response) => resolve(response || null));
        } catch { resolve(null); }
      });
      if (relayed?.base64) return { base64: relayed.base64, mimeType: relayed.mimeType || 'image/png' };
      throw new Error(`Khong tai duoc ket qua: ${String(pageError?.message || pageError)} (background: ${relayed?.error || 'khong phan hoi'}) | URL: ${url.slice(0, 200)}`);
    }
    throw new Error(`Khong tai duoc ket qua: ${String(pageError?.message || pageError)} | URL: ${url.slice(0, 200)}`);
  }
}

// Chrome throttles image decode/paint in background (inactive) tabs —
// confirmed live: a real, correct new <img src> showed up but img.complete
// / naturalWidth never became true because the tab was never focused
// (background.js opens tabs with active:false on purpose, to not disrupt
// the user's browsing). Since the actual bytes are fetched separately via
// ytfImageToBase64() rather than read off the decoded <img> element, that
// browser-side "finished loading" signal was never actually needed — only
// used as a proxy for "is this a real result, not a stray icon". Replaced
// with a same-src-persists-for-settleMs debounce: cheap, doesn't depend on
// paint/decode happening, and still guards against grabbing a blurry
// placeholder mid-transition (a real placeholder->final swap changes the
// src again before it can settle).
function ytfIsRealImageSrc(src) {
  return Boolean(src) && /^https?:\/\//i.test(src);
}

// On timeout, builds a diagnostic string instead of a bare "no new image"
// message — was flying blind on 3 consistently-failing jobs with no way to
// tell "selector never matched anything" from "matched but src never
// settled" from "the AI answered in text instead of generating an image
// this time" without eyes on the actual tab. Cheap to compute, only runs
// once when we're already about to fail.
function ytfDescribeTimeoutState(containerSelectors, priorSrcs) {
  let totalMatched = 0;
  let matchedNotNew = 0;
  let matchedNew = 0;
  for (const selector of containerSelectors) {
    let found;
    try { found = document.querySelectorAll(selector); } catch { continue; }
    for (const img of found) {
      totalMatched += 1;
      if (!ytfIsRealImageSrc(img.src) || priorSrcs.has(img.src)) { matchedNotNew += 1; continue; }
      matchedNew += 1;
    }
  }
  const lastText = (document.body?.innerText || '').trim().slice(-300).replace(/\s+/g, ' ');
  return `selectors matched ${totalMatched} phan tu (${matchedNotNew} khong moi, ${matchedNew} moi nhung khong on dinh). Cuoi trang: "${lastText}"`;
}

function ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs = 180000, intervalMs = 1500, settleMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let candidate = null; // { src, firstSeenAt }
    const tick = () => {
      let found = null;
      for (const selector of containerSelectors) {
        for (const img of document.querySelectorAll(selector)) {
          if (ytfIsRealImageSrc(img.src) && !priorSrcs.has(img.src)) { found = img.src; break; }
        }
        if (found) break;
      }
      if (found) {
        if (candidate && candidate.src === found) {
          if (Date.now() - candidate.firstSeenAt >= settleMs) return resolve(found);
        } else {
          candidate = { src: found, firstSeenAt: Date.now() };
        }
      } else {
        candidate = null;
      }
      if (Date.now() > deadline) {
        return reject(new Error(`Khong thay anh moi sau ${Math.round(timeoutMs / 1000)}s. ${ytfDescribeTimeoutState(containerSelectors, priorSrcs)}`));
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

// Relays "the AI asked a clarifying question" to the app's orchestrator
// (Claude Code / Codex CLI — the user's own logged-in subscription) via the
// background script, which crafts a short, natural, context-aware reply
// instead of us guessing. Falls back to a generic canned reply if the
// orchestrator call fails (not logged in, app unreachable, etc.) — a
// slightly awkward nudge still beats not trying at all.
// `kind` decides whether the crafted reply asks for a still or a clip —
// without it every reply asked for an image, so a video job that hit a
// clarifying question came back with a picture instead of a video.
function ytfAskOrchestratorForAnswer(originalPrompt, kind = 'image') {
  return new Promise((resolve) => {
    const pageText = (document.body?.innerText || '').trim().slice(-1500);
    try {
      chrome.runtime.sendMessage({ type: 'ytf_craft_answer', originalPrompt, pageText, kind }, (response) => {
        resolve(response?.answer || null);
      });
    } catch {
      resolve(null);
    }
  });
}

const YTF_GENERIC_FOLLOWUP_TEXT = 'Yes, please go ahead and generate the image directly now based on the description above. No need to ask anything further — just pick the best composition/style yourself and proceed.';
const YTF_GENERIC_VIDEO_FOLLOWUP_TEXT = 'Yes, please go ahead and generate the animated VIDEO clip directly now based on the description above — not a still image. No need to ask anything further; pick the best approach yourself and proceed.';

// Gemini/ChatGPT sometimes ask a clarifying question about style/layout
// instead of generating directly, or offer 2 candidate images to pick from
// — both leave the chat waiting on a human. This nudges it forward once:
// wait a shorter first window for an image; if none shows up (most likely
// a clarifying question, since a real 2-candidate reply already produces
// matchable <img> elements that ytfWaitForNewImage's first-match behavior
// picks from without needing an explicit choice), ask the orchestrator to
// write a reply and submit it, then give it the rest of the budget.
async function ytfWaitForNewImageWithFollowup(
  containerSelectors, priorSrcs, promptSelectors, submitSelectors, originalPrompt,
  { totalTimeoutMs = 180000, firstWaitMs = 45000 } = {},
) {
  try {
    return await ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs: firstWaitMs });
  } catch (firstError) {
    const followupText = (await ytfAskOrchestratorForAnswer(originalPrompt)) || YTF_GENERIC_FOLLOWUP_TEXT;
    try {
      const promptBox = await ytfWaitFor(promptSelectors, { timeoutMs: 5000 });
      ytfTypeInto(promptBox, followupText);
      await new Promise((r) => setTimeout(r, 300));
      await ytfSubmitPrompt(promptBox, submitSelectors, { timeoutMs: 5000 });
    } catch {
      // Couldn't send the nudge (prompt box busy/gone) — fall through and
      // let the remaining wait either catch a late image or time out with
      // the original diagnostic.
    }
    const remaining = Math.max(totalTimeoutMs - firstWaitMs, 30000);
    return ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs: remaining });
  }
}

function ytfComposerText(el) {
  return String('value' in el ? el.value : el.innerText || '').trim();
}

// Finds the send control by aria-label/title near the composer. It's an
// icon-only button whose markup and label language vary, so a fixed selector
// list keeps missing it; searching outward from the composer itself avoids
// grabbing an unrelated button elsewhere on the page.
function ytfFindSubmitNear(promptEl) {
  const patterns = ['send', 'gửi', 'gui', 'submit'];
  let node = promptEl;
  for (let i = 0; node && i < 6; i += 1) {
    for (const el of node.querySelectorAll("button, [role='button']")) {
      const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`.toLowerCase();
      if (patterns.some((pattern) => label.includes(pattern))) return el;
    }
    node = node.parentElement;
  }
  return null;
}

function ytfSendEnter(promptEl) {
  promptEl.focus();
  // Focusing a contenteditable does not by itself put a caret inside it, and
  // an editor that sees no selection of its own ignores the keystroke — so
  // place the caret at the end before dispatching.
  if (!('value' in promptEl)) {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(promptEl);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  for (const type of ['keydown', 'keypress', 'keyup']) {
    const event = new KeyboardEvent(type, {
      key: 'Enter', code: 'Enter', bubbles: true, cancelable: true, composed: true,
    });
    // keyCode/which are readonly getters on KeyboardEvent.prototype — the
    // constructor's options bag silently ignores them and they read back
    // as 0, so a handler doing `if (e.keyCode === 13)` (still very common
    // in chat UIs) never fires. They have to be redefined per-event.
    Object.defineProperty(event, 'keyCode', { get: () => 13 });
    Object.defineProperty(event, 'which', { get: () => 13 });
    promptEl.dispatchEvent(event);
  }
}

// Submits the composer and VERIFIES the prompt actually went out.
//
// This used to fire a click (or Enter) and return either way, so a failed
// submit was indistinguishable from a successful one: the prompt sat visibly
// in the box while the job burned its whole multi-minute wait and then failed
// with a misleading "no result appeared". Checking that the composer emptied
// turns that into an immediate error naming exactly what was tried.
async function ytfSubmitPrompt(promptEl, submitSelectors, { timeoutMs = 4000 } = {}) {
  // "Composer is empty" is the wrong test when promptEl turns out to be a
  // wrapper rather than the editor itself: leftover placeholder text would
  // make a successful send look failed. Track the prompt's own opening text
  // instead — that disappears on send no matter what else the node holds.
  const before = ytfComposerText(promptEl);
  const marker = before.slice(0, 40);
  const startUrl = location.href;
  const sent = () => {
    // A successful send re-renders the composer (and routes from / to
    // /prompt/<id>). The old node is then detached — and a detached
    // textarea keeps its .value, so reading text off it reported "not
    // sent" forever even though the prompt had gone through.
    if (!promptEl.isConnected) return true;
    if (location.href !== startUrl) return true;
    return marker
      ? !ytfComposerText(promptEl).includes(marker)
      : ytfComposerText(promptEl).length === 0;
  };
  const settle = () => new Promise((r) => setTimeout(r, 1500));
  const tried = [];

  const findButton = () => {
    for (const selector of submitSelectors) {
      let found = null;
      try { found = document.querySelector(selector); } catch { found = null; }
      if (found) return found;
    }
    return ytfFindSubmitNear(promptEl);
  };
  const isEnabled = (el) => el && !el.disabled && el.getAttribute('aria-disabled') !== 'true';

  // With a reference image attached the send button sits disabled until the
  // site finishes its own upload — measured live: disabled=true with an
  // image, disabled=false without one. Clicking through that window did
  // nothing, so wait for it to unlock before attempting anything.
  let button = findButton();
  const enableDeadline = Date.now() + Math.max(timeoutMs, 45000);
  while (!isEnabled(button) && Date.now() < enableDeadline) {
    await new Promise((r) => setTimeout(r, 1000));
    button = findButton();
  }

  // The send button is found reliably (aria-label "Gửi"), but a dispatched
  // click alone did not activate it, so this walks through progressively
  // different activation routes and checks after each one. Verification is
  // what makes trying several safe: the first that empties the composer wins
  // and the rest never run.
  const attempts = [];
  if (button) {
    const name = button.getAttribute('aria-label') || button.tagName;
    attempts.push([`click(${name})`, () => ytfClick(button)]);
    // Native .click() carries activation semantics a synthetic MouseEvent
    // doesn't, and some handlers sit on the inner icon rather than the button.
    attempts.push(['native-click', () => button.click?.()]);
    attempts.push(['click-child', () => {
      const child = button.querySelector('svg, span, div, i');
      if (child) ytfClick(child);
    }]);
  }
  attempts.push(['enter', () => ytfSendEnter(promptEl)]);
  attempts.push(['form-submit', () => {
    const form = promptEl.closest('form');
    if (form) (form.requestSubmit ? form.requestSubmit() : form.submit());
  }]);

  for (const [name, run] of attempts) {
    tried.push(name);
    try { run(); } catch { /* try the next route */ }
    await settle();
    if (sent()) return;
  }

  // Nearest ancestor that actually holds buttons — the immediate parents of a
  // contenteditable usually hold none, which is why the previous diagnostic
  // reported "(khong co)" and told us nothing.
  let composer = promptEl.parentElement;
  for (let i = 0; composer && i < 6; i += 1) {
    if (composer.querySelector("button, [role='button']")) break;
    composer = composer.parentElement;
  }
  const clickables = composer ? [...composer.querySelectorAll("button, [role='button']")] : [];
  const labels = clickables
    .map((el) => (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || '').trim())
    .filter(Boolean).slice(0, 20).join(' / ');
  // A send button that is present but refuses every activation route is
  // usually disabled because the composer's own state says "nothing to
  // send" — worth knowing before hunting for more ways to click it.
  const buttonState = button
    ? `disabled=${button.disabled ?? 'n/a'} aria-disabled=${button.getAttribute('aria-disabled') ?? 'n/a'}`
    : 'khong tim thay nut';
  const attached = document.querySelectorAll("input[type='file']").length;
  throw new Error(
    `Khong gui duoc prompt (da thu: ${tried.join(', ')}). Nut Gui: ${buttonState}. `
    + `O nhap: <${promptEl.tagName.toLowerCase()}> con giu "${ytfComposerText(promptEl).slice(0, 60)}". `
    + `So input file: ${attached}. Nut quanh khung soan: ${labels || '(khong co)'}`,
  );
}

function ytfCollectExistingImageSrcs(containerSelectors) {
  const set = new Set();
  for (const selector of containerSelectors) {
    document.querySelectorAll(selector).forEach((img) => { if (img.src) set.add(img.src); });
  }
  return set;
}

// Image-to-video: attaches an existing scene image as the starting frame
// before submitting the prompt. Best-effort, same unverified-selector
// caveat as everything else here — tries a direct <input type=file> first
// (common when an "Add image" button is really just a styled label for a
// hidden input), then falls back to clicking an upload affordance and
// hoping it reveals one. Returns false rather than throwing on failure —
// image-to-video is additive on top of a working text-to-X job, not a hard
// requirement, so a failed attach should fall through to generating from
// the prompt alone rather than aborting the job.
async function ytfAttachReferenceImage(uploadSelectors, base64, mimeType, filename = 'reference.png') {
  if (!base64) return false;
  let file;
  try {
    const byteChars = atob(base64);
    const bytes = new Uint8Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i += 1) bytes[i] = byteChars.charCodeAt(i);
    file = new File([bytes], filename, { type: mimeType || 'image/png' });
  } catch {
    return false;
  }
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  const assign = (input) => {
    input.files = dataTransfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const directInput = document.querySelector("input[type='file']");
  if (directInput) {
    assign(directInput);
    return true;
  }
  try {
    const button = await ytfWaitFor(uploadSelectors, { timeoutMs: 5000 });
    ytfClick(button);
    await new Promise((r) => setTimeout(r, 500));
    const revealedInput = document.querySelector("input[type='file']");
    if (revealedInput) {
      assign(revealedInput);
      return true;
    }
  } catch {
    // No upload affordance found — caller proceeds without a reference image.
  }
  return false;
}
