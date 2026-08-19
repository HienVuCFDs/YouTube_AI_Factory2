// Generic "hands" for the orchestrator: reports what is on the page and
// performs one action at a time, without knowing anything about a specific
// site's layout.
//
// This replaces per-site hardcoded selector scripts. Those had to guess, up
// front, which element was the send button, where the download control hid,
// and what order to touch things in — and every guess that missed cost a
// full generate-and-fail cycle to discover. The site knows its own layout
// and the orchestrator can read it, so the decisions belong there; this file
// only supplies observations and carries out instructions.

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

let ytfSnapshotElements = [];

function ytfIsVisible(el) {
  const rect = el.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return false;
  const style = window.getComputedStyle(el);
  return style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
}

function ytfDescribeElement(el) {
  const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
  let text = '';
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    text = String(el.value || '').trim();
  } else {
    text = String(el.innerText || '').trim().replace(/\s+/g, ' ');
  }
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role') || (el.tagName === 'INPUT' ? el.type || '' : ''),
    label: label.slice(0, 120),
    text: text.slice(0, 120),
    disabled: Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true',
  };
}

// Media is included so the orchestrator can tell "the result has arrived"
// from "still generating" — that judgement was previously a fixed timeout.
function ytfTakeSnapshot() {
  ytfSnapshotElements = [];
  const described = [];
  const push = (el, extra = {}) => {
    const index = ytfSnapshotElements.length;
    ytfSnapshotElements.push(el);
    described.push({ i: index, ...ytfDescribeElement(el), ...extra });
  };
  for (const el of document.querySelectorAll(YTF_INTERACTIVE_SELECTOR)) {
    if (!ytfIsVisible(el)) continue;
    push(el);
    if (described.length >= 60) break;
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

function ytfPageTail() {
  return (document.body?.innerText || '').trim().slice(-1200).replace(/\s+/g, ' ');
}

async function ytfPerformAction(action) {
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
      if (typeof el.click === 'function' && el.tagName === 'BUTTON') {
        await new Promise((r) => setTimeout(r, 200));
        if (el.isConnected) el.click();
      }
      await new Promise((r) => setTimeout(r, 1500));
      return;
    case 'wait':
      await new Promise((r) => setTimeout(r, 5000));
      return;
    default:
      throw new Error(`Hanh dong khong ho tro: ${action.action}`);
  }
}

function ytfRequestAction(payload) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage({ type: 'ytf_browser_action', payload }, (response) => {
        if (!response || response.error) reject(new Error(response?.error || 'Khong goi duoc AI dieu phoi'));
        else resolve(response);
      });
    } catch (error) {
      reject(error);
    }
  });
}

// Runs the observe → decide → act loop until the orchestrator says done/fail
// or the step budget runs out. Returns the media element the run ended on,
// when there is one, so the caller can upload the result.
async function ytfRunAgent(goal, { maxSteps = 25 } = {}) {
  const history = [];
  for (let step = 1; step <= maxSteps; step += 1) {
    const elements = ytfTakeSnapshot();
    const decision = await ytfRequestAction({
      goal,
      url: location.href,
      elements,
      page_text: ytfPageTail(),
      history,
      step,
    });
    history.push(`${step}. ${decision.action}${decision.index != null ? `(${decision.index})` : ''} — ${decision.reason}`);
    if (decision.action === 'done') {
      const el = typeof decision.index === 'number' ? ytfSnapshotElements[decision.index] : null;
      return { ok: true, element: el, history };
    }
    if (decision.action === 'fail') {
      throw new Error(`AI dieu phoi dung lai: ${decision.reason}`);
    }
    try {
      await ytfPerformAction(decision);
    } catch (error) {
      history.push(`   loi khi thuc hien: ${String(error?.message || error)}`);
    }
  }
  throw new Error(`Het ${maxSteps} buoc ma chua xong. Da lam:\n${history.join('\n')}`);
}
