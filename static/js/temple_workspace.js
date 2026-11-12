import { h, icon } from "./core.js?v=__APP_VERSION__";
import { templeCard } from "./cards.js?v=__APP_VERSION__";

let candidates = null;
let context = null;
let selected = null;
let detail = null;
let detailOpen = false;
let view = "chat";
let emptyNote = "";

const panel = () => document.getElementById("templeWorkspace");
const items = () => candidates?.data?.card?.items || [];

export function showConversation() {
  view = "chat";
  document.body.dataset.workspaceView = view;
  updateTabs();
}

function showResults(focus = false) {
  view = "results";
  document.body.dataset.workspaceView = view;
  updateTabs();
  if (focus) panel()?.querySelector("h2")?.focus({ preventScroll: true });
}

function updateTabs() {
  const count = items().length;
  const chat = document.getElementById("workspaceChatTab");
  const results = document.getElementById("workspaceResultsTab");
  if (chat) chat.setAttribute("aria-selected", String(view === "chat"));
  if (results) {
    results.textContent = count ? `候选 ${count}` : "候选";
    results.disabled = !count;
    results.setAttribute("aria-selected", String(view === "results"));
  }
}

function focusTemple(item) {
  selected = item;
  detail = { ...candidates, data: { ...candidates.data, card: { ...candidates.data.card, kind: "temple_detail", items: [item], reviews: candidates.data.card.reviews?.temple === item.name ? candidates.data.card.reviews : null, travel: candidates.data.card.travel?.temple === item.name ? candidates.data.card.travel : null, has_unverified_sources: item.sources_status !== "verified" } } };
  detailOpen = true;
  render();
  showResults(true);
}

function reason(item, card) {
  const relevant = item.wishes?.find((wish) => wish.theme === card.wish);
  if (relevant) return `${relevant.evidence || "民间说法"} · ${relevant.claim}`;
  const match = item.condition_checks?.find((check) => check.status === "match");
  return match?.text || item.atmosphere || item.accessibility || "查看资料，进一步了解参访条件。";
}

function tradeoff(item) {
  const conflict = item.condition_checks?.find((check) => check.status === "conflict");
  if (conflict) return conflict.text;
  const uncertain = item.condition_checks?.find((check) => check.condition === "visit_date" && check.status === "unknown");
  if (uncertain) return "计划日期的开放安排待确认";
  if (item.closure?.length) return item.closure[0];
  if (/山间|山地|山路|爬山|坡道较多/.test(item.accessibility || "")) return item.accessibility;
  if (item.booking_guidance?.reservation === "required") return "需要提前预约，先确认官方安排";
  return item.open_note || "临行前确认开放与预约安排";
}

function summary(item, index, card) {
  const button = h("button", { type: "button", class: `candidate-open${selected?.name === item.name ? " is-selected" : ""}`, onClick: () => focusTemple(item), "aria-label": `查看${item.name}详情` }, [
    h("span", { class: `candidate-number tone-${index % 3}`, text: String(index + 1).padStart(2, "0"), "aria-hidden": "true" }),
    h("span", { class: "candidate-copy" }, [
      h("span", { class: "candidate-heading" }, [h("strong", { text: item.name }), h("span", { class: "candidate-district", text: item.district })]),
      h("span", { class: "candidate-reason", text: reason(item, card) }),
      h("span", { class: "candidate-tradeoff", text: tradeoff(item) }),
      h("span", { class: "candidate-meta", text: [item.place_type, item.distance_km != null ? `直线约 ${item.distance_km} 公里` : "", item.sources?.length ? `${item.sources.length} 个来源${item.sources_status !== "verified" ? " · 待核实" : ""}` : "来源待核"].filter(Boolean).join(" · ") }),
    ]),
    h("span", { class: "candidate-chevron", "aria-hidden": "true" }, [icon("down")]),
  ]);
  return h("article", { class: "candidate-row" }, [button]);
}

function empty() {
  const art = h("div", { class: "workspace-art", "aria-hidden": "true" });
  art.innerHTML = '<svg viewBox="0 0 420 270" fill="none"><circle cx="270" cy="78" r="36" fill="#D6AB76" fill-opacity=".42"/><path d="M82 233V106a128 128 0 0 1 256 0v127M102 233V111a108 108 0 0 1 216 0v122" stroke="currentColor" stroke-opacity=".16"/><path d="M113 165c39-6 64-19 97-43 33 24 58 37 97 43M129 171h162M142 180v53m136-53v53M161 190v43m98-43v43M153 151h114M174 145c14-4 25-11 36-20 11 9 22 16 36 20M116 234h188M66 241h288" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M44 226c29-19 51-21 69-11m194 0c30-17 51-13 73 1" stroke="currentColor" stroke-opacity=".25" stroke-linecap="round"/></svg>';
  return h("div", { class: "workspace-empty" }, [
    h("span", { class: "workspace-eyebrow", text: "BEIJING · TEMPLE NOTES" }), art,
    h("h2", { tabindex: "-1", text: "你的寻访手记" }),
    h("p", { text: emptyNote || "开始对话后，在这里比较寺庙、查看来源和参访信息。" }),
    h("span", { class: "workspace-empty-foot", text: "当前资料覆盖北京" }),
  ]);
}

