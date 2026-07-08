const state = { chartPoints: [], history: [], latest: null, loadInProgress: false };
const el = (id) => document.getElementById(id);
const money = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' });
const dateTime = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/London' });
const shortDate = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Europe/London' });
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
  if (!Number.isFinite(milliseconds)) return 'Unknown time';
  const minutes = Math.max(0, Math.round(milliseconds / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function refreshRelativeTime() {
  if (!state.latest) return;
  el('checked-badge').textContent = `Checked ${relativeAge(state.latest.checked_at)}`;
  el('footer-updated').textContent = `Last check: ${formatDate(state.latest.checked_at)}`;
}

function renderLatest(latest) {
  state.latest = latest;
  el('product-name').textContent = latest.product_name;
  el('product-link').href = latest.product_url;
  el('current-price').textContent = formatMoney(latest.price);
  el('lowest-price').textContent = formatMoney(latest.lowest_price);
  el('highest-price').textContent = formatMoney(latest.highest_price);
  el('history-count').textContent = Number(latest.history_count || 0).toLocaleString('en-GB');

  const stockBadge = el('stock-badge');
  stockBadge.classList.remove('loading', 'in-stock', 'out-stock');
  if (latest.in_stock === true) {
    stockBadge.textContent = '● In stock';
    stockBadge.classList.add('in-stock');
  } else if (latest.in_stock === false) {
    stockBadge.textContent = '● Out of stock';
    stockBadge.classList.add('out-stock');
  } else {
    stockBadge.textContent = 'Stock status unknown';
  }

  refreshRelativeTime();

  const movement = el('price-movement');
  movement.className = 'movement neutral';
  if (latest.change == null || Number(latest.change) === 0) {
    movement.textContent = latest.previous_price == null ? 'Initial tracked price' : 'No change from the previous record';
  } else if (Number(latest.change) < 0) {
    movement.className = 'movement down';
    movement.textContent = `↓ ${formatMoney(Math.abs(latest.change))} (${Math.abs(Number(latest.change_percent)).toFixed(2)}%) since previous record`;
  } else {
    movement.className = 'movement up';
    movement.textContent = `↑ ${formatMoney(latest.change)} (${Number(latest.change_percent).toFixed(2)}%) since previous record`;
  }

  if (latest.target_price != null) {
    el('alert-rule').textContent = formatMoney(latest.target_price);
    el('alert-detail').textContent = latest.notify_on_any_drop
      ? 'Alert on any drop or when target is reached'
      : 'Alert when the target price is reached';
  } else {
    el('alert-rule').textContent = 'Any drop';
    el('alert-detail').textContent = 'GitHub issue assigned to the owner';
  }
}

function reasonLabel(reason = '') {
  const labels = { initial: 'Initial', heartbeat: 'Daily check', 'price-change': 'Price changed', 'stock-change': 'Stock changed' };
  return reason.split(',').map((item) => labels[item] || item || 'Check').join(' + ');
}

function stockCell(value) {
  if (value === true) return '<span class="stock-dot yes"></span>In stock';
  if (value === false) return '<span class="stock-dot no"></span>Out of stock';
  return '<span class="stock-dot unknown"></span>Unknown';
}

function renderTable(history) {
  const rows = [...history].reverse().slice(0, 12);
  el('history-table').innerHTML = rows.length
    ? rows.map((item) => `
      <tr>
        <td>${formatDate(item.timestamp)}</td>
        <td class="price-cell">${formatMoney(item.price)}</td>
        <td>${stockCell(item.in_stock)}</td>
        <td><span class="reason-pill">${reasonLabel(item.reason)}</span></td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="empty-cell">No price history has been recorded yet.</td></tr>';
}

function drawChart(history) {
  const canvas = el('price-chart');
  const wrapper = canvas.parentElement;
  const width = Math.max(300, wrapper.clientWidth);
  const height = Math.max(220, wrapper.clientHeight);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const points = history.map((item) => ({ date: new Date(item.timestamp), price: Number(item.price) }))
    .filter((item) => Number.isFinite(item.price) && !Number.isNaN(item.date.getTime()));
  state.chartPoints = [];

  const padding = { top: 20, right: 22, bottom: 40, left: 65 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  if (!points.length) {
    ctx.fillStyle = '#8e95a8';
    ctx.font = '13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No chart data yet', width / 2, height / 2);
    return;
  }

  const prices = points.map((point) => point.price);
  let min = Math.min(...prices);
  let max = Math.max(...prices);
  const spread = max - min;
  const buffer = spread === 0 ? Math.max(5, max * .03) : spread * .18;
  min -= buffer;
  max += buffer;

  const startTime = points[0].date.getTime();
  const endTime = points[points.length - 1].date.getTime();
  const timeSpread = Math.max(1, endTime - startTime);
  const xFor = (date) => points.length === 1 ? padding.left + plotWidth / 2 : padding.left + ((date.getTime() - startTime) / timeSpread) * plotWidth;
  const yFor = (price) => padding.top + ((max - price) / (max - min)) * plotHeight;

  ctx.font = '11px Inter, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 1;

  for (let i = 0; i <= 4; i += 1) {
    const y = padding.top + (plotHeight / 4) * i;
    const value = max - ((max - min) / 4) * i;
    ctx.strokeStyle = 'rgba(255,255,255,.055)';
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
    ctx.fillStyle = '#747b8e';
    ctx.textAlign = 'right';
    ctx.fillText(money.format(value), padding.left - 10, y);
  }

  const labelCount = Math.min(4, points.length);
  for (let i = 0; i < labelCount; i += 1) {
    const index = labelCount === 1 ? 0 : Math.round((points.length - 1) * (i / (labelCount - 1)));
    const x = xFor(points[index].date);
    ctx.fillStyle = '#747b8e';
    ctx.textAlign = i === 0 ? 'left' : i === labelCount - 1 ? 'right' : 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(shortDate.format(points[index].date), x, height - 24);
  }

  const coordinates = points.map((point) => ({ x: xFor(point.date), y: yFor(point.price), ...point }));
  state.chartPoints = coordinates;

  const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, 'rgba(159,122,234,.32)');
  gradient.addColorStop(1, 'rgba(159,122,234,.01)');
  ctx.beginPath();
  coordinates.forEach((point, index) => index === 0 ? ctx.moveTo(point.x, point.y) : ctx.lineTo(point.x, point.y));
  ctx.lineTo(coordinates[coordinates.length - 1].x, height - padding.bottom);
  ctx.lineTo(coordinates[0].x, height - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  coordinates.forEach((point, index) => index === 0 ? ctx.moveTo(point.x, point.y) : ctx.lineTo(point.x, point.y));
  ctx.strokeStyle = '#c4a7ff';
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.shadowColor = 'rgba(196,167,255,.35)';
  ctx.shadowBlur = 12;
  ctx.stroke();
  ctx.shadowBlur = 0;

  coordinates.forEach((point) => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, coordinates.length === 1 ? 4.5 : 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#f4edff';
    ctx.fill();
    ctx.strokeStyle = '#8c67d8';
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
    const nearest = state.chartPoints.reduce((best, point) => Math.abs(point.x - mouseX) < Math.abs(best.x - mouseX) ? point : best);
    tooltip.hidden = false;
    tooltip.style.left = `${nearest.x}px`;
    tooltip.style.top = `${nearest.y}px`;
    tooltip.innerHTML = `<strong>${formatMoney(nearest.price)}</strong><span>${formatDate(nearest.date)}</span>`;
  });
  canvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });
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
    state.history = history;
    renderLatest(latest);
    renderTable(history);
    drawChart(history);
    el('error-banner').hidden = true;
  } catch (error) {
    console.error(error);
    if (!state.latest) {
      el('error-banner').hidden = false;
      el('stock-badge').textContent = 'Data unavailable';
      el('stock-badge').classList.remove('loading');
    }
  } finally {
    state.loadInProgress = false;
  }
}

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => drawChart(state.history), 120);
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') loadTracker();
});

setupTooltip();
loadTracker();
setInterval(loadTracker, DATA_REFRESH_INTERVAL_MS);
setInterval(refreshRelativeTime, 60_000);
