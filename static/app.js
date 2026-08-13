// CardBuySearch 前端邏輯
const $ = (sel) => document.querySelector(sel);
const wishlist = new Map(); // key "game:id" -> {card, qty, rarity, lang}
let ygoOptions = { rarities: [], langs: [] };
let gcgOptions = { langs: [] };

const GAME_LABEL = { pkm: "寶可夢", ygo: "遊戲王", gcg: "鋼彈", ga: "GA" };
// GA（Grand Archive）普卡/閃卡（用願望清單的 lang 欄位承載）
const GA_FOILS = ["普卡", "閃卡"];

function currentGame() {
  return document.querySelector('input[name="game"]:checked').value;
}

// ---------- 初始化 ----------
async function loadRarities() {
  const res = await fetch("/api/rarities");
  const data = await res.json();
  const sel = $("#raritySelect");
  for (const r of data.rarities) {
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = r;
    sel.appendChild(opt);
  }
}
async function loadYgoOptions() {
  const res = await fetch("/api/ygo/options");
  ygoOptions = await res.json();
}
async function loadGcgOptions() {
  const res = await fetch("/api/gcg/options");
  gcgOptions = await res.json();
}
loadRarities();
loadYgoOptions();
loadGcgOptions();
restoreWishlist();
startBrowse();  // 開頁預設進入「全部卡片」一覽（含篩選列）

// ---------- 深色模式開關 ----------
function applyTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "";
  $("#themeToggle").textContent = dark ? "☀️" : "🌙";
  localStorage.setItem("cbs_theme", dark ? "dark" : "light");
}
$("#themeToggle").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme !== "dark"));
// 開頁腳本已先套過 data-theme，這裡同步按鈕圖示
$("#themeToggle").textContent =
  document.documentElement.dataset.theme === "dark" ? "☀️" : "🌙";

document.querySelectorAll('input[name="game"]').forEach((el) =>
  el.addEventListener("change", () => {
    const game = currentGame();
    $("#raritySelect").style.display = game === "pkm" ? "" : "none";
    $("#searchInput").placeholder = {
      ygo: "卡名（例：灰流麗、増殖するG，中日文皆可）",
      gcg: "卡名或卡號（例：高達、GD01-001）",
      pkm: "卡名或編號（例：噴火龍、094/081）",
      ga: "英文卡名或卡號（例：Volnia、RDO-204）",
    }[game];
    $("#searchInput").value = "";
    startBrowse();  // 切換遊戲直接進入該遊戲的全卡一覽
  }));

// ---------- 搜尋 ----------
async function doSearch() {
  const q = $("#searchInput").value.trim();
  const game = currentGame();
  const rarity = game === "pkm" ? $("#raritySelect").value : "";
  if (!q && !rarity) { startBrowse(); return; }  // 清空搜尋＝回到全卡一覽
  stopBrowse();
  const grid = $("#searchResults");
  grid.innerHTML = '<p class="empty"><span class="spinner"></span>搜尋中…</p>';
  const res = await fetch(`/api/search?game=${game}&q=${encodeURIComponent(q)}&rarity=${encodeURIComponent(rarity)}`);
  const data = await res.json();
  grid.innerHTML = "";
  if (!data.cards.length) {
    grid.innerHTML = '<p class="empty">找不到卡片。資料庫可能尚未收錄——可先跑爬蟲補資料。</p>';
    return;
  }
  for (const c of data.cards) grid.appendChild(cardEl(c));
}
$("#searchBtn").addEventListener("click", doSearch);
$("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

// ---------- 全部卡片一覽（篩選＋分頁） ----------
let browseState = null; // {game, opts, offset} 非 null 表示一覽模式

$("#browseBtn").addEventListener("click", () => startBrowse());

function filterSelect(key, label, values, keep) {
  // values 可為字串陣列或 {value,label} 物件陣列
  return `
    <select data-fkey="${key}">
      <option value="">${label}</option>
      ${(values || []).map((v) => {
        const val = typeof v === "object" ? v.value : v;
        const txt = typeof v === "object" ? v.label : v;
        return `<option value="${val}" ${keep === val ? "selected" : ""}>${txt}</option>`;
      }).join("")}
    </select>`;
}

function renderFilterBar() {
  const { game, opts } = browseState;
  const bar = $("#filterBar");
  const cur = {};
  bar.querySelectorAll("select").forEach((s) => { cur[s.dataset.fkey] = s.value; });
  if (game === "ygo") {
    const cat = cur.cat || "";
    // 選了魔法/陷阱 → 細分類換成該類別的；星數/屬性/種族只在怪獸（或未選）時出現
    // （subTable 後備：後端若是舊版（無 subtypes_by_cat）退回扁平清單）
    const subTable = opts.subtypes_by_cat || { "": opts.subtypes || [] };
    let html = filterSelect("cat", "全部類別", opts.categories, cat) +
      filterSelect("sub", cat ? `${cat}種類` : "細分類",
                   subTable[cat] || subTable[""], cur.sub);
    if (!cat || cat === "怪獸") {
      html += filterSelect("lv", "星數/連結", opts.levels, cur.lv) +
              filterSelect("attr", "屬性", opts.attrs, cur.attr) +
              filterSelect("race", "種族", opts.races, cur.race);
    }
    bar.innerHTML = html + '<button class="clear-filters">清除條件</button>';
  } else if (game === "gcg") {
    bar.innerHTML =
      filterSelect("color", "顏色", opts.colors, cur.color) +
      filterSelect("type", "卡牌類型", opts.types, cur.type) +
      filterSelect("lv", "等級", opts.levels, cur.lv) +
      filterSelect("source", "作品", opts.sources, cur.source) +
      filterSelect("pack", "產品", opts.products, cur.pack) +
      filterSelect("rarity", "稀有度", opts.rarities, cur.rarity) +
      '<button class="clear-filters">清除條件</button>';
  } else if (game === "ga") {
    bar.innerHTML =
      filterSelect("element", "元素", opts.elements, cur.element) +
      filterSelect("class", "職業", opts.classes, cur.class) +
      filterSelect("type", "卡種", opts.types, cur.type) +
      filterSelect("set", "系列", opts.sets, cur.set) +
      filterSelect("rarity", "稀有度", opts.rarities, cur.rarity) +
      '<button class="clear-filters">清除條件</button>';
  } else {
    bar.innerHTML =
      filterSelect("kind", "卡片大類", opts.kinds, cur.kind) +
      ((cur.kind || "寶可夢") === "寶可夢"
        ? filterSelect("ptype", "屬性", opts.ptypes, cur.ptype) +
          filterSelect("stage", "階段/機制", opts.stages, cur.stage)
        : "") +
      filterSelect("product", "產品", opts.products, cur.product) +
      filterSelect("set", "系列", opts.sets, cur.set) +
      filterSelect("rarity", "稀有度", opts.rarities, cur.rarity) +
      '<button class="clear-filters">清除條件</button>';
  }
  bar.hidden = false;
  bar.querySelectorAll("select").forEach((s) =>
    s.addEventListener("change", () => {
      if (s.dataset.fkey === "cat" || s.dataset.fkey === "kind") {
        // 換類別時重畫連動選單（細分類清空避免殘留不合法值）
        const keep = s.value;
        bar.querySelectorAll("select").forEach((x) => {
          if (x !== s && (x.dataset.fkey === "sub")) x.value = "";
        });
        renderFilterBar();
        bar.querySelector(`[data-fkey="${s.dataset.fkey}"]`).value = keep;
      }
      loadBrowse(0);
    }));
  bar.querySelector(".clear-filters").addEventListener("click", () => {
    bar.querySelectorAll("select").forEach((s) => { s.value = ""; });
    renderFilterBar();
    loadBrowse(0);
  });
}

async function startBrowse() {
  const game = currentGame();
  const res = await fetch(`/api/browse-options?game=${game}`);
  const opts = await res.json();
  browseState = { game, opts, offset: 0 };
  $("#filterBar").innerHTML = "";
  renderFilterBar();
  loadBrowse(0);
}

function stopBrowse() {
  browseState = null;
  $("#filterBar").hidden = true;
  $("#browseCount").hidden = true;
}

async function loadBrowse(offset) {
  const game = browseState.game;
  const params = new URLSearchParams({ game, offset });
  $("#filterBar").querySelectorAll("select").forEach((s) => {
    if (s.value) params.set(s.dataset.fkey, s.value);
  });
  const grid = $("#searchResults");
  if (offset === 0) grid.innerHTML = '<p class="empty"><span class="spinner"></span>載入中…</p>';
  const res = await fetch(`/api/browse?${params}`);
  const data = await res.json();
  if (offset === 0) grid.innerHTML = "";
  else { const btn = grid.querySelector(".load-more"); if (btn) btn.remove(); }
  for (const c of data.cards) grid.appendChild(cardEl(c));
  const shown = offset + data.cards.length;
  $("#browseCount").hidden = false;
  $("#browseCount").textContent = `符合條件 ${data.total} 張，已顯示 ${shown} 張`;
  if (shown < data.total) {
    const more = document.createElement("button");
    more.className = "load-more";
    more.textContent = `載入更多（還有 ${data.total - shown} 張）`;
    more.addEventListener("click", () => loadBrowse(shown));
    grid.appendChild(more);
  }
  browseState.offset = shown;
}

// ---------- 以圖搜卡 ----------
$("#imgSearchBtn").addEventListener("click", () => $("#imgInput").click());
$("#imgInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  stopBrowse();
  const grid = $("#searchResults");
  grid.innerHTML = '<p class="empty"><span class="spinner"></span>比對圖片中…</p>';
  const fd = new FormData();
  fd.append("image", file);
  fd.append("game", currentGame());
  try {
    const res = await fetch("/api/search-by-image", { method: "POST", body: fd });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    grid.innerHTML = "";
    if (!data.cards.length) {
      grid.innerHTML = '<p class="empty">找不到相近的卡。</p>';
      return;
    }
    for (const c of data.cards) grid.appendChild(cardEl(c));
  } catch (err) {
    grid.innerHTML = `<p class="empty">圖片搜尋失敗：${err.message}</p>`;
  } finally {
    e.target.value = "";
  }
});

