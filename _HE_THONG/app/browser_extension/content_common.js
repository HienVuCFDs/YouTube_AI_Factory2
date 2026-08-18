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
function ytfTypeInto(el, text) {
  el.focus();
  if ('value' in el) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set
      || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(el, text); else el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    el.textContent = text;
    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
  }
}

function ytfClick(el) {
  el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  el.click();
}

// Fetches an <img>/media src the page has already loaded (same-origin
// session cookies apply automatically since this runs as a page fetch, not
// a background-script cross-origin one) and returns {base64, mimeType}.
async function ytfImageToBase64(url) {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) throw new Error(`Khong tai duoc anh: HTTP ${response.status}`);
  const blob = await response.blob();
  const mimeType = blob.type || 'image/png';
  const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(new Error('Khong doc duoc du lieu anh'));
    reader.readAsDataURL(blob);
  });
  return { base64, mimeType };
}

function ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs = 180000, intervalMs = 1500 } = {}) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      for (const selector of containerSelectors) {
        const imgs = document.querySelectorAll(selector);
        for (const img of imgs) {
          if (img.src && !priorSrcs.has(img.src) && img.complete && img.naturalWidth > 64) {
            return resolve(img.src);
          }
        }
      }
      if (Date.now() > deadline) return reject(new Error(`Khong thay anh moi sau ${Math.round(timeoutMs / 1000)}s`));
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

function ytfCollectExistingImageSrcs(containerSelectors) {
  const set = new Set();
  for (const selector of containerSelectors) {
    document.querySelectorAll(selector).forEach((img) => { if (img.src) set.add(img.src); });
  }
  return set;
}
