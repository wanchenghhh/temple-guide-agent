import { $, h, icon, announce, prefersReducedMotion, debugBlock } from "./core.js?v=__APP_VERSION__";
import { renderMarkdown } from "./markdown.js?v=__APP_VERSION__";

const COLLAPSE_CHARS = 520;
const COLLAPSE_LINES = 9;
let stickToBottom = true;
let isProgrammatic = false;
let programmaticTimer;

function endProgrammaticScroll() {
  isProgrammatic = false;
  clearTimeout(programmaticTimer);
  updateJumpLatest();
}

export function programmaticScroll(action) {
  isProgrammatic = true;
  clearTimeout(programmaticTimer);
  programmaticTimer = setTimeout(endProgrammaticScroll, 400);
  action();
  updateJumpLatest();
}

export function initThread() {
  const scroller = $("logScroll");
  scroller.addEventListener(
    "scroll",
    () => {
      updateJumpLatest();
      if (isProgrammatic) return;
      stickToBottom = isNearBottom();
    },
    { passive: true }
  );
  scroller.addEventListener("scrollend", endProgrammaticScroll);
  const stopSticking = () => {
    stickToBottom = false;
    updateJumpLatest();
    endProgrammaticScroll();
  };
  scroller.addEventListener("wheel", (event) => {
    if (event.deltaY < 0) stopSticking();
  }, { passive: true });
  let touchY;
  scroller.addEventListener("touchstart", (event) => {
    touchY = event.touches[0].clientY;
  }, { passive: true });
  scroller.addEventListener("touchmove", (event) => {
    const clientY = event.touches[0].clientY;
    if (clientY > touchY) stopSticking();
    touchY = clientY;
  }, { passive: true });
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    if (["PageUp", "ArrowUp", "Home"].includes(event.key)) stopSticking();
  });
  $("jumpLatest").addEventListener("click", () => {
    scrollToBottom({ force: true, smooth: true });
    $("composerInput").focus({ preventScroll: true });
  });
  // Layout changes can change the bottom gap without a scroll event.
  const resizeObserver = new ResizeObserver(updateJumpLatest);
  resizeObserver.observe(scroller);
  resizeObserver.observe($("log"));
  window.addEventListener("pageshow", updateJumpLatest);
  updateJumpLatest();
}

function updateJumpLatest() {
  if (!$("jumpLatest")) return;
  $("jumpLatest").hidden = isNearBottom();
}

function isNearBottom() {
  const s = $("logScroll");
  if (!s) return true;
  return s.scrollHeight - s.scrollTop - s.clientHeight <= 80;
}