function render() {
  const root = panel();
  if (!root) return;
  updateTabs();
  const chip = document.getElementById("templeFocus");
  if (chip) {
    chip.hidden = !selected;
    chip.textContent = selected ? `正在聊 · ${selected.name}` : "";
  }
  if (!candidates) {
    root.replaceChildren(empty());
    return;
  }
  const card = candidates.data.card;
  const heading = h("header", { class: "workspace-head" }, [
    h("div", {}, [h("span", { class: "workspace-eyebrow", text: detailOpen ? "参访资料" : "本次寻访" }), h("h2", { tabindex: "-1", text: detailOpen ? selected.name : "这次的选择" })]),
    detailOpen ? h("button", { type: "button", class: "workspace-back", onClick: () => { detailOpen = false; render(); }, text: "返回候选", "aria-label": "返回候选列表" }) : h("span", { class: "workspace-count", text: `${items().length} 处` }),
  ]);
  const body = h("div", { class: `workspace-body${detailOpen ? " is-detail" : ""}` });
  if (detailOpen) {
    body.append(h("div", { class: "workspace-detail-actions" }, [
      h("button", { type: "button", text: "开放与预约", onClick: () => context.refineTemple(`${selected.name}开放时间和预约购票要求是什么？`) }),
      h("button", { type: "button", text: "怎么去", onClick: () => context.refineTemple(`${selected.name}怎么去？`) }),
      h("button", { type: "button", text: "公开分享", onClick: () => context.refineTemple(`${selected.name}有没有去过的人分享？`) }),
    ]));
    body.append(templeCard(detail, context));
  } else {
    const conditions = card.conditions || {};
    const conditionsText = [card.wish, conditions.visit_date, conditions.elderly ? "长辈同行" : "", conditions.no_climbing ? "少爬山" : "", conditions.quiet ? "偏好安静" : "", card.origin_name ? `从${card.origin_name}出发` : ""].filter(Boolean).join(" · ");
    if (conditionsText) body.append(h("p", { class: "workspace-conditions", text: conditionsText }));
    body.append(h("div", { class: "candidate-list" }, items().map((item, index) => summary(item, index, card))));
    body.append(h("p", { class: "workspace-note", text: "点击一处展开资料。民间说法与公开分享供参考，开放安排请临行确认。" }));
  }
  root.replaceChildren(heading, body);
}

export function renderWorkspaceEntry(entry, ctx, { restored = false } = {}) {
  const card = entry.data.card;
  if (!panel() || !card?.items?.length) return null;
  context = ctx;
  if (card.kind === "temple_detail") {
    const incoming = card.items[0];
    const known = items().find(item => item.name === incoming.name);
    // Operational follow-ups refresh facts, not the visible scope of folk customs.
    const item = known ? { ...known, ...incoming, wishes: known.wishes || [] } : incoming;
    selected = item;
    detail = { ...entry, data: { ...entry.data, card: { ...card, items: [item] } } };
    if (!candidates) {
      candidates = entry;
      detailOpen = true;
    } else if (items().some((known) => known.name === item.name)) {
      const old = candidates.data.card;
      candidates = { ...candidates, data: { ...candidates.data, card: { ...old, items: old.items.map((known) => known.name === item.name ? { ...known, ...item } : known) } } };
    } else {
      detailOpen = true;
    }
    render();
    return null;
  }
  candidates = entry;
  selected = null;
  detail = null;
  detailOpen = false;
  render();
  return h("div", { class: "result-receipt" }, [icon("check"), h("span", { text: "候选已更新" }), h("button", { type: "button", text: "查看当前选择", onClick: () => showResults(true) })]);
}

export function isNewTempleSearch(text) {
  return /推荐|换|重新|别的|其他|附近|就近|区(?:都行|不限|[，。！？、\s]|$)|带老人|带长辈|不爬山|少走路|想.*安静/.test(text);
}

export function messageWithTempleContext(text) {
  if (isNewTempleSearch(text)) return text;
  const ordinal = text.match(/第([一二三123])(?:个|座|家)/);
  if (ordinal) {
    const index = "一二三".includes(ordinal[1]) ? "一二三".indexOf(ordinal[1]) : Number(ordinal[1]) - 1;
    const item = items()[index];
    if (item) return `关于${item.name}，${text}`;
  }
  if (selected && !text.includes(selected.name) && /它|那里|那边|这座|那座|几点|需要预约|门票多少/.test(text)) return `关于${selected.name}，${text}`;
  return text;
}

export function resetTempleWorkspace(note = "") {
  emptyNote = note;
  candidates = null;
  context = null;
  selected = null;
  detail = null;
  detailOpen = false;
  showConversation();
  render();
}

export function initTempleWorkspace() {
  document.getElementById("workspaceChatTab")?.addEventListener("click", showConversation);
  document.getElementById("workspaceResultsTab")?.addEventListener("click", () => showResults(true));
  document.getElementById("composer")?.addEventListener("submit", showConversation, true);
  panel()?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && detailOpen) { detailOpen = false; render(); }
  });
  const composer = document.getElementById("composer");
  if (composer && typeof ResizeObserver !== "undefined") new ResizeObserver(() => {
    document.documentElement.style.setProperty("--composer-height", `${composer.getBoundingClientRect().height}px`);
  }).observe(composer);
  const menu = document.getElementById("accountMenu");
  menu?.addEventListener("click", (event) => { if (event.target.closest("button")) menu.open = false; });
  document.addEventListener("click", (event) => { if (menu && !menu.contains(event.target)) menu.open = false; });
  resetTempleWorkspace();
}
