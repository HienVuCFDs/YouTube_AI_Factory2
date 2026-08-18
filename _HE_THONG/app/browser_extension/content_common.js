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

// On timeout, builds a diagnostic string instead of a bare "no new image"
// message — was flying blind on 3 consistently-failing jobs with no way to
// tell "selector never matched anything" from "matched but never finished
// loading" from "the AI answered in text instead of generating an image
// this time" without eyes on the actual tab. Cheap to compute, only runs
// once when we're already about to fail.
function ytfDescribeTimeoutState(containerSelectors, priorSrcs) {
  let totalMatched = 0;
  let matchedNotNew = 0;
  let matchedNewNotLoaded = 0;
  for (const selector of containerSelectors) {
    let found;
    try { found = document.querySelectorAll(selector); } catch { continue; }
    for (const img of found) {
      totalMatched += 1;
      if (!img.src || priorSrcs.has(img.src)) { matchedNotNew += 1; continue; }
      if (!(img.complete && img.naturalWidth > 64)) matchedNewNotLoaded += 1;
    }
  }
  const lastText = (document.body?.innerText || '').trim().slice(-300).replace(/\s+/g, ' ');
  return `selectors matched ${totalMatched} phan tu (${matchedNotNew} khong moi, ${matchedNewNotLoaded} moi nhung chua load xong). Cuoi trang: "${lastText}"`;
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
      if (Date.now() > deadline) {
        return reject(new Error(`Khong thay anh moi sau ${Math.round(timeoutMs / 1000)}s. ${ytfDescribeTimeoutState(containerSelectors, priorSrcs)}`));
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

// Gemini/ChatGPT sometimes ask a clarifying question about style/layout
// instead of generating directly, or offer 2 candidate images to pick from
// — both leave the chat waiting on a human. This nudges it forward once:
// wait a shorter first window for an image; if none shows up (most likely
// a clarifying question, since a real 2-candidate reply already produces
// matchable <img> elements that ytfWaitForNewImage's first-match behavior
// picks from without needing an explicit choice), type a generic "just
// proceed" reply and submit again, then give it the rest of the budget.
async function ytfWaitForNewImageWithFollowup(
  containerSelectors, priorSrcs, promptSelectors, submitSelectors,
  { totalTimeoutMs = 180000, firstWaitMs = 45000, followupText = 'Yes, please go ahead and generate the image directly now based on the description above. No need to ask anything further — just pick the best composition/style yourself and proceed.' } = {},
) {
  try {
    return await ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs: firstWaitMs });
  } catch (firstError) {
    try {
      const promptBox = await ytfWaitFor(promptSelectors, { timeoutMs: 5000 });
      ytfTypeInto(promptBox, followupText);
      await new Promise((r) => setTimeout(r, 300));
      const submitBtn = await ytfWaitFor(submitSelectors, { timeoutMs: 5000 });
      ytfClick(submitBtn);
    } catch {
      // Couldn't send the nudge (prompt box busy/gone) — fall through and
      // let the remaining wait either catch a late image or time out with
      // the original diagnostic.
    }
    const remaining = Math.max(totalTimeoutMs - firstWaitMs, 30000);
    return ytfWaitForNewImage(containerSelectors, priorSrcs, { timeoutMs: remaining });
  }
}

function ytfCollectExistingImageSrcs(containerSelectors) {
  const set = new Set();
  for (const selector of containerSelectors) {
    document.querySelectorAll(selector).forEach((img) => { if (img.src) set.add(img.src); });
  }
  return set;
}