function keyOf(c) { return `${c.game}:${c.id}`; }

// 遊戲王預設日紙、鋼彈預設日版（台灣主流），寶可夢無版本
function defaultLang(game) {
  return game === "ygo" ? "日紙" : game === "gcg" ? "日版" : "";
}
function newWishItem(card, qty) {
  return { card, qty: qty || 1, rarity: "", art: "",
           lang: defaultLang(card.game), cardRarities: null };
}

function cardEl(c) {
  const div = document.createElement("div");
  div.className = "card-item";
  div.dataset.key = keyOf(c);
  const inList = wishlist.has(keyOf(c));
  const sub = c.game === "ygo" ? `${c.name_jp || ""}`
    : c.game === "gcg" ? `${c.collector_number || ""} ${c.color || ""}`
    : c.game === "ga" ? `${c.collector_number || ""} ${c.element || ""}`
    : `${c.set_alpha || ""} ${c.collector_number || ""}`;
  div.innerHTML = `
    <div class="card-click" title="查看卡片詳情">
      <img src="${c.image_url || ""}" alt="${esc(c.name || "")}">
      <div class="meta">
        <span class="name">${esc(c.name) || "（未知）"}</span>
        <span class="sub">${esc(sub)}</span>
        ${c.rarity ? `<span class="rarity-tag">${esc(c.rarity)}</span>` : ""}
        ${c.last_price != null
          ? `<span class="price-tag" title="比價時記錄的最低價（${c.last_price_ts}），非即時">${fmt(c.last_price)} 起</span>`
          : ""}
      </div>
    </div>
    <div class="card-btns">
      <button class="add" ${inList ? "disabled" : ""}>${inList ? "已加入" : "＋ 加入清單"}</button>
      <button class="coll" title="我已經有這張卡，加入收藏">📦</button>
    </div>`;
  div.querySelector(".card-click").addEventListener("click", () =>
    openCardModal(c.game, c.id));
  div.querySelector("button.add").addEventListener("click", (e) => {
    wishlist.set(keyOf(c), newWishItem(c));
    e.target.disabled = true;
    e.target.textContent = "已加入";
    renderWishlist();
    if (c.game === "ygo") loadCardRarities(keyOf(c), c.id);
  });
  div.querySelector("button.coll").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await addToCollection(c);
      btn.textContent = "✓";
      setTimeout(() => { btn.textContent = "📦"; btn.disabled = false; }, 1200);
    } catch (err) {
      alert("加入收藏失敗：" + err.message);
      btn.disabled = false;
    }
  });
  return div;
}

// 查這張卡實際出過的稀有度（Konami 官方收錄資料），縮小稀有度選單
async function loadCardRarities(key, cardId) {
  try {
    const res = await fetch(`/api/ygo/printings/${cardId}`);
    const data = await res.json();
    const item = wishlist.get(key);
    if (!item) return;
    if (data.ok && data.rarities.length) {
      item.cardRarities = data.rarities;
      if (item.rarity && !data.rarities.includes(item.rarity)) item.rarity = "";
      renderWishlist();
    }
  } catch (e) { /* 查不到就維持完整選單 */ }
}

// ---------- 卡片詳情彈窗 ----------
const modal = $("#cardModal");

function closeModal() { modal.hidden = true; }
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
modal.querySelector(".modal-close").addEventListener("click", closeModal);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) closeModal();
});

async function openCardModal(game, cardId) {
  modal.hidden = false;
  $("#modalImg").src = "";
  $("#modalInfo").innerHTML = '<p class="empty"><span class="spinner"></span>載入中…</p>';
  let d;
  try {
    const res = await fetch(`/api/card/${game}/${cardId}`);
    if (!res.ok) throw new Error("讀取失敗");
    d = await res.json();
  } catch (err) {
    $("#modalInfo").innerHTML = `<p class="empty">${err.message}</p>`;
    return;
  }
  $("#modalImg").src = d.image_url;
  $("#modalInfo").innerHTML = d.game === "ygo" ? ygoDetailHtml(d)
    : d.game === "gcg" ? gcgDetailHtml(d)
    : d.game === "ga" ? gaDetailHtml(d) : pkmDetailHtml(d);
  bindModalActions(d);
  pushHistory(d);
}

// ---------- 歷史瀏覽 ----------
// 純前端（localStorage），看過的卡留個入口方便回訪。上限 24 筆、最新在前。
const HISTORY_MAX = 24;

function pushHistory(d) {
  let hist = [];
  try { hist = JSON.parse(localStorage.getItem("cbs_history") || "[]"); } catch (e) { }
  const key = `${d.game}:${d.id}`;
  hist = hist.filter((h) => `${h.g}:${h.id}` !== key);   // 看過的往前挪，不重複
  hist.unshift({ g: d.game, id: d.id, n: d.name, img: d.image_url });
  localStorage.setItem("cbs_history", JSON.stringify(hist.slice(0, HISTORY_MAX)));
  renderHistory();
}

function renderHistory() {
  const box = $("#historyStrip");
  const sec = $("#historySection");
  if (!box || !sec) return;
  let hist = [];
  try { hist = JSON.parse(localStorage.getItem("cbs_history") || "[]"); } catch (e) { }
  sec.hidden = !hist.length;
  box.innerHTML = hist.map((h) =>
    `<button class="hist-item" data-g="${esc(h.g)}" data-id="${esc(String(h.id))}"
       title="${esc(h.n || "")}"><img src="${esc(h.img || "")}" alt=""><span>${esc(h.n || "")}</span></button>`
  ).join("");
  box.querySelectorAll(".hist-item").forEach((b) =>
    b.addEventListener("click", () => openCardModal(b.dataset.g, b.dataset.id)));
}

$("#historyClear").addEventListener("click", () => {
  localStorage.removeItem("cbs_history");
  renderHistory();
});

renderHistory();

function gcgDetailHtml(d) {
  const chips = [];
  const push = (v) => v && chips.push(`<span class="badge-chip">${esc(String(v))}</span>`);
  push(d.color); push(d.card_type);
  if (d.level != null) chips.push(`<span class="badge-chip stat">Lv ${d.level}</span>`);
  if (d.cost != null) chips.push(`<span class="badge-chip">COST ${d.cost}</span>`);
  if (d.ap != null || d.hp != null)
    chips.push(`<span class="badge-chip stat">AP ${d.ap ?? "-"}／HP ${d.hp ?? "-"}</span>`);
  const rows = [["卡號", d.id], ["稀有度", d.rarity], ["地形", d.terrain],
    ["特徵", d.traits], ["來源作品", d.source]]
    .filter(([, v]) => v)
    .map(([k, v]) => `<tr><th>${k}</th><td>${esc(String(v))}</td></tr>`).join("");
  const variants = (d.variants || []).map((v) => `
    <li class="${v.id === d.id ? "current" : ""}">
      <a href="#" data-vid="${esc(v.id)}" data-vgame="gcg">
        <span>${v.is_alt ? "異圖" : "原圖"}</span>
        ${v.rarity ? `<span class="rarity-tag">${esc(v.rarity)}</span>` : ""}
        ${v.id === d.id ? "<span>← 目前</span>" : ""}
      </a>
    </li>`).join("");
  return `
    <h2>${esc(d.name)}</h2>
    <p class="modal-sub">${esc(d.id)}　·　鋼彈卡片遊戲</p>
    <div class="badge-row">${chips.join("")}</div>
    ${d.effect ? `<div class="modal-section"><h4>效果</h4>
      <div class="card-effect">${esc(d.effect)}</div></div>` : ""}
    <div class="modal-section"><table class="printings-table">${rows}</table></div>
    ${(d.variants || []).length > 1 ? `<div class="modal-section">
      <h4>異圖版本（${d.variants.length}）——挑你要收的版本</h4>
      <ul class="variant-list" style="max-height:200px;overflow-y:auto">${variants}</ul></div>` : ""}
    <div class="modal-actions">
      <button class="add">＋ 加入願望清單</button>
      <button class="coll" title="我已經有這張卡，加入收藏">📦 收藏</button>
      <a class="official" href="${esc(d.official_url)}" target="_blank" rel="noopener">官方卡表</a>
    </div>`;
}

