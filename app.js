const state = {
  latest: null,
  history: {},
  selectedId: null,
  filter: 'all',
  chartPoints: [],
  loadInProgress: false
};

const el = (id) => document.getElementById(id);
const money = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' });
const dateTime = new Intl.DateTimeFormat('en-GB', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Europe/London'
});
const shortDate = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'Europe/London'
});
const DATA_REFRESH_INTERVAL_MS = 60_000;

function formatMoney(value) {
  return Number.isFinite(Number(value)) ? money.format(Number(value)) : '—';
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown' : dateTime.format(date);
}

function relativeAge(value) {
  const milliseconds = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(milliseconds)) return 'unknown time';
  const minutes = Math.max(0, Math.round(milliseconds / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function stockLabel(value) {
  if (value === true) return 'In stock';
  if (value === false) return 'Out of stock';
  return 'Unknown';
}

function stockClass(value) {
  if (value === true) return 'in-stock';
  if (value === false) return 'out-stock';
  return 'unknown-stock';
}

function reasonLabel(reason = '') {
  const labels = {
    initial: 'Initial',
    heartbeat: '15-minute check',
    'price-change': 'Price changed',
    'stock-change': 'Stock changed',
    'basket-snapshot': 'Basket snapshot'
  };
  return reason.split(',').map((item) => labels[item] || item || 'Check').join(' + ');
}

function refreshRelativeTime() {
  if (!state.latest) return;
  el('checked-badge').textContent = `Checked ${relativeAge(state.latest.generated_at)}`;
  el('footer-updated').textContent = `Last generated: ${formatDate(state.latest.generated_at)}`;
}

function renderSummary() {
  const basket = state.latest.basket || {};
  el('basket-subtotal').textContent = formatMoney(basket.selected_subtotal);
  el('basket-original').textContent = formatMoney(basket.selected_original_total);
  el('basket-savings').textContent = formatMoney(basket.selected_savings);
  el('basket-saving').textContent = `${formatMoney(basket.selected_savings)} below the displayed original total`;
  el('basket-items').textContent = Number(basket.selected_items || 0).toLocaleString('en-GB');
  el('saved-items').textContent = Number(basket.saved_out_of_stock_items || 0).toLocaleString('en-GB');
  el('product-count').textContent = Number(state.latest.product_count || 0).toLocaleString('en-GB');
  el('failed-checks').textContent = Number(state.latest.failed_checks || 0).toLocaleString('en-GB');

  const health = el('health-badge');
  health.className = 'badge';
  if (Number(state.latest.failed_checks || 0) === 0) {
    health.textContent = '● All product checks healthy';
    health.classList.add('in-stock');
  } else {
    health.textContent = `${state.latest.failed_checks} check${state.latest.failed_checks === 1 ? '' : 's'} using last known price`;
    health.classList.add('warning');
  }
  refreshRelativeTime();
}

function productMatchesFilter(product) {
  if (state.filter === 'all') return true;
  return product.basket_status === state.filter;
}

function movementMarkup(product) {
  const change = Number(product.change);
  if (!Number.isFinite(change) || change === 0) {
    return '<span class="card-movement neutral">No recorded change</span>';
  }
  if (change < 0) {
    return `<span class="card-movement down">↓ ${formatMoney(Math.abs(change))}</span>`;
  }
  return `<span class="card-movement up">↑ ${formatMoney(change)}</span>`;
}

function renderProducts() {
  const products = state.latest.products || [];
  const visible = products.filter(productMatchesFilter);
  const grid = el('product-grid');

  if (!visible.length) {
    grid.innerHTML = '<div class="loading-card">No products match this filter.</div>';
    return;
  }

  grid.innerHTML = visible.map((product) => {
    const selected = product.id === state.selectedId ? ' selected' : '';
    const image = product.image_url
      ? `<img src="${escapeHtml(product.image_url)}" alt="" loading="lazy">`
      : `<span class="product-placeholder">${escapeHtml((product.category || '£').slice(0, 1))}</span>`;
    const basketLine = product.basket_status === 'selected'
      ? `<div class="basket-line"><span>Basket</span><strong>${formatMoney(product.basket_price)}</strong></div>`
      : product.basket_status === 'out-of-stock'
        ? `<div class="basket-line unavailable"><span>Saved item</span><strong>${formatMoney(product.basket_price)}</strong></div>`
        : '<div class="basket-line muted-line"><span>Not in Bambu basket</span></div>';
    const warning = product.check_error ? '<span class="check-warning" title="Latest live check failed">!</span>' : '';

    return `
      <button class="product-card${selected}" data-product-id="${escapeHtml(product.id)}" type="button">
        <div class="product-image">${image}${warning}</div>
        <div class="product-card-body">
          <div class="product-card-top">
            <span class="category">${escapeHtml(product.category || 'Product')}</span>
            <span class="stock-chip ${stockClass(product.in_stock)}">${stockLabel(product.in_stock)}</span>
          </div>
          <h3>${escapeHtml(product.product_name)}</h3>
          <p>${escapeHtml(product.variant || '')}</p>
          <div class="store-price">
            <span>Store price</span>
            <strong>${formatMoney(product.price)}</strong>
          </div>
          ${basketLine}
          ${movementMarkup(product)}
        </div>
      </button>`;
  }).join('');

  grid.querySelectorAll('[data-product-id]').forEach((button) => {
    button.addEventListener('click', () => selectProduct(button.dataset.productId));
  });
}

function stockCell(value) {
  if (value === true) return '<span class="stock-dot yes"></span>In stock';
  if (value === false) return '<span class="stock-dot no"></span>Out of stock';
  return '<span class="stock-dot unknown"></span>Unknown';
}

function renderTable(product) {
  const history = state.history[product.id] || [];
  const rows = [...history].reverse().slice(0, 14);
  el('activity-title').textContent = `${product.product_name} checks`;
  el('history-table').innerHTML = rows.length
    ? rows.map((item) => `
      <tr>
        <td>${formatDate(item.timestamp)}</td>
        <td class="price-cell">${formatMoney(item.price)}</td>
        <td>${stockCell(item.in_stock)}</td>
        <td><span class="reason-pill">${escapeHtml(reasonLabel(item.reason))}</span></td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="empty-cell">No price history has been recorded yet.</td></tr>';
}

function renderDetail(product) {
  el('detail-name').textContent = product.product_name;
  el('detail-variant').textContent = product.variant || '';
  el('detail-eyebrow').textContent = `${product.retailer || 'RETAILER'} · ${product.sku || product.category || 'PRODUCT'}`.toUpperCase();
  el('detail-price').textContent = formatMoney(product.price);
  el('detail-basket-price').textContent = product.basket_status === 'none' ? 'Not in basket' : formatMoney(product.basket_price);
  el('detail-lowest').textContent = formatMoney(product.lowest_price);
  el('detail-stock').textContent = stockLabel(product.in_stock);
  el('detail-link').href = product.product_url;
  el('chart-title').textContent = `${product.product_name} store price`;

  const image = el('detail-image');
  if (product.image_url) {
    image.className = 'detail-image';
    image.innerHTML = `<img src="${escapeHtml(product.image_url)}" alt="">`;
  } else {
    image.className = 'detail-image placeholder';
    image.textContent = '£';
  }

  const warning = el('detail-warning');
  if (product.check_error) {
    warning.hidden = false;
    warning.textContent = `The latest live product-page check was unavailable, so the last known price is shown. ${product.check_error}`;
  } else if (product.basket_status === 'selected' && Number(product.basket_price) !== Number(product.price)) {
    warning.hidden = false;
    warning.textContent = `The uploaded basket price was ${formatMoney(product.basket_price)}; the separate store-page price is ${formatMoney(product.price)}. Basket discounts can depend on the full bundle.`;
  } else if (product.basket_status === 'out-of-stock') {
    warning.hidden = false;
    warning.textContent = 'This saved basket item was out of stock in the uploaded basket and was not included in the £1,001.59 purchasable subtotal.';
  } else {
    warning.hidden = true;
    warning.textContent = '';
  }

  renderTable(product);
  drawChart(state.history[product.id] || []);
}

function selectProduct(productId) {
  const product = (state.latest.products || []).find((item) => item.id === productId);
  if (!product) return;
  state.selectedId = productId;
  renderProducts();
  renderDetail(product);
}

function drawChart(history) {
  const canvas = el('price-chart');
  const wrapper = canvas.parentElement;
  const width = Math.max(300, wrapper.clientWidth);
  const height = Math.max(230, wrapper.clientHeight);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const points = history
    .map((item) => ({ date: new Date(item.timestamp), price: Number(item.price) }))
    .filter((item) => Number.isFinite(item.price) && !Number.isNaN(item.date.getTime()));
  state.chartPoints = [];

  const padding = { top: 20, right: 22, bottom: 40, left: 65 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  if (!points.length) {
    ctx.fillStyle = '#8e9a94';
    ctx.font = '13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No chart data yet', width / 2, height / 2);
    return;
  }

  const prices = points.map((point) => point.price);
  let min = Math.min(...prices);
  let max = Math.max(...prices);
  const spread = max - min;
  const buffer = spread === 0 ? Math.max(1, max * .03) : spread * .18;
  min -= buffer;
  max += buffer;

  const startTime = points[0].date.getTime();
  const endTime = points[points.length - 1].date.getTime();
  const timeSpread = Math.max(1, endTime - startTime);
  const xFor = (date) => points.length === 1
    ? padding.left + plotWidth / 2
    : padding.left + ((date.getTime() - startTime) / timeSpread) * plotWidth;
  const yFor = (price) => padding.top + ((max - price) / (max - min)) * plotHeight;

  ctx.font = '11px Inter, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 1;

  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight / 4) * index;
    const value = max - ((max - min) / 4) * index;
    ctx.strokeStyle = 'rgba(255,255,255,.06)';
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillStyle = '#738078';
    ctx.textAlign = 'right';
    ctx.fillText(money.format(value), padding.left - 10, y);
  }

  const labelCount = Math.min(4, points.length);
  for (let index = 0; index < labelCount; index += 1) {
    const pointIndex = labelCount === 1 ? 0 : Math.round((points.length - 1) * (index / (labelCount - 1)));
    const x = xFor(points[pointIndex].date);
    ctx.fillStyle = '#738078';
    ctx.textAlign = index === 0 ? 'left' : index === labelCount - 1 ? 'right' : 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(shortDate.format(points[pointIndex].date), x, height - 24);
  }

  const coordinates = points.map((point) => ({ x: xFor(point.date), y: yFor(point.price), ...point }));
  state.chartPoints = coordinates;

  const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, 'rgba(73, 220, 143, .28)');
  gradient.addColorStop(1, 'rgba(73, 220, 143, .01)');
  ctx.beginPath();
  coordinates.forEach((point, index) => index === 0 ? ctx.moveTo(point.x, point.y) : ctx.lineTo(point.x, point.y));
  ctx.lineTo(coordinates[coordinates.length - 1].x, height - padding.bottom);
  ctx.lineTo(coordinates[0].x, height - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  coordinates.forEach((point, index) => index === 0 ? ctx.moveTo(point.x, point.y) : ctx.lineTo(point.x, point.y));
  ctx.strokeStyle = '#76e8aa';
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.shadowColor = 'rgba(118,232,170,.35)';
  ctx.shadowBlur = 12;
  ctx.stroke();
  ctx.shadowBlur = 0;

  coordinates.forEach((point) => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, coordinates.length === 1 ? 4.5 : 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#ecfff4';
    ctx.fill();
    ctx.strokeStyle = '#2f9b65';
    ctx.lineWidth = 2;
    ctx.stroke();
  });
}

function setupTooltip() {
  const canvas = el('price-chart');
  const tooltip = el('chart-tooltip');
  canvas.addEventListener('mousemove', (event) => {
    if (!state.chartPoints.length) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const nearest = state.chartPoints.reduce((best, point) =>
      Math.abs(point.x - mouseX) < Math.abs(best.x - mouseX) ? point : best
    );
    tooltip.hidden = false;
    tooltip.style.left = `${nearest.x}px`;
    tooltip.style.top = `${nearest.y}px`;
    tooltip.innerHTML = `<strong>${formatMoney(nearest.price)}</strong><span>${formatDate(nearest.date)}</span>`;
  });
  canvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });
}

function setupFilters() {
  document.querySelectorAll('.filter').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll('.filter').forEach((item) => item.classList.toggle('active', item === button));
      renderProducts();
    });
  });
}

async function loadTracker() {
  if (state.loadInProgress) return;
  state.loadInProgress = true;
  const cacheBust = `?v=${Date.now()}`;

  try {
    const [latestResponse, historyResponse] = await Promise.all([
      fetch(`data/latest.json${cacheBust}`, { cache: 'no-store' }),
      fetch(`data/price-history.json${cacheBust}`, { cache: 'no-store' })
    ]);
    if (!latestResponse.ok || !historyResponse.ok) throw new Error('Tracker data request failed');
    const [latest, history] = await Promise.all([latestResponse.json(), historyResponse.json()]);
    state.latest = latest;
    state.history = history;
    if (!state.selectedId || !latest.products.some((item) => item.id === state.selectedId)) {
      state.selectedId = latest.products.find((item) => item.basket_status === 'selected')?.id || latest.products[0]?.id;
    }
    renderSummary();
    renderProducts();
    selectProduct(state.selectedId);
    el('error-banner').hidden = true;
  } catch (error) {
    console.error(error);
    el('error-banner').hidden = false;
    el('checked-badge').textContent = 'Data unavailable';
    el('checked-badge').classList.remove('loading');
  } finally {
    state.loadInProgress = false;
  }
}

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!state.latest || !state.selectedId) return;
    drawChart(state.history[state.selectedId] || []);
  }, 120);
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') loadTracker();
});

setupFilters();
setupTooltip();
loadTracker();
setInterval(loadTracker, DATA_REFRESH_INTERVAL_MS);
setInterval(refreshRelativeTime, 60_000);
