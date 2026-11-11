/** A single composer moves between the welcome screen and the working conversation. */
let initialized = false;
const byId = id => document.getElementById(id);

export function enterWorkspace() {
  const composer = byId("composer");
  const main = byId("main");
  if (composer && main && composer.parentElement !== main) main.append(composer);
  document.body.dataset.screen = "workspace";
  if (byId("composerInput")) byId("composerInput").placeholder = "说说你的心愿，或者继续追问这座寺庙";
}

export function showHome() {
  const composer = byId("composer");
  const slot = byId("landingComposer");
  if (!composer || !slot) return;
  document.body.dataset.screen = "home";
  if (byId("composerInput")) byId("composerInput").placeholder = "周六想为家人求平安，带老人，不想爬山……";
  slot.append(composer);
  const resume = byId("resumeConversation");
  if (resume) resume.hidden = !byId("log")?.querySelector(".msg-user, .msg-assistant");
}

export function initExperience({ onResume = () => {} } = {}) {
  if (initialized) return;
  initialized = true;
  byId("btnHome")?.addEventListener("click", () => { showHome(); byId("composerInput")?.focus({ preventScroll: true }); });
  byId("resumeConversation")?.addEventListener("click", () => { enterWorkspace(); onResume(); byId("composerInput")?.focus({ preventScroll: true }); });
  byId("pauseGallery")?.addEventListener("click", event => {
    const button = event.currentTarget;
    const paused = document.body.classList.toggle("gallery-paused");
    button.setAttribute("aria-pressed", String(paused));
    button.textContent = paused ? "播放画面" : "暂停画面";
  });
  for (const id of ["btnMemory", "privacyOpenMemory"]) byId(id)?.addEventListener("click", enterWorkspace, true);
  showHome();
}