function gaDetailHtml(d) {
  const chips = [];
  const push = (v) => v && chips.push(`<span class="badge-chip">${esc(String(v))}</span>`);
  push(d.element);
  (d.classes || "").split(",").filter(Boolean).forEach(push);
  (d.types || "").split(",").filter(Boolean).forEach(push);
  if (d.level != null) chips.push(`<span class="badge-chip stat">Lv ${d.level}</span>`);
  if (d.cost_memory != null || d.cost_reserve != null)
    chips.push(`<span class="badge-chip">費 ${d.cost_memory ?? "-"}${d.cost_reserve != null ? "/" + d.cost_reserve : ""}</span>`);
  if (d.power != null || d.life != null)
    chips.push(`<span class="badge-chip stat">攻 ${d.power ?? "-"}／命 ${d.life ?? "-"}</span>`);
  if (d.durability != null) chips.push(`<span class="badge-chip stat">耐 ${d.durability}</span>`);
  const rows = [["卡號", `${d.set_prefix}-${d.collector_number}`], ["系列", d.set_name],
    ["稀有度", d.rarity], ["特徵", d.subtypes]]
    .filter(([, v]) => v)
    .map(([k, v]) => `<tr><th>${k}</th><td>${esc(String(v))}</td></tr>`).join("");
  const variants = (d.variants || []).map((v) => `
    <li class="${v.id === d.id ? "current" : ""}">
      <a href="#" data-vid="${esc(v.id)}" data-vgame="ga">
        <span>${esc(v.set_prefix)}-${esc(v.collector_number)}</span>
        ${v.rarity ? `<span class="rarity-tag">${esc(v.rarity)}</span>` : ""}
        ${v.id === d.id ? "<span>← 目前</span>" : ""}
      </a>
    </li>`).join("");
  return `
    <h2>${esc(d.name)}</h2>
    <p class="modal-sub">${esc(d.set_prefix)}-${esc(d.collector_number)}　·　Grand Archive TCG</p>
    <div class="badge-row">${chips.join("")}</div>
    ${d.effect ? `<div class="modal-section"><h4>效果</h4>
      <div class="card-effect">${esc(d.effect)}</div></div>` : ""}
    <div class="modal-section"><table class="printings-table">${rows}</table></div>
    ${(d.variants || []).length > 1 ? `<div class="modal-section">
      <h4>其他版本（${d.variants.length}）——挑你要收的版本</h4>
      <ul class="variant-list" style="max-height:200px;overflow-y:auto">${variants}</ul></div>` : ""}
    <div class="modal-actions">
      <button class="add">＋ 加入願望清單</button>
      <button class="coll" title="我已經有這張卡，加入收藏">📦 收藏</button>
      <a class="official" href="${esc(d.official_url)}" target="_blank" rel="noopener">官方卡表</a>
    </div>`;
}

function esc(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function ygoDetailHtml(d) {
  // types 格式：「[怪獸|效果|調整] 不死/炎\n[★3] 0/1800」→ 拆成徽章
  const chips = [];
  const types = d.types || "";
  const cat = types.match(/\[([^\]]+)\]/);
  if (cat) for (const t of cat[1].split("|")) chips.push(`<span class="badge-chip">${esc(t)}</span>`);
  const raceAttr = types.match(/\]\s*([^\n\[]+)/);
  if (raceAttr && raceAttr[1].trim()) chips.push(`<span class="badge-chip">${esc(raceAttr[1].trim())}</span>`);
  const lv = types.match(/\[(★|☆|R|L)([0-9]+)\]/);
  if (lv) chips.push(`<span class="badge-chip stat">${lv[1] === "L" ? "LINK-" : lv[1]}${lv[2]}</span>`);
  const stats = types.match(/(-?\d+|\?)\/(-?\d+|\?)\s*$/m);
  if (stats) chips.push(`<span class="badge-chip stat">ATK ${stats[1]}／DEF ${stats[2]}</span>`);

  const otherNames = [d.name_jp, d.name_en, d.name_cnocg && d.name_cnocg !== d.name ? `台譯：${d.name_cnocg}` : null]
    .filter(Boolean).map(esc).join("　·　");

  const printRows = (d.printings || []).map((p) => `
    <tr><td>${esc(p.release || "")}</td><td>${esc(p.code || "")}</td>
        <td>${p.rarity ? `<span class="rarity-tag">${esc(p.rarity)}</span>` : ""}</td>
        <td>${esc(p.pack || "")}</td></tr>`).join("");

  return `
    <h2>${esc(d.name)}</h2>
    <p class="modal-sub">${otherNames}</p>
    <div class="badge-row">${chips.join("")}</div>
    ${d.pend_text ? `<div class="modal-section"><h4>靈擺效果</h4>
      <div class="card-effect">${esc(d.pend_text)}</div></div>` : ""}
    <div class="modal-section"><h4>效果</h4>
      <div class="card-effect">${esc(d.card_text) || "（無資料）"}</div></div>
    ${printRows ? `<div class="modal-section"><h4>收錄卡包（${d.printings.length}）</h4>
      <div style="max-height:180px;overflow-y:auto">
      <table class="printings-table">
        <tr><th>發售日</th><th>卡號</th><th>稀有度</th><th>卡包</th></tr>${printRows}
      </table></div></div>` : ""}
    <div class="modal-actions">
      <button class="add">＋ 加入願望清單</button>
      <button class="coll" title="我已經有這張卡，加入收藏">📦 收藏</button>
    </div>`;
}

function pkmDetailHtml(d) {
  const chips = [];
  if (d.evolve_marker) chips.push(`<span class="badge-chip">${esc(d.evolve_marker)}</span>`);
  if (d.set_alpha) chips.push(`<span class="badge-chip">系列 ${esc(d.set_alpha)}</span>`);
  if (d.collector_number) chips.push(`<span class="badge-chip stat">${esc(d.collector_number)}</span>`);
  if (d.rarity) chips.push(`<span class="badge-chip stat">${esc(d.rarity)}</span>`);

  const variants = (d.variants || []).map((v) => `
    <li class="${v.id === d.id ? "current" : ""}">
      <a href="#" data-vid="${v.id}">
        <span>${esc(v.set_alpha || "")} ${esc(v.collector_number || "")}</span>
        ${v.rarity ? `<span class="rarity-tag">${esc(v.rarity)}</span>` : ""}
        ${v.id === d.id ? "<span>← 目前</span>" : ""}
      </a>
    </li>`).join("");

  return `
    <h2>${esc(d.name)}</h2>
    <p class="modal-sub">卡片效果請見左側卡圖（繁中卡面）</p>
    <div class="badge-row">${chips.join("")}</div>
    ${(d.variants || []).length > 1 ? `<div class="modal-section">
      <h4>同名卡版本（${d.variants.length}）——挑你要收的版本</h4>
      <ul class="variant-list" style="max-height:200px;overflow-y:auto">${variants}</ul></div>` : ""}
    <div class="modal-actions">
      <button class="add">＋ 加入願望清單</button>
      <button class="coll" title="我已經有這張卡，加入收藏">📦 收藏</button>
      <a class="official" href="${esc(d.official_url)}" target="_blank" rel="noopener">官方詳細頁</a>
    </div>`;
}

function bindModalActions(d) {
  const addBtn = modal.querySelector(".add");
  const card = d.game === "ygo"
    ? { id: d.id, game: "ygo", name: d.name, name_jp: d.name_jp,
        collector_number: null, rarity: null, image_url: d.image_url }
    : d.game === "gcg"
    ? { id: d.id, game: "gcg", name: d.name, collector_number: d.id,
        rarity: d.rarity, color: d.color, image_url: d.image_url }
    : d.game === "ga"
    ? { id: d.id, game: "ga", name: d.name,
        collector_number: `${d.set_prefix}-${d.collector_number}`,
        rarity: d.rarity, element: d.element, image_url: d.image_url }
    : { id: d.id, game: "pkm", name: d.name, set_alpha: d.set_alpha,
        collector_number: d.collector_number, rarity: d.rarity,
        image_url: d.image_url };
  if (wishlist.has(keyOf(card))) {
    addBtn.disabled = true;
    addBtn.textContent = "已在清單中";
  }
  addBtn.addEventListener("click", () => {
    wishlist.set(keyOf(card), newWishItem(card));
    if (card.game === "ygo") loadCardRarities(keyOf(card), card.id);
    renderWishlist();
    addBtn.disabled = true;
    addBtn.textContent = "已加入 ✓";
  });
  const collBtn = modal.querySelector(".coll");
  if (collBtn) collBtn.addEventListener("click", async () => {
    collBtn.disabled = true;
    try {
      await addToCollection(card);
      collBtn.textContent = "已收藏 ✓";
    } catch (err) {
      alert("加入收藏失敗：" + err.message);
      collBtn.disabled = false;
    }
  });
  // 切換版本：寶可夢＝同名卡、鋼彈＝異圖（gcg 卡號是字串，不可 parseInt）
  modal.querySelectorAll("[data-vid]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const g = a.dataset.vgame || "pkm";
      openCardModal(g, (g === "gcg" || g === "ga") ? a.dataset.vid : parseInt(a.dataset.vid));
    }));
}

