// Page primitives shared by content_agent.js, loaded before it on every
// site (see manifest.json's "js" arrays).
//
// Holds only what the agent uses. The rest of this file served the old
// per-site scripted flows (content_gemini.js / content_chatgpt.js /
// content_meta.js) and went with them. Keeping it around was actively
// misleading: a stale extension produced "Khong thay anh moi sau 135s"
// from code no live path could reach, which read as a Gemini fault when
// Gemini was in fact still drawing the image.

// Rich-text editors listen for beforeinput on their OWN root element.
// Typing into a wrapper that merely looks like the field puts the
// characters in the DOM — visible on screen — while the editor never hears
// about them: on Flow the prompt showed with its placeholder still overlaid
// and the send button never unlocked. Resolve to the real editable host.
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
