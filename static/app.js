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

document.querySelectorAll('input[name="game"]').forEach((el) =>
  el.addEventListener("change", () => {
    const ygo = currentGame() === "ygo";
    $("#raritySelect").style.display = ygo ? "none" : "";
    $("#searchInput").placeholder = ygo
      ? "卡名（例：灰流麗、増殖するG，中日文皆可）"
      : "卡名或編號（例：噴火龍、094/081）";
    $("#searchResults").innerHTML = "";
  }));

// ---------- 搜尋 ----------
async function doSearch() {
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

function keyOf(c) { return `${c.game}:${c.id}`; }

function cardEl(c) {
  const div = document.createElement("div");
  div.className = "card-item";
  const inList = wishlist.has(keyOf(c));
  const sub = c.game === "ygo"
    ? `${c.name_jp || ""}`
    : `${c.set_alpha || ""} ${c.collector_number || ""}`;
  div.innerHTML = `
    <img src="${c.image_url || ""}" alt="${c.name || ""}">
    <div class="meta">
      <span class="name">${c.name || "（未知）"}</span>
      <span class="sub">${sub}</span>
      ${c.rarity ? `<span class="rarity-tag">${c.rarity}</span>` : ""}
    </div>
    <button ${inList ? "disabled" : ""}>${inList ? "已加入" : "＋ 加入清單"}</button>`;
  div.querySelector("button").addEventListener("click", (e) => {
    wishlist.set(keyOf(c), { card: c, qty: 1, rarity: "", lang: "" });
    e.target.disabled = true;
    e.target.textContent = "已加入";
    renderWishlist();
  });
  return div;
}

// ---------- 願望清單 ----------
function renderWishlist() {
  const ul = $("#wishlist");
  ul.innerHTML = "";
  for (const [key, item] of wishlist) {
    const c = item.card;
    const li = document.createElement("li");
    let optsHtml = "";
    if (c.game === "ygo") {
      const rOpts = ['<option value="">稀有度?</option>',
        ...ygoOptions.rarities.map((r) =>
          `<option value="${r}" ${item.rarity === r ? "selected" : ""}>${r}</option>`)];
      const lOpts = ['<option value="">紙種不限</option>',
        ...ygoOptions.langs.map((l) =>
          `<option value="${l}" ${item.lang === l ? "selected" : ""}>${l}</option>`)];
      optsHtml = `<select class="opt rar">${rOpts.join("")}</select>
                  <select class="opt lang">${lOpts.join("")}</select>`;
    }
    li.innerHTML = `
      <img src="${c.image_url || ""}" alt="">
      <div class="winfo">
        <span class="game-icon">${GAME_LABEL[c.game]}</span> <b>${c.name}</b><br>
        <small>${c.game === "ygo" ? (c.name_jp || "") : `${c.collector_number || ""} ${c.rarity ? "・" + c.rarity : ""}`}</small><br>
        ${optsHtml}
      </div>
      <input class="qty" type="number" min="1" max="9" value="${item.qty}">
      <button class="rm" title="移除">✕</button>`;
    li.querySelector(".qty").addEventListener("change", (e) => {
      item.qty = Math.max(1, parseInt(e.target.value) || 1);
    });
    const rar = li.querySelector(".rar");
    if (rar) rar.addEventListener("change", (e) => { item.rarity = e.target.value; });
    const lang = li.querySelector(".lang");
    if (lang) lang.addEventListener("change", (e) => { item.lang = e.target.value; });
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
    rarity: it.rarity || null, lang: it.lang || null,
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
  const bits = [c.collector_number, c.rarity, c.lang].filter(Boolean).join("・");
  return `${bits}${bits ? " " : ""}×${c.qty}`;
}

function renderCompare(data) {
  const total = data.wishlist.length;
  const complete = data.sellers.filter((s) => s.complete);
  $("#compareStatus").textContent = complete.length
    ? `找到 ${complete.length} 位賣家可一次湊齊全部 ${total} 張卡！`
    : `沒有賣家能一次湊齊全部 ${total} 張，以下依覆蓋數排序。`;

  const box = $("#compareResults");
  box.innerHTML = "";

  for (const s of data.sellers) {
    const div = document.createElement("div");
    div.className = "seller-block" + (s.complete ? " complete" : "");
    const covClass = s.complete ? "full" : "part";
    const rows = s.covered.map((c) => `
      <tr>
        <td>${c.card_name}<br><small>${wantDesc(c)}</small></td>
        <td><a href="${c.listing.url}" target="_blank" rel="noopener">${c.listing.title}</a></td>
        <td><span class="conf ${c.listing.confidence}">${confLabel[c.listing.confidence]}</span></td>
        <td>${fmt(c.listing.price)}</td>
      </tr>`).join("");
    div.innerHTML = `
      <div class="seller-head">
        <span>賣家 <a href="https://www.ruten.com.tw/store/${s.seller_id}" target="_blank" rel="noopener">#${s.seller_id}</a></span>
        <span class="cov ${covClass}">${s.complete ? "✅ 全齊" : `覆蓋 ${s.covered_count}/${s.total_count} 張`}</span>
        <span class="price">${fmt(s.total)} <small>（卡 ${fmt(s.subtotal)} + 運 ${fmt(s.shipping)}）</small></span>
      </div>
      <table class="listing-table">
        <tr><th>卡片</th><th>露天商品</th><th>比對信心</th><th>單價</th></tr>${rows}
      </table>
      ${s.missing.length ? `<p class="missing-line">缺：${s.missing.map((m) => `${m.card_name}${m.rarity ? "（" + m.rarity + "）" : ""}`).join("、")}</p>` : ""}`;
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