// ---------- 牌組匯入 ----------
// 不直接塞進願望清單——先出校對頁。遊戲王譯名亂、寶可夢同名多版本、鋼彈異圖，
// 靠模糊比對對到的那幾行最容易錯，讓人先看過再加入。
let importItems = [];

$("#importBtn").addEventListener("click", async () => {
  const text = $("#deckText").value.trim();
  if (!text) return;
  $("#importResult").textContent = "解析中…";
  $("#importPreview").hidden = true;
  try {
    const res = await fetch("/api/import-deck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: currentGame(), text }),
    });
    const data = await res.json();
    importItems = data.items || [];
    renderImportPreview(data.unmatched || []);
  } catch (err) {
    $("#importResult").textContent = "匯入失敗：" + err.message;
  }
});

function renderImportPreview(unmatched) {
  const fuzzy = importItems.filter((it) => it.match === "fuzzy").length;
  $("#importResult").textContent =
    `比對到 ${importItems.length} 種卡` +
    (fuzzy ? `，其中 ${fuzzy} 種是模糊比對（下方標 ⚠，請確認）` : "") +
    (unmatched.length ? `；${unmatched.length} 行無法辨識` : "");
  if (!importItems.length && !unmatched.length) {
    $("#importPreview").hidden = true;
    return;
  }
  $("#previewList").innerHTML = importItems.map((it, i) => {
    const c = it.card;
    const sub = c.game === "ygo" ? (c.name_jp || "")
      : `${c.collector_number || ""}${c.rarity ? "・" + c.rarity : ""}`;
    const warn = it.match === "fuzzy";
    return `<li class="${warn ? "fuzzy" : ""}">
      <input type="checkbox" class="pick" data-i="${i}" checked>
      <img src="${esc(c.image_url || "")}" alt="">
      <div class="pinfo">
        <b>${esc(c.name)}</b> ×${it.qty}
        ${warn ? '<span class="warn-tag" title="靠模糊比對對到的，可能不是你要的那張">⚠ 模糊</span>' : ""}
        <small>${esc(sub)}</small>
        ${it.sources && it.sources.length
          ? `<small class="src">原文：${esc(it.sources.join("、"))}</small>` : ""}
      </div></li>`;
  }).join("");
  const um = $("#previewUnmatched");
  um.hidden = !unmatched.length;
  if (unmatched.length) {
    um.innerHTML = `<b>無法辨識的 ${unmatched.length} 行</b>（不會加入）：<br>` +
      unmatched.map((u) => esc(u)).join("<br>");
  }
  $("#importPreview").hidden = false;
}

$("#previewToggleAll").addEventListener("click", () => {
  const boxes = [...document.querySelectorAll("#previewList .pick")];
  const anyChecked = boxes.some((b) => b.checked);
  boxes.forEach((b) => { b.checked = !anyChecked; });
  $("#previewToggleAll").textContent = anyChecked ? "全選" : "全不選";
});

$("#previewCancel").addEventListener("click", () => {
  $("#importPreview").hidden = true;
  $("#importResult").textContent = "已取消，沒有加入任何卡。";
});

$("#previewConfirm").addEventListener("click", () => {
  let added = 0;
  document.querySelectorAll("#previewList .pick").forEach((box) => {
    if (!box.checked) return;
    const it = importItems[Number(box.dataset.i)];
    if (!it) return;
    const key = keyOf(it.card);
    if (wishlist.has(key)) {
      wishlist.get(key).qty += it.qty;
    } else {
      wishlist.set(key, newWishItem(it.card, it.qty));
      if (it.card.game === "ygo") loadCardRarities(key, it.card.id);
    }
    added++;
  });
  renderWishlist();
  $("#importPreview").hidden = true;
  $("#importResult").textContent = added
    ? `已加入 ${added} 種卡到願望清單。` : "沒有勾選任何卡。";
  if (added) $("#deckText").value = "";
});

// ---------- 願望清單持久化與分享 ----------
// 清單的精簡表示法（分享連結與存牌組共用同一套格式，避免兩邊各寫一份）
function wishlistCompact() {
  return [...wishlist.values()].map((it) => ({
    g: it.card.game, id: it.card.id, q: it.qty,
    r: it.rarity || undefined, l: it.lang || undefined, a: it.art || undefined,
  }));
}

// 精簡表示法 → 願望清單（向後端補齊卡片資料）。分享連結與載入牌組共用。
async function hydrateIntoWishlist(items) {
  const byGame = {};
  for (const it of items) (byGame[it.g] = byGame[it.g] || []).push(it);
  await Promise.all(Object.entries(byGame).map(async ([game, its]) => {
    const res = await fetch(`/api/cards?game=${game}&ids=${its.map((i) => i.id).join(",")}`);
    const data = await res.json();
    const cardById = {};
    for (const c of data.cards) cardById[c.id] = c;
    for (const it of its) {
      const c = cardById[it.id];
      if (!c) continue;  // 卡片已不在資料庫（例如換過資料來源）就略過
      wishlist.set(keyOf(c), { card: c, qty: it.q || 1, rarity: it.r || "",
                               lang: it.l || "", art: it.a || "", cardRarities: null });
      if (c.game === "ygo") loadCardRarities(keyOf(c), c.id);
    }
  }));
  renderWishlist();
}

function saveWishlist() {
  const data = [...wishlist.values()].map((it) => ({
    card: it.card, qty: it.qty, rarity: it.rarity, lang: it.lang, art: it.art,
  }));
  localStorage.setItem("cbs_wishlist", JSON.stringify(data));
}

function restoreWishlist() {
  // 分享連結優先（#list=…），其次 localStorage
  const hash = location.hash.match(/#list=([A-Za-z0-9+/=_-]+)/);
  if (hash) {
    try {
      const b64 = hash[1].replace(/-/g, "+").replace(/_/g, "/");
      hydrateIntoWishlist(JSON.parse(decodeURIComponent(escape(atob(b64)))));
      history.replaceState(null, "", location.pathname);
      return;
    } catch (e) { /* 連結壞了就走 localStorage */ }
  }
  try {
    const data = JSON.parse(localStorage.getItem("cbs_wishlist") || "[]");
    for (const it of data) {
      wishlist.set(keyOf(it.card), { card: it.card, qty: it.qty || 1,
                                     rarity: it.rarity || "", lang: it.lang || "",
                                     art: it.art || "", cardRarities: null });
      if (it.card.game === "ygo") loadCardRarities(keyOf(it.card), it.card.id);
    }
    if (wishlist.size) {
      renderWishlist();
      refreshWishlistCards(data);  // 舊存檔的圖片網址可能過期，向後端更新
    }
  } catch (e) { /* 空清單開始 */ }
}

async function refreshWishlistCards(stored) {
  const byGame = {};
  for (const it of stored) (byGame[it.card.game] = byGame[it.card.game] || []).push(it.card.id);
  let changed = false;
  await Promise.all(Object.entries(byGame).map(async ([game, ids]) => {
    try {
      const res = await fetch(`/api/cards?game=${game}&ids=${ids.join(",")}`);
      const data = await res.json();
      for (const c of data.cards) {
        const item = wishlist.get(keyOf(c));
        if (item && item.card.image_url !== c.image_url) {
          item.card = { ...item.card, ...c };
          changed = true;
        }
      }
    } catch (e) { /* 離線時維持舊資料 */ }
  }));
  if (changed) renderWishlist();
}

$("#shareBtn").addEventListener("click", () => {
  if (!wishlist.size) return;
  const compact = wishlistCompact();
  // unescape/escape 包一層讓 btoa 支援中文（如「日紙」）
  const url = `${location.origin}${location.pathname}#list=${btoa(unescape(encodeURIComponent(JSON.stringify(compact))))}`;
  navigator.clipboard.writeText(url).then(
    () => { $("#shareBtn").textContent = "✅ 已複製連結";
            setTimeout(() => { $("#shareBtn").textContent = "🔗 分享清單"; }, 2000); },
    () => { prompt("複製這個連結：", url); });
});

// ---------- 願望清單 ----------
function renderWishlist() {
  saveWishlist();
  const ul = $("#wishlist");
  ul.innerHTML = "";
  for (const [key, item] of wishlist) {
    const c = item.card;
    const li = document.createElement("li");
    let optsHtml = "";
    if (c.game === "ygo") {
      // 有官方收錄資料時，只列這張卡實際出過的稀有度
      const rarityList = item.cardRarities || ygoOptions.rarities;
      const rOpts = [`<option value="">${item.cardRarities ? "稀有度（此卡出過）" : "稀有度?"}</option>`,
        ...rarityList.map((r) =>
          `<option value="${r}" ${item.rarity === r ? "selected" : ""}>${r}</option>`)];
      const lOpts = ['<option value="">紙種不限</option>',
        ...ygoOptions.langs.map((l) =>
          `<option value="${l}" ${item.lang === l ? "selected" : ""}>${l}</option>`)];
      const aOpts = [["", "版本不限"], ["一般", "一般版"], ["超框", "超框/異圖"]]
        .map(([v, t]) => `<option value="${v}" ${item.art === v ? "selected" : ""}>${t}</option>`);
      optsHtml = `<div class="opts">
                    <select class="opt rar">${rOpts.join("")}</select>
                    <select class="opt lang">${lOpts.join("")}</select>
                    <select class="opt art">${aOpts.join("")}</select>
                  </div>`;
    } else if (c.game === "gcg") {
      // 鋼彈：僅版本（日版/美版），稀有度是卡片本身固定屬性不需選
      const lOpts = ['<option value="">版本不限</option>',
        ...gcgOptions.langs.map((l) =>
          `<option value="${l}" ${item.lang === l ? "selected" : ""}>${l}</option>`)];
      optsHtml = `<div class="opts"><select class="opt lang">${lOpts.join("")}</select></div>`;
    } else if (c.game === "ga") {
      // GA：普卡/閃卡（價差大）。稀有度是版本固有屬性不需選；用 lang 欄位承載
      const lOpts = ['<option value="">普/閃不限</option>',
        ...GA_FOILS.map((l) =>
          `<option value="${l}" ${item.lang === l ? "selected" : ""}>${l}</option>`)];
      optsHtml = `<div class="opts"><select class="opt lang">${lOpts.join("")}</select></div>`;
    }
    const subText = c.game === "ygo" ? (c.name_jp || "")
      : `${c.collector_number || ""}${c.rarity ? "・" + c.rarity : ""}`;
    li.innerHTML = `
      <img src="${c.image_url || ""}" alt="">
      <div class="winfo">
        <div class="wtop">
          <span class="wname"><span class="game-icon">${GAME_LABEL[c.game]}</span> <b>${esc(c.name)}</b></span>
          <input class="qty" type="number" min="1" max="9" value="${item.qty}">
          <button class="bell" title="設定到價通知">🔔</button>
          <button class="got" title="已經買到了：移進收藏（沿用目前選的版本條件）">📦</button>
          <button class="rm" title="移除">✕</button>
        </div>
        <small>${subText}</small>
        ${optsHtml}
      </div>`;
    li.querySelector(".qty").addEventListener("change", (e) => {
      item.qty = Math.max(1, parseInt(e.target.value) || 1);
      saveWishlist();
    });
    const rar = li.querySelector(".rar");
    if (rar) rar.addEventListener("change", (e) => { item.rarity = e.target.value; saveWishlist(); });
    const lang = li.querySelector(".lang");
    if (lang) lang.addEventListener("change", (e) => { item.lang = e.target.value; saveWishlist(); });
    const art = li.querySelector(".art");
    if (art) art.addEventListener("change", (e) => { item.art = e.target.value; saveWishlist(); });
    li.querySelector(".bell").addEventListener("click", (e) => addAlertFromWish(item, e.currentTarget));
    // 買到了：整筆移進收藏並移出願望清單（版本條件跟著帶過去）
    li.querySelector(".got").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await addToCollection(c, item, item.qty);
        wishlist.delete(key);
        renderWishlist();
        document.querySelectorAll(`.card-item[data-key="${key}"] button.add`)
          .forEach((b) => { b.disabled = false; b.textContent = "＋ 加入清單"; });
      } catch (err) {
        alert("加入收藏失敗：" + err.message);
        btn.disabled = false;
      }
    });
    li.querySelector(".rm").addEventListener("click", () => {
      wishlist.delete(key);
      renderWishlist();
      // 原地把結果區同一張卡的「已加入」按鈕復原，不重置目前畫面
      document.querySelectorAll(`.card-item[data-key="${key}"] button.add`)
        .forEach((b) => { b.disabled = false; b.textContent = "＋ 加入清單"; });
    });
    ul.appendChild(li);
  }
  $("#wishCount").textContent = wishlist.size;
  $("#compareBtn").disabled = wishlist.size === 0;
  updateDeductBtn();
}

