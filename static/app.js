// CardBuySearch 前端邏輯
const $ = (sel) => document.querySelector(sel);
const wishlist = new Map(); // card_id -> {card, qty}

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
loadRarities();

// ---------- 搜尋 ----------
async function doSearch() {
  const q = $("#searchInput").value.trim();
  const rarity = $("#raritySelect").value;
  if (!q && !rarity) return;
  const grid = $("#searchResults");
  grid.innerHTML = '<p class="empty"><span class="spinner"></span>搜尋中…</p>';
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&rarity=${encodeURIComponent(rarity)}`);
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

function cardEl(c) {
  const div = document.createElement("div");
  div.className = "card-item";
  const inList = wishlist.has(c.id);
  div.innerHTML = `
    <img src="${c.image_url || ""}" alt="${c.name || ""}">
    <div class="meta">
      <span class="name">${c.name || "（未知）"}</span>
      <span class="sub">${c.set_alpha || ""} ${c.collector_number || ""}</span>
      ${c.rarity ? `<span class="rarity-tag">${c.rarity}</span>` : ""}
    </div>
    <button ${inList ? "disabled" : ""}>${inList ? "已加入" : "＋ 加入清單"}</button>`;
  div.querySelector("button").addEventListener("click", (e) => {
    wishlist.set(c.id, { card: c, qty: 1 });
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
  for (const [id, item] of wishlist) {
    const li = document.createElement("li");
    li.innerHTML = `
      <img src="${item.card.image_url || ""}" alt="">
      <div class="winfo">
        <b>${item.card.name}</b><br>
        <small>${item.card.collector_number || ""} ${item.card.rarity ? "・" + item.card.rarity : ""}</small>
      </div>
      <input class="qty" type="number" min="1" max="9" value="${item.qty}">
      <button class="rm" title="移除">✕</button>`;
    li.querySelector(".qty").addEventListener("change", (e) => {
      item.qty = Math.max(1, parseInt(e.target.value) || 1);
    });
    li.querySelector(".rm").addEventListener("click", () => {
      wishlist.delete(id);
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

  const items = [...wishlist.entries()].map(([id, it]) => ({ card_id: id, qty: it.qty }));
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
const confLabel = { strong: "編號+稀有度符合", weak: "稀有度符合", maybe: "標題未標稀有度" };

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
        <td>${c.card_name}<br><small>${c.collector_number || ""}・${c.rarity || "?"} ×${c.qty}</small></td>
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
      ${s.missing.length ? `<p class="missing-line">缺：${s.missing.map((m) => `${m.card_name}（${m.rarity || "?"}）`).join("、")}</p>` : ""}`;
    box.appendChild(div);
  }

  // 拆買基準
  const sp = data.split_baseline;
  if (sp.items.length) {
    const div = document.createElement("div");
    div.className = "seller-block split-block";
    const rows = sp.items.map((c) => `
      <tr>
        <td>${c.card_name}<br><small>${c.collector_number || ""}・${c.rarity || "?"} ×${c.qty}</small></td>
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
    box.innerHTML = '<p class="empty">露天上找不到符合這些卡片＋稀有度的商品。</p>';
  }
}
