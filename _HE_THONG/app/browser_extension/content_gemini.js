// Best-effort selectors for gemini.google.com/app — NOT verified against
// the live DOM (see popup.html troubleshooting note). If Gemini changes its
// markup these will need updating; open DevTools on the page to find the
// real ones and edit this file, then reload the extension (no re-login,
// no restart needed — that's the whole point of the extension approach).
const YTF_GEMINI_PROMPT_SELECTORS = [
  "div.ql-editor[contenteditable='true']",
  "div[contenteditable='true'][aria-label*='prompt' i]",
  "rich-textarea div[contenteditable='true']",
  "[contenteditable='true']",
];
const YTF_GEMINI_SUBMIT_SELECTORS = [
  "button[aria-label*='Send' i]",
  "button.send-button",
  "button[aria-label*='Gửi' i]",
];
const YTF_GEMINI_IMAGE_SELECTORS = [
  "img[alt*='Generated image' i]",
  "generated-image img",
  "single-image img",
  "image-preview img",
];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_generate' || message.provider !== 'gemini_web_image') return false;
  (async () => {
    try {
      const priorSrcs = ytfCollectExistingImageSrcs(YTF_GEMINI_IMAGE_SELECTORS);
      const promptBox = await ytfWaitFor(YTF_GEMINI_PROMPT_SELECTORS, { timeoutMs: 20000 });
      ytfTypeInto(promptBox, message.prompt);
      await new Promise((r) => setTimeout(r, 300));
      const submitBtn = await ytfWaitFor(YTF_GEMINI_SUBMIT_SELECTORS, { timeoutMs: 10000 });
      ytfClick(submitBtn);
      const imageSrc = await ytfWaitForNewImageWithFollowup(
        YTF_GEMINI_IMAGE_SELECTORS, priorSrcs, YTF_GEMINI_PROMPT_SELECTORS, YTF_GEMINI_SUBMIT_SELECTORS,
      );
      const { base64, mimeType } = await ytfImageToBase64(imageSrc);
      sendResponse({ ok: true, base64, mimeType });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true; // keep the message channel open for the async response
});