// ---------- 比價 ----------
$("#compareBtn").addEventListener("click", async () => {
  const section = $("#compareSection");
  section.hidden = false;
  $("#compareStatus").innerHTML =
    '<span class="spinner"></span>正在查詢露天拍賣，每張卡約需數秒，請稍候…';
  $("#compareResults").innerHTML = "";
  section.scrollIntoView({ behavior: "smooth" });

  const items = [...wishlist.values()].map((it) => ({
    game: it.card.game, card_id: it.card.id, qty: it.qty,
    rarity: it.rarity || null, lang: it.lang || null, art: it.art || null,
  }));
  let data;
  try {
    const res = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    data = await res.json();
    if (data.error) throw new Error(data.error);
  } catch (err) {
    $("#compareStatus").textContent = "查詢失敗：" + err.message;
    return;
  }
  renderCompare(data);
});

const fmt = (n) => "NT$ " + Number(n).toLocaleString("zh-Hant-TW");
const confLabel = { strong: "高：條件都符合", weak: "中：部分符合", maybe: "低：標題未標示" };

function wantDesc(c) {
  const artLabel = c.art === "超框" ? "超框/異圖" : c.art === "一般" ? "一般版" : null;
  const bits = [c.collector_number, c.rarity, c.lang, artLabel]
    .filter(Boolean).join("・");
  return `${bits}${bits ? " " : ""}×${c.qty}`;
}

function priceCell(listing, market) {
  // 依本次行情區間上色：貼近最低=綠、貼近最高=紅
  let cls = "";
  if (market && market.n >= 3 && market.high > market.low) {
    const pos = (listing.price - market.low) / (market.high - market.low);
    cls = pos <= 0.25 ? "price-low" : pos >= 0.75 ? "price-high" : "";
  } else if (market && listing.price <= market.low) {
    cls = "price-low";
  }
  return `<span class="${cls}">${fmt(listing.price)}</span>`;
}

