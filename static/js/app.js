import { initExperience, showHome } from "./experience.js?v=__APP_VERSION__";
import { initTempleWorkspace } from "./temple_workspace.js?v=__APP_VERSION__";
import { initSchedules } from "./schedules.js?v=__APP_VERSION__";
import { $, h, DEBUG, VERSION, toast } from "./core.js?v=__APP_VERSION__";
import { api } from "./api.js?v=__APP_VERSION__";
import { currentUserId, ensureSession } from "./identity.js?v=__APP_VERSION__";
import { store } from "./store.js?v=__APP_VERSION__";
import { initThread, scrollToBottom } from "./thread.js?v=__APP_VERSION__";
import { initComposer, focusComposer } from "./composer.js?v=__APP_VERSION__";
import { initDrawer, loadProfile, resetDrawer } from "./drawer.js?v=__APP_VERSION__";
import {
  sendComposer,
  askMemory,
  restoreTranscript,
  showHero,
  resetThread,
  loadProactive,
  noteProfileEdited,
} from "./flows.js?v=__APP_VERSION__";

let health = null;
let conversationStarted = false;
let lastUserId = currentUserId();

function badge(text, cls = "") {
  return h("span", { class: `badge${cls ? ` ${cls}` : ""}` }, [h("span", { class: "dot", "aria-hidden": "true" }), text]);
}

function renderDebugBadges() {
  if (!DEBUG) return;
  const box = $("debugBadges");
  box.replaceChildren();
  if (!health) {
    box.append(badge("服务离线", "is-off"), badge(`ui ${VERSION}`), badge(`user ${currentUserId()}`));
    return;
  }
  const fast = health.fast || (health.routing && health.routing.fast) || {};
  const strong = health.strong || (health.routing && health.routing.strong) || {};
  box.append(
    badge(
      `llm ${health.llm || "?"} · fast ${fast.provider || "?"}/${fast.model || "?"} · strong ${strong.provider || "?"}/${strong.model || "?"}`,
      health.llm === "live" ? "is-live" : "is-mock"
    ),
    badge(`api ${health.version || "?"} · ui ${VERSION}`),
    badge(`user ${currentUserId()}`)
  );
}

async function loadHealth() {
  try {
    health = await api.health();
  } catch {
    health = null;
  }
  renderDebugBadges();
}

function startConversation() {
  conversationStarted = true;
  if (!restoreTranscript()) showHero();
  showHome();
  loadProactive();
}

function onUserChange() {
  const uid = currentUserId();
  if (uid === lastUserId) return;
  const hadUser = lastUserId !== "pending";
  lastUserId = uid;
  store.reload();
  resetThread();
  resetDrawer();
  startConversation();
  renderDebugBadges();
  if (hadUser) toast("已切换账号，档案和对话记录随之切换");
}

function onClearLocal() {
  store.clear();
  resetThread();
  showHero();
  showHome();
  toast("已清除这台设备上的对话记录");
  focusComposer();
}

/* 一次性隐私告知：只在本机存标记；「看看记住了什么」直接打开记忆卡。 */
function initPrivacyNotice() {
  const banner = $("privacyBanner");
  if (!banner) return;
  const KEY = "pa.privacy.seen.v1";
  let seen = false;
  try { seen = localStorage.getItem(KEY) === "1"; } catch { seen = false; }
  if (!seen) banner.hidden = false;
  const dismiss = () => {
    banner.hidden = true;
    try { localStorage.setItem(KEY, "1"); } catch { /* 隐私模式下忽略 */ }
  };
  $("privacyDismiss")?.addEventListener("click", dismiss);
  $("privacyOpenMemory")?.addEventListener("click", () => {
    dismiss();
    askMemory();
  });
}

async function boot() {
  if (DEBUG) document.body.classList.add("is-debug");
  initThread();
  initTempleWorkspace();
  initExperience({ onResume: () => requestAnimationFrame(() => scrollToBottom({ force: true, replyStart: true })) });
  initSchedules();
  initComposer({ onSubmit: sendComposer });
  initDrawer({ onUserChange, onProfileEdited: noteProfileEdited, onClearLocal });
  $("btnMemory").addEventListener("click", () => askMemory());
  initPrivacyNotice();

  try {
    await ensureSession();
  } catch {
    /* requests retry the session themselves */
  }
  onUserChange();
  const healthReady = loadHealth();
  loadProfile();
  await Promise.race([healthReady, new Promise((resolve) => window.setTimeout(resolve, 1500))]);
  if (!conversationStarted) startConversation();
  if (document.body.dataset.screen !== "home" && window.matchMedia("(pointer: fine)").matches) focusComposer();
}

boot();
