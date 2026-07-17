// CardBuySearch 前端邏輯
const $ = (sel) => document.querySelector(sel);
const wishlist = new Map(); // key "game:id" -> {card, qty, rarity, lang}
let ygoOptions = { rarities: [], langs: [] };

const GAME_LABEL = { pkm: "寶可夢", ygo: "遊戲王" };

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
loadRarities();
loadYgoOptions();
restoreWishlist();

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
    const ygo = currentGame() === "ygo";
    $("#raritySelect").style.display = ygo ? "none" : "";
    $("#searchInput").placeholder = ygo
      ? "卡名（例：灰流麗、増殖するG，中日文皆可）"
      : "卡名或編號（例：噴火龍、094/081）";
    $("#searchResults").innerHTML = "";
    stopBrowse();
  }));

// ---------- 搜尋 ----------
async function doSearch() {
  stopBrowse();
  const q = $("#searchInput").value.trim();
  const game = currentGame();
  const rarity = game === "pkm" ? $("#raritySelect").value : "";
  if (!q && !rarity) return;
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
  return `
    <select data-fkey="${key}">
      <option value="">${label}</option>
      ${(values || []).map((v) =>
        `<option value="${v}" ${keep === v ? "selected" : ""}>${v}</option>`).join("")}
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
  } else {
    bar.innerHTML =
      filterSelect("kind", "卡片大類", opts.kinds, cur.kind) +
      ((cur.kind || "寶可夢") === "寶可夢"
        ? filterSelect("ptype", "屬性", opts.ptypes, cur.ptype) +
          filterSelect("stage", "階段/機制", opts.stages, cur.stage)
        : "") +
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

function cardEl(c) {
  const div = document.createElement("div");
  div.className = "card-item";
  const inList = wishlist.has(keyOf(c));
  const sub = c.game === "ygo"
    ? `${c.name_jp || ""}`
    : `${c.set_alpha || ""} ${c.collector_number || ""}`;
  div.innerHTML = `
    <div class="card-click" title="查看卡片詳情">
      <img src="${c.image_url || ""}" alt="${c.name || ""}">
      <div class="meta">
        <span class="name">${c.name || "（未知）"}</span>
        <span class="sub">${sub}</span>
        ${c.rarity ? `<span class="rarity-tag">${c.rarity}</span>` : ""}
      </div>
    </div>
    <button ${inList ? "disabled" : ""}>${inList ? "已加入" : "＋ 加入清單"}</button>`;
  div.querySelector(".card-click").addEventListener("click", () =>
    openCardModal(c.game, c.id));
  div.querySelector("button").addEventListener("click", (e) => {
    // 遊戲王預設日紙（台灣玩家主流），可在清單改成韓紙/英紙/不限
    const item = { card: c, qty: 1, rarity: "", art: "",
                   lang: c.game === "ygo" ? "日紙" : "", cardRarities: null };
    wishlist.set(keyOf(c), item);
    e.target.disabled = true;
    e.target.textContent = "已加入";
    renderWishlist();
    if (c.game === "ygo") loadCardRarities(keyOf(c), c.id);
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
  $("#modalInfo").innerHTML = d.game === "ygo" ? ygoDetailHtml(d) : pkmDetailHtml(d);
  bindModalActions(d);
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
      <a class="official" href="${esc(d.official_url)}" target="_blank" rel="noopener">官方詳細頁</a>
    </div>`;
}

function bindModalActions(d) {
  const addBtn = modal.querySelector(".add");
  const card = d.game === "ygo"
    ? { id: d.id, game: "ygo", name: d.name, name_jp: d.name_jp,
        collector_number: null, rarity: null, image_url: d.image_url }
    : { id: d.id, game: "pkm", name: d.name, set_alpha: d.set_alpha,
        collector_number: d.collector_number, rarity: d.rarity,
        image_url: d.image_url };
  if (wishlist.has(keyOf(card))) {
    addBtn.disabled = true;
    addBtn.textContent = "已在清單中";
  }
  addBtn.addEventListener("click", () => {
    wishlist.set(keyOf(card), { card, qty: 1, rarity: "", art: "",
                                lang: card.game === "ygo" ? "日紙" : "",
                                cardRarities: null });
    if (card.game === "ygo") loadCardRarities(keyOf(card), card.id);
    renderWishlist();
    addBtn.disabled = true;
    addBtn.textContent = "已加入 ✓";
  });
  // 寶可夢：切換同名卡版本
  modal.querySelectorAll("[data-vid]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      openCardModal("pkm", parseInt(a.dataset.vid));
    }));
}

// ---------- 牌組匯入 ----------
$("#importBtn").addEventListener("click", async () => {
  const text = $("#deckText").value.trim();
  if (!text) return;
  $("#importResult").textContent = "解析中…";
  try {
    const res = await fetch("/api/import-deck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: currentGame(), text }),
    });
    const data = await res.json();
    let added = 0;
    for (const it of data.items) {
      const key = keyOf(it.card);
      if (wishlist.has(key)) {
        wishlist.get(key).qty += it.qty;
      } else {
        wishlist.set(key, { card: it.card, qty: it.qty, rarity: "", art: "",
                            lang: it.card.game === "ygo" ? "日紙" : "",
                            cardRarities: null });
        if (it.card.game === "ygo") loadCardRarities(key, it.card.id);
      }
      added++;
    }
    renderWishlist();
    $("#importResult").textContent = `匯入 ${added} 種卡` +
      (data.unmatched.length
        ? `；${data.unmatched.length} 行無法辨識：${data.unmatched.slice(0, 3).join("、")}${data.unmatched.length > 3 ? "…" : ""}`
        : "");
    if (added) $("#deckText").value = "";
  } catch (err) {
    $("#importResult").textContent = "匯入失敗：" + err.message;
  }
});