export function scrollToBottom({ force = false, smooth = false } = {}) {
  if (force) stickToBottom = true;
  const s = $("logScroll");
  if (!stickToBottom) {
    updateJumpLatest();
    return;
  }
  programmaticScroll(() => s.scrollTo({ top: s.scrollHeight, behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto" }));
  updateJumpLatest();
}

export function reveal(node, { focus = null, user = false } = {}) {
  if (!node) return;
  if (!stickToBottom && !user) {
    updateJumpLatest();
    return;
  }
  programmaticScroll(() => node.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" }));
  if (focus) focus.focus({ preventScroll: true });
}

export function append(node, { scroll = true } = {}) {
  removeHero();
  $("log").appendChild(node);
  updateJumpLatest();
  if (scroll) requestAnimationFrame(() => {
    if (!stickToBottom) {
      updateJumpLatest();
      return;
    }
    if (!node.isConnected) return;
    const scroller = $("logScroll");
    if (node.offsetHeight > scroller.clientHeight) {
      programmaticScroll(() => { scroller.scrollTop = node.offsetTop - 16; });
    } else {
      scrollToBottom();
    }
  });
  return node;
}

export function clearLog() {
  $("log").replaceChildren();
  stickToBottom = true;
  updateJumpLatest();
}

export function collapsible(text, cls = "bubble-text", { markdown = false } = {}) {
  const value = String(text || "");
  const long = value.length > COLLAPSE_CHARS || value.split("\n").length > COLLAPSE_LINES;
  const body = h("div", { class: cls, text: value });
  if (markdown) body.innerHTML = renderMarkdown(value);
  if (!long) return body;
  body.classList.add("is-clamped");
  const toggle = h("button", {
    type: "button",
    class: "btn-text more-toggle",
    "aria-expanded": "false",
    text: "展开全文",
  });
  toggle.addEventListener("click", () => {
    const open = body.classList.toggle("is-clamped") === false;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "收起" : "展开全文";
  });
  return h("div", { class: "collapsible" }, [body, toggle]);
}

function avatar() {
  return h("span", { class: "msg-avatar", "aria-hidden": "true", text: "助" });
}

export function userMessage(data, { animate = true, scroll = true } = {}) {
  const node = append(userRow(data, { animate }), { scroll: false });
  // A new send resumes following immediately; restored rows stay in place.
  if (scroll) scrollToBottom({ force: true });
  return node;
}

export function userRow({ text, omitted = 0 }, { animate = true } = {}) {
  const bubble = h("div", { class: "bubble bubble-user" });
  if (text) bubble.append(collapsible(text));
  if (omitted) bubble.append(h("div", { class: "bubble-note", text: `（本机只保存了前面一部分，省略 ${omitted} 字）` }));
  return h("div", { class: `msg msg-user${animate ? " enter" : ""}` }, [
    h("span", { class: "sr-only", text: "你：" }),
    bubble,
  ]);
}

function feedbackBar(initial, onFeedback) {
  const status = h("span", { class: "fb-status", role: "status" });
  const buttons = [];
  const mark = (value) => {
    for (const b of buttons) {
      b.setAttribute("aria-pressed", String(b.dataset.value === value));
      b.disabled = !!value;
    }
    status.textContent = value ? "已收到反馈，谢谢" : "";
  };
  const make = (value, glyph, label) => {
    const btn = h("button", {
      type: "button",
      class: "btn-text fb-btn",
      "aria-label": label,
      title: label,
      "aria-pressed": "false",
      dataset: { value },
      text: glyph,
      onClick: async () => {
        for (const b of buttons) b.disabled = true;
        try {
          await onFeedback(value);
          mark(value);
        } catch {
          for (const b of buttons) b.disabled = false;
          status.textContent = "反馈没发出去，稍后再试";
        }
      },
    });
    buttons.push(btn);
    return btn;
  };
  const bar = h("div", { class: "msg-feedback", role: "group", "aria-label": "这条回复有帮助吗" }, [
    make("up", "👍", "有帮助"),
    make("down", "👎", "没帮助"),
    status,
  ]);
  if (initial) mark(initial);
  return bar;
}

export function assistantMessage(text, { scroll = true, animate = true, speak = true, feedback = null, onFeedback = null } = {}) {
  const row = h("div", { class: `msg msg-assistant${animate ? " enter" : ""}` }, [
    avatar(),
    h("div", { class: "bubble bubble-assistant" }, [
      h("span", { class: "sr-only", text: "小助：" }),
      collapsible(text, "bubble-text", { markdown: true }),
      onFeedback ? feedbackBar(feedback, onFeedback) : null,
    ]),
  ]);
  if (speak) announce(`小助：${text}`);
  return append(row, { scroll });
}

export function systemLine(text, { divider = false, scroll = true } = {}) {
  return append(h("div", { class: `sys-line${divider ? " is-divider" : ""}`, role: "note" }, [h("span", { text })]), { scroll });
}

export function errorMessage({ text, onRetry = null, debug = "" }) {
  const actions = [];
  let row;
  if (onRetry) {
    actions.push(
      h("button", {
        type: "button",
        class: "btn btn-ghost btn-sm",
        text: "重试",
        onClick: () => {
          row.remove();
          onRetry();
        },
      })
    );
  }
  row = h("div", { class: "msg msg-assistant enter" }, [
    avatar(),
    h("div", { class: "bubble bubble-error", role: "alert" }, [
      h("div", { class: "err-line" }, [icon("alert", "err-icon"), h("span", { text })]),
      actions.length ? h("div", { class: "err-actions" }, actions) : null,
      debug ? debugBlock("调试信息", debug) : null,
    ]),
  ]);
  return append(row);
}

export function typing({ hint = "", slowHint = "" } = {}) {
  const hintNode = h("span", { class: "typing-hint", text: hint });
  const row = h("div", { class: "msg msg-assistant msg-typing", "aria-hidden": "true" }, [
    avatar(),
    h("div", { class: "bubble bubble-assistant bubble-typing" }, [
      h("span", { class: "typing-dots" }, [h("span"), h("span"), h("span")]),
      hintNode,
    ]),
  ]);
  append(row);
  announce(hint || "正在处理…");
  const timer = slowHint
    ? window.setTimeout(() => {
        hintNode.textContent = slowHint;
      }, 6000)
    : 0;
  return {
    done() {
      window.clearTimeout(timer);
      row.remove();
    },
  };
}

export function renderHero({ onChip, onMemory }) {
  if ($("hero")) return;
  const chip = (iconName, label, onClick) =>
    h("button", { type: "button", class: "hero-chip", onClick }, [icon(iconName), h("span", { text: label })]);
  const hero = h("section", { class: "hero enter", id: "hero", "aria-labelledby": "heroTitle" }, [
    h("div", { class: "hero-mark", "aria-hidden": "true", text: "助" }),
    h("h2", { id: "heroTitle", text: "今天有什么我可以帮忙的？" }),
    h("p", {
      class: "hero-sub",
      text: "我是小助。直接和我聊就行：告诉我你的事，我会记住；要写邮件、消息或文章，我先出草稿，你确认后才算定稿。",
    }),
    h("p", {
      class: "hero-sub",
      text: "也可以让我到点提醒你，或者按你的要求定时做点事。",
    }),
    h("div", { class: "hero-actions" }, [
      chip("doc", "记住我下周三出差", () => onChip("记住我下周三出差")),
      chip("edit", "帮我写一封请假邮件", () => onChip("帮我写一封请假邮件")),
      chip("bell", "明早八点提醒我", () => onChip("明早八点提醒我")),
      chip("sun", "最近有点累", () => onChip("最近有点累")),
      onMemory ? chip("doc", "你记得我什么", onMemory) : null,
    ]),
    h("p", { class: "hero-note", text: "草稿确认卡不过期，后点的决定会覆盖先点的 · 档案在右上角「档案」里随时可改" }),
  ]);
  $("log").appendChild(hero);
}

export function removeHero() {
  const hero = $("hero");
  if (hero) hero.remove();
}
