// Best-effort selectors for chatgpt.com — NOT verified against the live
// DOM (see popup.html troubleshooting note). Edit + reload extension (no
// re-login) if these stop matching after a ChatGPT UI change.
const YTF_CHATGPT_PROMPT_SELECTORS = [
  "#prompt-textarea",
  "div[contenteditable='true'][id='prompt-textarea']",
  "div[contenteditable='true']",
];
const YTF_CHATGPT_SUBMIT_SELECTORS = [
  "button[data-testid='send-button']",
  "button[aria-label*='Send' i]",
];
const YTF_CHATGPT_IMAGE_SELECTORS = [
  "img[alt*='Generated image' i]",
  "div[data-testid*='image'] img",
  ".agent-turn img",
];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'ytf_generate' || message.provider !== 'chatgpt_web_image') return false;
  (async () => {
    try {
      const priorSrcs = ytfCollectExistingImageSrcs(YTF_CHATGPT_IMAGE_SELECTORS);
      const promptBox = await ytfWaitFor(YTF_CHATGPT_PROMPT_SELECTORS, { timeoutMs: 20000 });
      ytfTypeInto(promptBox, message.prompt);
      await new Promise((r) => setTimeout(r, 300));
      const submitBtn = await ytfWaitFor(YTF_CHATGPT_SUBMIT_SELECTORS, { timeoutMs: 10000 });
      ytfClick(submitBtn);
      const imageSrc = await ytfWaitForNewImageWithFollowup(
        YTF_CHATGPT_IMAGE_SELECTORS, priorSrcs, YTF_CHATGPT_PROMPT_SELECTORS, YTF_CHATGPT_SUBMIT_SELECTORS, message.prompt,
      );
      const { base64, mimeType } = await ytfImageToBase64(imageSrc);
      sendResponse({ ok: true, base64, mimeType });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error) });
    }
  })();
  return true;
});
