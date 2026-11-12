import { $ } from "./core.js?v=__APP_VERSION__";

const DEFAULT_PLACEHOLDER = "说说你的心愿，或者直接让我推荐寺庙";

let busy = false;
let submitHandler = null;

export function initComposer({ onSubmit }) {
  submitHandler = onSubmit;
  const input = $("composerInput");
  input.addEventListener("input", () => {
    hideComposerError();
    autoGrow();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      submit();
    }
  });
  input.addEventListener("blur", () => {
    if (!input.value) input.placeholder = DEFAULT_PLACEHOLDER;
  });
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    submit();
  });
  window.addEventListener("resize", autoGrow);
}

export function focusComposer(placeholder = "") {
  const input = $("composerInput");
  input.placeholder = placeholder || (document.body.dataset.screen === "home" ? "周六想为家人求平安，带老人，不想爬山……" : DEFAULT_PLACEHOLDER);
  input.focus();
}

let lastPrefill = "";

/**
 * Put an editable starter sentence in the composer, caret at the end. Never clobbers text the
 * user typed themselves (only an empty box or our own previous prefill). Returns true if filled.
 */
export function prefillComposer(text, placeholder = "") {
  const input = $("composerInput");
  const current = input.value;
  if (current.trim() && current !== lastPrefill) {
    focusComposer(placeholder);
    return false;
  }
  input.value = text;
  lastPrefill = text;
  input.placeholder = placeholder || (document.body.dataset.screen === "home" ? "周六想为家人求平安，带老人，不想爬山……" : DEFAULT_PLACEHOLDER);
  hideComposerError();
  autoGrow();
  input.focus();
  input.setSelectionRange(text.length, text.length);
  return true;
}

export function showComposerError(text) {
  const box = $("composerError");
  box.textContent = text;
  box.hidden = false;
}

export function hideComposerError() {
  const box = $("composerError");
  box.hidden = true;
  box.textContent = "";
}

export function setComposerBusy(value) {
  busy = value;
  const send = $("btnSend");
  send.disabled = value;
  send.classList.toggle("is-loading", value);
  send.setAttribute("aria-label", value ? "正在处理上一条" : "发送");
  $("composer").setAttribute("aria-busy", String(value));
}

function autoGrow() {
  const input = $("composerInput");
  const max = window.innerHeight < 700 ? 132 : 180;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, max)}px`;
}

// Detail shortcuts send their question immediately without replacing an unfinished draft.
export function submitPrompt(text) {
  return submit(text);
}

async function submit(prompt = null) {
  const input = $("composerInput");
  const text = (prompt === null ? input.value : String(prompt)).trim();
  if (busy) {
    showComposerError("上一条还在处理，稍等一下再发。");
    return;
  }
  if (!text) {
    showComposerError("先输入点内容再发送。");
    input.focus();
    return;
  }
  hideComposerError();
  if (prompt === null) {
    input.value = "";
    input.placeholder = DEFAULT_PLACEHOLDER;
    autoGrow();
  }
  setComposerBusy(true);
  try {
    await submitHandler({ text, attachments: [] });
  } finally {
    setComposerBusy(false);
  }
}
