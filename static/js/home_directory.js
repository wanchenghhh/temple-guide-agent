import { h } from "./core.js?v=__APP_VERSION__";

const groups = ["东城区", "西城区", "海淀区", "石景山区", "门头沟区"];
const types = { religious_site: "寺观", heritage: "文博点", scenic: "景区/民俗", relic: "遗址", closed: "不开放", market: "文化市场" };
const flags = { reservation: "预约信息待确认", unverified: "开放待核实", closed: "资料标记关闭" };
let initialized = false;

export function initHomeDirectory({ onPrompt }) {
  if (initialized) return;
  initialized = true;
  document.querySelectorAll("#landing [data-prompt]").forEach(button => {
    button.addEventListener("click", () => onPrompt(button.dataset.prompt));
  });
  const list = document.getElementById("templeIndex");
  const filters = document.getElementById("indexFilters");
  const count = document.getElementById("indexCount");
  const status = document.getElementById("indexStatus");
  if (!list || !filters || !count || !status) return;

  async function load() {
    status.textContent = "正在整理名录…";
    try {
      const response = await fetch(new URL("../data/temple-index.json", import.meta.url));
      if (!response.ok) throw new Error('directory unavailable');
      const payload = await response.json();
      if (!Array.isArray(payload.items) || !payload.items.every(item => typeof item.name === 'string' && typeof item.district === 'string')) throw new Error('invalid directory');
      const all = payload.items;
      let current = "全部";
      const groupOf = item => groups.includes(item.district) ? item.district : "其他";
      const row = (item, index) => {
        const religious = item.status === "religious_site";
        const kind = !religious ? "other" : /藏传/.test(item.sect) ? "zang" : /道教/.test(item.sect) ? "dao" : "han";
        const type = religious ? item.sect || "寺观" : types[item.status] || "场所资料";
        return h("li", {}, [h("button", {
          type: "button", class: "idx-row", "aria-label": `了解${item.name}`,
          onClick: () => onPrompt(`想先了解${item.name}，再决定去不去`),
        }, [
          h("span", { class: "idx-no", text: String(index + 1).padStart(2, "0"), "aria-hidden": "true" }),
          h("span", { class: "idx-name", text: item.name }),
          h("span", { class: "idx-desc", text: item.atmosphere }),
          flags[item.open_status] ? h("span", { class: `idx-flag is-${item.open_status}`, text: flags[item.open_status] }) : null,
          h("span", { class: `idx-meta kind-${kind}`, text: `${item.district.replace(/区$/, "")} · ${type}` }),
          h("span", { class: "idx-arrow", text: "→", "aria-hidden": "true" }),
        ])]);
      };
      const render = () => {
        const shown = all.filter(item => current === "全部" || groupOf(item) === current);
        list.replaceChildren(...shown.map(item => row(item, all.indexOf(item))));
        count.textContent = String(shown.length);
        status.textContent = shown.length ? "" : "当前区域暂无已收录资料。";
        filters.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.group === current)));
      };
      filters.replaceChildren(...["全部", ...groups, "其他"].map(group => h("button", {
        type: "button", dataset: { group }, "aria-pressed": "false",
        onClick: () => { current = group; render(); },
      }, [h("span", { text: group.replace(/区$/, "") }), h("small", { text: String(group === "全部" ? all.length : all.filter(item => groupOf(item) === group).length) })])));
      render();
    } catch {
      count.textContent = "—";
      status.replaceChildren(h("span", { text: "名录暂时未能加载，可以直接在输入框中提问。" }), h("button", { type: "button", text: "重新加载", onClick: load }));
    }
  }
  load();
}