// ---------- 願望清單持久化與分享 ----------
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
      const items = JSON.parse(decodeURIComponent(escape(atob(b64))));
      const byGame = {};
      for (const it of items) (byGame[it.g] = byGame[it.g] || []).push(it);
      Promise.all(Object.entries(byGame).map(async ([game, its]) => {
        const res = await fetch(`/api/cards?game=${game}&ids=${its.map((i) => i.id).join(",")}`);
        const data = await res.json();
        const cardById = {};
        for (const c of data.cards) cardById[c.id] = c;
        for (const it of its) {
          const c = cardById[it.id];
          if (!c) continue;
          wishlist.set(keyOf(c), { card: c, qty: it.q || 1, rarity: it.r || "",
                                   lang: it.l || "", art: it.a || "", cardRarities: null });
          if (c.game === "ygo") loadCardRarities(keyOf(c), c.id);
        }
      })).then(() => renderWishlist());
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
  const compact = [...wishlist.values()].map((it) => ({
    g: it.card.game, id: it.card.id, q: it.qty,
    r: it.rarity || undefined, l: it.lang || undefined, a: it.art || undefined,
  }));
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
    }
    li.innerHTML = `
      <img src="${c.image_url || ""}" alt="">
      <div class="winfo">
        <span class="game-icon">${GAME_LABEL[c.game]}</span> <b>${c.name}</b><br>
        <small>${c.game === "ygo" ? (c.name_jp || "") : `${c.collector_number || ""} ${c.rarity ? "・" + c.rarity : ""}`}</small>
        ${optsHtml}
      </div>
      <input class="qty" type="number" min="1" max="9" value="${item.qty}">
      <button class="rm" title="移除">✕</button>`;
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
    li.querySelector(".rm").addEventListener("click", () => {
      wishlist.delete(key);
      renderWishlist();
      doSearch();
    });
    ul.appendChild(li);
  }
  $("#wishCount").textContent = wishlist.size;
  $("#compareBtn").disabled = wishlist.size === 0;
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

function marketNote(market) {
  if (!market || !market.n) return "";
  if (market.low === market.high) return `<small class="mkt">行情 ${fmt(market.low)}（${market.n} 筆）</small>`;
  return `<small class="mkt">行情 ${fmt(market.low)}～${fmt(market.high)}（${market.n} 筆）</small>`;
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
      `${w.card_name} ${fmt(w.market.low)}${w.market.high > w.market.low ? "～" + fmt(w.market.high) : ""}` +
      sparkline(w.history_series)
    ).join("；") + "</small>";
  }
  const hist = data.wishlist.filter((w) => w.history && w.history.samples > 1);
  if (hist.length) {
    statusHtml += "<br><small>30 天歷史參考價（本站查詢紀錄）：" +
      hist.map((w) => `${w.card_name} 低 ${fmt(w.history.low)}／均 ${fmt(w.history.avg)}`).join("；") +
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
        <td>${c.card_name}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${c.listing.url}" target="_blank" rel="noopener">${c.listing.title}</a></td>
        <td><span class="conf ${c.listing.confidence}">${confLabel[c.listing.confidence]}</span></td>
        <td>${priceCell(c.listing, mkt)}<br>${marketNote(mkt)}</td>
      </tr>`;
    }).join("");
    div.innerHTML = `
      <div class="seller-head">
        <span>賣家 ${s.store_url
          ? `<a href="${s.store_url}" target="_blank" rel="noopener">${s.seller_name || s.seller_nick}</a>`
          : `#${s.seller_id}（<a href="${s.covered[0].listing.url}" target="_blank" rel="noopener">看商品頁</a>）`}
          ${creditNote(s)}</span>
        <span class="cov ${covClass}">${s.complete ? "✅ 全齊" : `覆蓋 ${s.covered_count}/${s.total_count} 張`}</span>
        ${priceBadge}
        <span class="price">${fmt(s.total)} <small>（卡 ${fmt(s.subtotal)} + 運 ${fmt(s.shipping)}）</small></span>
      </div>
      <table class="listing-table">
        <tr><th>卡片</th><th>露天商品</th><th>比對信心</th><th>單價</th></tr>${rows}
      </table>
      ${s.missing.length ? `<p class="missing-line">缺：${s.missing.map((m) => `${m.card_name}${m.rarity ? "（" + m.rarity + "）" : ""}`).join("、")}</p>` : ""}`;
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
        <td>${c.card_name}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${c.listing.url}" target="_blank" rel="noopener">${c.listing.title}</a></td>
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
        <td>${c.card_name}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${c.listing.url}" target="_blank" rel="noopener">${c.listing.title}</a></td>
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