function sparkline(series) {
  // 每日最低價迷你走勢圖（≥3 個資料日才畫）
  if (!series || series.length < 3) return "";
  const prices = series.map((s) => s[1]);
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const W = 72, H = 18, pad = 2;
  const pts = series.map((s, i) => {
    const x = pad + (i / (series.length - 1)) * (W - pad * 2);
    const y = hi === lo ? H / 2
      : pad + (1 - (s[1] - lo) / (hi - lo)) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"
    title="30 天每日最低價走勢">
    <polyline points="${pts}" fill="none" stroke="#7c3aed" stroke-width="1.5"/></svg>`;
}

function creditNote(s) {
  if (s.credit_rate == null) return "";
  const cnt = s.credit_cnt >= 10000
    ? (s.credit_cnt / 10000).toFixed(1) + "萬" : (s.credit_cnt || "");
  return `<span class="credit">★${s.credit_rate}${cnt ? "（" + cnt + "）" : ""}</span>`;
}

// 流動性：在售量與累計成交量。用來分辨「便宜」與「沒人買」——
// 成交量是賣場商品的累計值，只看相對熱度，別當成本期成交筆數。
function liquidityNote(market) {
  if (!market || !market.n) return "";
  const parts = [];
  if (market.stock) parts.push(`在售 ${market.stock} 張`);
  if (market.sold) parts.push(`累計成交 ${market.sold}`);
  if (!parts.length) return "";
  const cold = market.n <= 2 && !market.sold;  // 貨少又沒成交紀錄＝這價位參考性低
  return `<small class="mkt liq${cold ? " cold" : ""}"` +
    `${cold ? ' title="在售商品少且無成交紀錄，這個價位參考性較低"' : ""}>` +
    `${parts.join("・")}${cold ? " ⚠" : ""}</small>`;
}

function marketNote(market) {
  if (!market || !market.n) return "";
  const range = market.low === market.high
    ? `行情 ${fmt(market.low)}（${market.n} 筆）`
    : `行情 ${fmt(market.low)}～${fmt(market.high)}（${market.n} 筆）`;
  return `<small class="mkt">${range}</small>` + liquidityNote(market);
}

function renderCompare(data) {
  const total = data.wishlist.length;
  const complete = data.sellers.filter((s) => s.complete);
  const marketByKey = {};
  for (const w of data.wishlist) marketByKey[`${w.game}:${w.card_id}`] = w.market;

  // 頂部摘要：最便宜全齊 vs 拆買基準
  let statusHtml;
  if (complete.length) {
    const best = complete[0]; // 後端已排序：全齊在前、總價低在前
    statusHtml = `找到 ${complete.length} 位賣家可一次湊齊全部 ${total} 張卡，` +
      `<b>全齊最低總價 ${fmt(best.total)}</b>（含運）`;
    const sp = data.split_baseline;
    if (sp.found_count === sp.total_count && sp.items.length) {
      const diff = sp.total - best.total;
      statusHtml += diff >= 0
        ? `，比拆買（${fmt(sp.total)}）省 <b class="price-low">${fmt(diff)}</b>`
        : `；拆買更便宜（${fmt(sp.total)}，差 ${fmt(-diff)}）`;
    }
  } else {
    statusHtml = `沒有賣家能一次湊齊全部 ${total} 張` +
      (data.pair ? `，但有<b>雙賣家組合</b>可湊齊（見下方紫框）。` : `，以下依覆蓋數排序。`);
  }
  // 每張卡行情區間
  const mkts = data.wishlist.filter((w) => w.market && w.market.n);
  if (mkts.length) {
    statusHtml += "<br><small>本次行情：" + mkts.map((w) =>
      `${esc(w.card_name)} ${fmt(w.market.low)}${w.market.high > w.market.low ? "～" + fmt(w.market.high) : ""}` +
      sparkline(w.history_series)
    ).join("；") + "</small>";
  }
  const hist = data.wishlist.filter((w) => w.history && w.history.samples > 1);
  if (hist.length) {
    statusHtml += "<br><small>30 天歷史參考價（本站查詢紀錄）：" +
      hist.map((w) => `${esc(w.card_name)} 低 ${fmt(w.history.low)}／均 ${fmt(w.history.avg)}`).join("；") +
      "</small>";
  }
  $("#compareStatus").innerHTML = statusHtml;

  const box = $("#compareResults");
  box.innerHTML = "";

  const bestTotal = complete.length ? complete[0].total : null;
  for (const s of data.sellers) {
    const div = document.createElement("div");
    div.className = "seller-block" + (s.complete ? " complete" : "");
    const covClass = s.complete ? "full" : "part";
    let priceBadge = "";
    if (s.complete && bestTotal !== null) {
      priceBadge = s.total === bestTotal
        ? '<span class="best-badge">💰 全齊最低價</span>'
        : `<span class="diff-note">比最低 +${fmt(s.total - bestTotal).replace("NT$ ", "NT$")}</span>`;
    }
    const rows = s.covered.map((c) => {
      const mkt = marketByKey[`${c.game}:${c.card_id}`];
      return `
      <tr>
        <td>${esc(c.card_name)}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${esc(c.listing.url)}" target="_blank" rel="noopener">${esc(c.listing.title)}</a></td>
        <td><span class="conf ${c.listing.confidence}">${confLabel[c.listing.confidence]}</span></td>
        <td>${priceCell(c.listing, mkt)}<br>${marketNote(mkt)}</td>
      </tr>`;
    }).join("");
    div.innerHTML = `
      <div class="seller-head">
        <span>賣家 ${s.store_url
          ? `<a href="${esc(s.store_url)}" target="_blank" rel="noopener">${esc(s.seller_name || s.seller_nick)}</a>`
          : `#${esc(String(s.seller_id))}（<a href="${esc(s.covered[0].listing.url)}" target="_blank" rel="noopener">看商品頁</a>）`}
          ${creditNote(s)}</span>
        <span class="cov ${covClass}">${s.complete ? "✅ 全齊" : `覆蓋 ${s.covered_count}/${s.total_count} 張`}</span>
        ${priceBadge}
        <span class="price">${fmt(s.total)} <small>（卡 ${fmt(s.subtotal)} + 運 ${fmt(s.shipping)}）</small></span>
      </div>
      <table class="listing-table">
        <tr><th>卡片</th><th>露天商品</th><th>比對信心</th><th>單價</th></tr>${rows}
      </table>
      ${s.missing.length ? `<p class="missing-line">缺：${s.missing.map((m) => `${esc(m.card_name)}${m.rarity ? "（" + esc(m.rarity) + "）" : ""}`).join("、")}</p>` : ""}`;
    box.appendChild(div);
  }

  // 雙賣家組合（沒有單家全齊、或兩家更省時後端才會給）
  if (data.pair) {
    const div = document.createElement("div");
    div.className = "seller-block pair-block";
    const rows = data.pair.items.map((c) => {
      const mkt = marketByKey[`${c.game}:${c.card_id}`];
      return `
      <tr>
        <td>${esc(c.card_name)}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${esc(c.listing.url)}" target="_blank" rel="noopener">${esc(c.listing.title)}</a></td>
        <td>賣家 #${c.seller_id}</td>
        <td>${priceCell(c.listing, mkt)}</td>
      </tr>`;
    }).join("");
    div.innerHTML = `
      <div class="seller-head">
        <span>🤝 雙賣家組合（${data.pair.seller_ids.map((s) => "#" + s).join(" + ")}）可湊齊全部</span>
        <span class="price">${fmt(data.pair.total)} <small>（卡 ${fmt(data.pair.subtotal)} + 運 ${fmt(data.pair.shipping)}）</small></span>
      </div>
      <table class="listing-table">
        <tr><th>卡片</th><th>露天商品</th><th>賣家</th><th>單價</th></tr>${rows}
      </table>`;
    box.appendChild(div);
  }

  // 拆買基準
  const sp = data.split_baseline;
  if (sp.items.length) {
    const div = document.createElement("div");
    div.className = "seller-block split-block";
    const rows = sp.items.map((c) => `
      <tr>
        <td>${esc(c.card_name)}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${esc(c.listing.url)}" target="_blank" rel="noopener">${esc(c.listing.title)}</a></td>
        <td>賣家 #${c.listing.seller_id}</td>
        <td>${fmt(c.listing.price)}</td>
      </tr>`).join("");
    div.innerHTML = `
      <div class="seller-head">
        <span>📦 拆買基準（每張卡取全站最低價，共 ${sp.seller_count} 位賣家）</span>
        <span class="price">${fmt(sp.total)} <small>（卡 ${fmt(sp.subtotal)} + 運 ${fmt(sp.shipping)}）</small></span>
      </div>
      <table class="listing-table">
        <tr><th>卡片</th><th>露天商品</th><th>賣家</th><th>單價</th></tr>${rows}
      </table>
      ${sp.found_count < sp.total_count ? `<p class="missing-line">有 ${sp.total_count - sp.found_count} 張卡在露天找不到符合的商品</p>` : ""}`;
    box.appendChild(div);
  }

  if (!data.sellers.length && !sp.items.length) {
    box.innerHTML = '<p class="empty">露天上找不到符合這些卡片條件的商品。</p>';
  }
}

// ---------- 到價通知 ----------
let alertPoll = null;

// 訪客識別：每個瀏覽器一組隨機 ID（存 localStorage），讓多人各自有獨立的
// Webhook 與通知清單。免登入、非嚴謹權限；清掉瀏覽器資料等於重置自己那份。
function clientId() {
  let id = localStorage.getItem("cbs_client");
  if (!id) {
    id = (crypto.randomUUID ? crypto.randomUUID()
          : Date.now().toString(36) + Math.random().toString(36).slice(2));
    localStorage.setItem("cbs_client", id);
  }
  return id;
}
// 到價通知相關請求都帶上訪客 ID
function alertFetch(url, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, { "X-Client-Id": clientId() });
  return fetch(url, opts);
}

// 目標價輸入：純數字，或「-10%」「-10」這種相對基準的寫法。
// base 為 null（查不到行情）時只接受純數字，避免相對於「沒有」算出怪數字。
function parseTargetPrice(raw, base) {
  const s = (raw || "").trim();
  const pct = s.match(/^([+-]?\d+(?:\.\d+)?)\s*%$/);
  if (pct) {
    if (base == null) return null;
    return Math.max(1, Math.round(base * (1 + parseFloat(pct[1]) / 100)));
  }
  const rel = s.match(/^([+-]\d+)$/);   // 明確帶正負號＝相對基準加減
  if (rel) {
    if (base == null) return null;
    return Math.max(1, base + parseInt(rel[1], 10));
  }
  const n = parseInt(s.replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : null;
}

// 從願望清單某張卡建立通知：沿用該卡目前選的稀有度/紙種/版本條件
async function addAlertFromWish(item, bellBtn) {
  const c = item.card;
  const cond = [item.rarity, item.lang, item.art].filter(Boolean).join("・");
  // 先查一次目前露天最低價，給使用者參考、並當預設值（查露天需數秒）
  let quote = null;
  if (bellBtn) { bellBtn.disabled = true; bellBtn.textContent = "⏳"; }
  try {
    const res = await fetch("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game: c.game, card_id: c.id,
        rarity: item.rarity || null, lang: item.lang || null, art: item.art || null,
      }),
    });
    quote = await res.json();
  } catch (e) { /* 查不到就讓使用者直接填 */ }
  finally { if (bellBtn) { bellBtn.disabled = false; bellBtn.textContent = "🔔"; } }

  // 相對定價的基準：優先用目前最低價，沒有才退回 30 天均價
  const base = (quote && quote.min_price != null) ? quote.min_price
             : (quote && quote.avg_price != null) ? quote.avg_price : null;
  const lines = [];
  let def = "";
  if (quote && quote.min_price != null) {
    lines.push(`目前露天最低約 ${fmt(quote.min_price)}（${quote.reliable_count} 筆可靠報價）`);
    def = String(quote.min_price);
  } else {
    lines.push("目前露天查無符合的商品——仍可設定，之後有貨且達標會通知。");
  }
  if (quote && quote.avg_price != null) {
    lines.push(`近 30 天均價 ${fmt(quote.avg_price)}、最低 ${fmt(quote.hist_low)}（${quote.hist_samples} 次紀錄）`);
  }
  if (quote && quote.stock) {
    lines.push(`在售 ${quote.stock} 張${quote.sold ? `・累計成交 ${quote.sold}` : ""}`);
  }
  if (base != null) lines.push("可直接填數字，或填 -10% 表示比上面的基準低一成");

  const ans = prompt(
    `為「${c.name}」${cond ? "（" + cond + "）" : ""}設定目標價（NT$）\n` +
    `${lines.join("\n")}\n露天最低價跌到這個價格以下時通知你：`, def);
  if (ans === null) return;
  const target = parseTargetPrice(ans, base);
  if (!target || target <= 0) {
    alert(base == null
      ? "請輸入大於 0 的數字"
      : "請輸入大於 0 的數字，或像 -10% 這樣的百分比");
    return;
  }
  try {
    const res = await alertFetch("/api/alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game: c.game, card_id: c.id, target_price: target,
        rarity: item.rarity || null, lang: item.lang || null, art: item.art || null,
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    await loadAlerts();
    $("#alertSection").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    alert("設定失敗：" + err.message);
  }
}

async function loadAlerts() {
  let data;
  try {
    const res = await alertFetch("/api/alerts");
    data = await res.json();
  } catch (e) { return; }
  // Webhook 狀態
  const wStatus = $("#webhookStatus");
  if (data.webhook_set) {
    wStatus.innerHTML = `✅ 已設定 Webhook（${esc(data.webhook_hint)}）`;
    if (!document.activeElement || document.activeElement.id !== "webhookInput") {
      if (!$("#webhookInput").value) $("#webhookInput").placeholder = `已設定 ${data.webhook_hint}`;
    }
  } else {
    wStatus.textContent = "尚未設定 Webhook——設定後達標才會推播到 Discord。";
  }
  renderAlerts(data.alerts);
  // 背景檢查中：顯示提示並輪詢，結束後停止
  const cs = $("#alertCheckStatus");
  if (data.checking) {
    cs.innerHTML = '<span class="spinner"></span>檢查中，請稍候…';
    $("#alertCheckBtn").disabled = true;
    if (!alertPoll) alertPoll = setInterval(loadAlerts, 4000);
  } else {
    $("#alertCheckBtn").disabled = false;
    if (alertPoll) {
      clearInterval(alertPoll); alertPoll = null;
      cs.textContent = "檢查完成。";
    }
  }
}

function renderAlerts(alerts) {
  $("#alertCount").textContent = alerts.length;
  const ul = $("#alertList");
  ul.innerHTML = "";
  if (!alerts.length) {
    ul.innerHTML = '<li class="empty">還沒有到價通知——到願望清單按 🔔 新增。</li>';
    return;
  }
  for (const a of alerts) {
    const cond = [a.rarity, a.lang, a.art].filter(Boolean).join("・");
    const li = document.createElement("li");
    li.className = "alert-item" + (a.status === "paused" ? " paused" : "");
    // 狀態文字
    let state;
    if (a.status === "paused") {
      state = '<span class="a-state paused">已暫停</span>';
    } else if (a.notified) {
      state = `<span class="a-state hit">✅ 已達標 ${fmt(a.hit_price)}` +
        (a.hit_url ? ` <a href="${a.hit_url}" target="_blank" rel="noopener">看商品</a>` : "") +
        "</span>";
    } else if (a.last_price != null) {
      state = `<span class="a-state wait">等待中・目前最低 ${fmt(a.last_price)}</span>`;
    } else if (a.last_checked) {
      state = '<span class="a-state none">目前露天查無符合商品</span>';
    } else {
      state = '<span class="a-state none">尚未檢查</span>';
    }
    li.innerHTML = `
      <img src="${a.image_url || ""}" alt="">
      <div class="a-info">
        <div class="a-top">
          <span class="a-name"><span class="game-icon">${GAME_LABEL[a.game]}</span> <b>${esc(a.card_name || String(a.card_id))}</b></span>
          <span class="a-target">目標 ${fmt(a.target_price)}</span>
        </div>
        <small>${cond ? esc(cond) + "　" : ""}${a.last_checked ? "最後檢查 " + esc(a.last_checked) : ""}</small>
        <div class="a-bottom">
          ${state}
          <span class="a-actions">
            <button data-act="edit">改目標價</button>
            <button data-act="toggle">${a.status === "paused" ? "啟用" : "暫停"}</button>
            ${a.notified ? '<button data-act="rearm">重設</button>' : ""}
            <button data-act="del">刪除</button>
          </span>
        </div>
      </div>`;
    li.querySelector('[data-act="edit"]').addEventListener("click", () => editAlert(a));
    li.querySelector('[data-act="toggle"]').addEventListener("click", () =>
      updateAlert(a.id, { status: a.status === "paused" ? "active" : "paused" }));
    const rearm = li.querySelector('[data-act="rearm"]');
    if (rearm) rearm.addEventListener("click", () => updateAlert(a.id, { rearm: true }));
    li.querySelector('[data-act="del"]').addEventListener("click", () => {
      if (confirm(`刪除「${a.card_name}」的到價通知？`)) deleteAlert(a.id);
    });
    ul.appendChild(li);
  }
}

async function editAlert(a) {
  // 基準用最近一次查到的最低價，讓這裡也能填「-10%」（與新增時同一套規則）
  const base = a.last_price != null ? a.last_price : null;
  const ans = prompt(
    `修改「${a.card_name}」的目標價（NT$）：` +
    (base != null ? `\n最近查到最低 ${fmt(base)}，可填 -10% 表示比它低一成` : ""),
    a.target_price);
  if (ans === null) return;
  const target = parseTargetPrice(ans, base);
  if (!target || target <= 0) { alert("請輸入大於 0 的數字，或像 -10% 這樣的百分比"); return; }
  updateAlert(a.id, { target_price: target });
}

async function updateAlert(id, body) {
  try {
    const res = await alertFetch(`/api/alerts/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    loadAlerts();
  } catch (err) { alert("更新失敗：" + err.message); }
}

async function deleteAlert(id) {
  await alertFetch(`/api/alerts/${id}`, { method: "DELETE" });
  loadAlerts();
}

$("#webhookSave").addEventListener("click", async () => {
  const url = $("#webhookInput").value.trim();
  $("#webhookStatus").textContent = "儲存中…";
  try {
    const res = await alertFetch("/api/settings/webhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ webhook: url }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    $("#webhookInput").value = "";
    loadAlerts();
  } catch (err) { $("#webhookStatus").textContent = "儲存失敗：" + err.message; }
});

$("#webhookTest").addEventListener("click", async () => {
  $("#webhookStatus").textContent = "傳送測試訊息中…";
  try {
    const res = await alertFetch("/api/settings/webhook/test", { method: "POST" });
    const data = await res.json();
    $("#webhookStatus").textContent = data.ok
      ? "✅ 測試訊息已送出，請到 Discord 查看。"
      : "❌ " + (data.error || "傳送失敗");
  } catch (err) { $("#webhookStatus").textContent = "傳送失敗：" + err.message; }
});

$("#alertCheckBtn").addEventListener("click", async () => {
  $("#alertCheckStatus").innerHTML = '<span class="spinner"></span>開始檢查…';
  $("#alertCheckBtn").disabled = true;
  try {
    await alertFetch("/api/alerts/check", { method: "POST" });
    loadAlerts();  // 進入輪詢模式
  } catch (err) {
    $("#alertCheckStatus").textContent = "檢查失敗：" + err.message;
    $("#alertCheckBtn").disabled = false;
  }
});

loadAlerts();

// ---------- 我的收藏 ----------
// 「我已經有什麼」，與願望清單（我還缺什麼）互補。存後端（同 client_id），
// 因為收藏是長期資料又帶成本價，放 localStorage 清瀏覽器就沒了。
let collection = [];

async function loadCollection() {
  let data;
  try {
    const res = await alertFetch("/api/collection");
    data = await res.json();
  } catch (e) { return; }
  collection = data.items || [];
  renderCollection(data.summary || {});
}

// 加入收藏：card 為卡片物件，cond 帶願望清單那套版本條件（可省略）
async function addToCollection(card, cond = {}, qty = 1) {
  const res = await alertFetch("/api/collection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      game: card.game, card_id: card.id, qty,
      rarity: cond.rarity || null, lang: cond.lang || null, art: cond.art || null,
    }),
  });
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  await loadCollection();
}

function collCondText(it) {
  return [it.rarity, it.lang, it.art].filter(Boolean).join("・");
}

function renderCollection(summary) {
  const ul = $("#collectionList");
  ul.innerHTML = "";
  for (const it of collection) {
    const li = document.createElement("li");
    const cond = collCondText(it);
    // 市值來自比價時存下的價格快照；沒查過這張卡就沒有數字，據實留白
    const mkt = it.market_price == null ? "—"
      : fmt(it.market_price) + (it.market_basis === "card" ? "＊" : "");
    const gain = (it.unit_price != null && it.market_price != null)
      ? (it.market_price - it.unit_price) * it.qty : null;
    li.innerHTML = `
      <img src="${it.image_url || ""}" alt="">
      <div class="winfo">
        <div class="wtop">
          <span class="wname"><span class="game-icon">${GAME_LABEL[it.game]}</span>
            <b>${esc(it.card_name || "")}</b></span>
          <input class="qty" type="number" min="1" max="99" value="${it.qty}"
                 title="持有張數">
          <button class="rm" title="移除">✕</button>
        </div>
        <small>${esc(cond) || "未指定版本"}</small>
        <div class="coll-money">
          <label>成本 <input class="cost" type="number" min="0" placeholder="未記"
                 value="${it.unit_price ?? ""}"></label>
          <span class="coll-mkt">現價 ${mkt}</span>
          ${gain == null ? "" :
            `<span class="coll-gain ${gain >= 0 ? "up" : "down"}">${
              gain >= 0 ? "▲" : "▼"} ${fmt(Math.abs(gain))}</span>`}
        </div>
      </div>`;
    li.querySelector(".qty").addEventListener("change", (e) =>
      updateCollection(it.id, { qty: parseInt(e.target.value) || 0 }));
    li.querySelector(".cost").addEventListener("change", (e) =>
      updateCollection(it.id, { unit_price: e.target.value.trim() || null }));
    li.querySelector(".rm").addEventListener("click", async () => {
      await alertFetch(`/api/collection/${it.id}`, { method: "DELETE" });
      loadCollection();
    });
    ul.appendChild(li);
  }
  $("#collCount").textContent = collection.length;

  const box = $("#collSummary");
  if (!collection.length) {
    box.hidden = true;
  } else {
    box.hidden = false;
    const gain = summary.market - summary.cost;
    // 只有部分收藏記了成本時，損益的基準不同，明講以免誤讀
    const partial = summary.priced_qty && summary.priced_qty < summary.total_qty;
    box.innerHTML = `
      <span>${summary.kinds} 種・共 ${summary.total_qty} 張</span>
      <span>成本 ${fmt(summary.cost)}</span>
      <span>市值 ${fmt(summary.market)}</span>
      ${summary.cost ? `<span class="coll-gain ${gain >= 0 ? "up" : "down"}">${
        gain >= 0 ? "▲" : "▼"} ${fmt(Math.abs(gain))}</span>` : ""}
      ${partial ? "<small>（僅部分收藏記了成本，損益不含未記的）</small>" : ""}
      <small>市值取比價時存下的最低價快照，＊為不分版本的參考價；沒查過的卡不計入。</small>`;
  }
  updateDeductBtn();
}

function updateDeductBtn() {
  const btn = $("#deductBtn");
  if (btn) btn.disabled = !(collection.length && wishlist.size);
}

async function updateCollection(id, body) {
  await alertFetch(`/api/collection/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  loadCollection();
}

// 扣除已收藏：先向後端試算，再讓使用者確認才真的動清單
$("#deductBtn").addEventListener("click", async () => {
  if (!wishlist.size) return;
  const entries = [...wishlist.entries()];
  const out = $("#deductResult");
  out.textContent = "計算中…";
  let data;
  try {
    const res = await alertFetch("/api/collection/deduct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: entries.map(([, it]) => ({
          game: it.card.game, card_id: it.card.id, qty: it.qty,
          rarity: it.rarity || null, lang: it.lang || null, art: it.art || null,
        })),
      }),
    });
    data = await res.json();
  } catch (err) {
    out.textContent = "計算失敗：" + err.message;
    return;
  }
  if (!data.summary.qty) {
    out.textContent = "願望清單裡沒有你已收藏的卡，不需扣除。";
    return;
  }
  // 後端回傳順序與送出的 items 一致，直接用索引對回願望清單
  const lines = data.items.map((r, i) => {
    if (!r.owned) return null;
    const it = entries[i][1];
    return `・${it.card.name}：已有 ${r.owned}／需要 ${r.want}` +
           (r.remaining ? `，還缺 ${r.remaining}` : "，已湊齊");
  }).filter(Boolean);
  if (!confirm(`將依「我的收藏」扣除以下張數：\n\n${lines.join("\n")}\n\n` +
               `共扣 ${data.summary.qty} 張，湊齊的卡會從清單移除。要套用嗎？`)) {
    out.textContent = "已取消。";
    return;
  }
  let removed = 0, reduced = 0;
  data.items.forEach((r, i) => {
    if (!r.owned) return;
    const [key, item] = entries[i];
    if (r.remaining <= 0) { wishlist.delete(key); removed++; }
    else { item.qty = r.remaining; reduced++; }
  });
  renderWishlist();
  // 被移除的卡，把搜尋結果那顆「已加入」按鈕復原
  document.querySelectorAll(".card-item").forEach((el) => {
    if (!wishlist.has(el.dataset.key)) {
      const b = el.querySelector("button.add");
      if (b) { b.disabled = false; b.textContent = "＋ 加入清單"; }
    }
  });
  out.textContent = `已扣除 ${data.summary.qty} 張：${removed} 種湊齊移除、${reduced} 種減量。`;
});

loadCollection();

// ---------- 我的牌組 ----------
// 原本匯入牌組是一次性的（匯完就散成清單）。存起來才能切換多套牌各自比價。
let decks = [];

async function loadDecks() {
  try {
    const res = await alertFetch("/api/decks");
    decks = (await res.json()).decks || [];
  } catch (e) { return; }
  const sel = $("#deckSelect");
  const keep = sel.value;
  sel.innerHTML = decks.length
    ? decks.map((d) =>
        `<option value="${d.id}">${esc(d.name)}（${GAME_LABEL[d.game] || "混"}・${d.kinds} 種 ${d.qty} 張）</option>`
      ).join("")
    : '<option value="">（尚無牌組）</option>';
  if (keep && decks.some((d) => String(d.id) === keep)) sel.value = keep;
  $("#deckCount").textContent = decks.length;
  const none = !decks.length;
  $("#deckLoad").disabled = none;
  $("#deckDelete").disabled = none;
}

$("#deckSave").addEventListener("click", async () => {
  const out = $("#deckResult");
  if (!wishlist.size) { out.textContent = "願望清單是空的，沒東西可存。"; return; }
  const name = $("#deckName").value.trim();
  if (!name) { out.textContent = "請先輸入牌組名稱。"; return; }
  try {
    const res = await alertFetch("/api/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, items: wishlistCompact() }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    $("#deckName").value = "";
    await loadDecks();
    $("#deckSelect").value = String(data.id);
    out.textContent = data.overwritten
      ? `已覆蓋牌組「${name}」。` : `已存成牌組「${name}」。`;
  } catch (err) { out.textContent = "儲存失敗：" + err.message; }
});

$("#deckLoad").addEventListener("click", async () => {
  const id = $("#deckSelect").value;
  const out = $("#deckResult");
  if (!id) return;
  // 會蓋掉目前清單，先問——清單可能是剛整理好的
  if (wishlist.size &&
      !confirm(`載入牌組會取代目前的願望清單（${wishlist.size} 種卡）。要繼續嗎？`)) {
    out.textContent = "已取消。";
    return;
  }
  out.textContent = "載入中…";
  try {
    const res = await alertFetch(`/api/decks/${id}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    wishlist.clear();
    await hydrateIntoWishlist(data.items);
    // 結果區的「已加入」狀態要跟著新清單重算
    document.querySelectorAll(".card-item").forEach((el) => {
      const b = el.querySelector("button.add");
      if (!b) return;
      const inList = wishlist.has(el.dataset.key);
      b.disabled = inList;
      b.textContent = inList ? "已加入" : "＋ 加入清單";
    });
    const miss = data.items.length - wishlist.size;
    out.textContent = `已載入「${data.name}」${wishlist.size} 種卡` +
      (miss > 0 ? `（${miss} 種在資料庫中已找不到，略過）` : "");
  } catch (err) { out.textContent = "載入失敗：" + err.message; }
});

$("#deckDelete").addEventListener("click", async () => {
  const id = $("#deckSelect").value;
  if (!id) return;
  const d = decks.find((x) => String(x.id) === id);
  if (!confirm(`確定刪除牌組「${d ? d.name : id}」？`)) return;
  await alertFetch(`/api/decks/${id}`, { method: "DELETE" });
  await loadDecks();
  $("#deckResult").textContent = "已刪除。";
});

loadDecks();

// ---------- 你最常查的卡 ----------
// 依 price_history 統計（＝本機查過的紀錄，不是市場熱度）。切換遊戲時重載。
async function loadTrending() {
  const sec = $("#trendingSection");
  let cards = [];
  try {
    const res = await fetch(`/api/trending?game=${currentGame()}`);
    cards = (await res.json()).cards || [];
  } catch (e) { return; }
  sec.hidden = !cards.length;
  $("#trendingList").innerHTML = cards.map((c) => {
    const cond = [c.rarity, c.lang].filter(Boolean).join("・");
    const flat = c.change_pct == null || c.change_pct === 0;
    const up = !flat && c.change_pct > 0;
    return `<button class="trend-item" data-g="${esc(c.game)}" data-id="${esc(c.card_id)}">
      <img src="${esc(c.image_url || "")}" alt="">
      <span class="tname">${esc(c.name)}</span>
      ${cond ? `<span class="tcond">${esc(cond)}</span>` : ""}
      <span class="tprice">${fmt(c.last_price)}</span>
      <span class="tchg ${flat ? "" : up ? "up" : "down"}">${
        flat ? "—" : `${up ? "▲" : "▼"} ${Math.abs(c.change_pct)}%`}</span>
      <span class="tn">查過 ${c.samples} 次</span>
    </button>`;
  }).join("");
  $("#trendingList").querySelectorAll(".trend-item").forEach((b) =>
    b.addEventListener("click", () => openCardModal(b.dataset.g, b.dataset.id)));
}

document.querySelectorAll('input[name="game"]').forEach((r) =>
  r.addEventListener("change", loadTrending));

loadTrending();
