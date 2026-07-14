(() => {
  'use strict';

  const REPOSITORY = 'Minecraftman04/Price-Tracker';
  const ISSUE_URL = `https://github.com/${REPOSITORY}/issues/new`;
  let pendingReset = null;
  let observer = null;
  let enhancingCards = false;

  function escapeText(value = '') {
    return String(value).replace(/\s+/g, ' ').trim();
  }

  function buildIssueUrl(request) {
    const isAll = request.scope === 'all';
    const title = isAll
      ? '[Clear price history] All products'
      : `[Clear price history] ${request.productName}`;
    const body = [
      'action: clear-price-history',
      `scope: ${request.scope}`,
      ...(isAll ? [] : [
        `product_id: ${request.productId}`,
        `product_name: ${request.productName}`,
      ]),
      '',
      'This owner-authorised reset request was created from the Basket Price Tracker dashboard.',
      'A current-price baseline will be retained so the dashboard can continue displaying the product immediately.',
    ].join('\n');

    const query = new URLSearchParams({ title, body });
    return `${ISSUE_URL}?${query.toString()}`;
  }

  function ensureDialog() {
    let dialog = document.getElementById('history-clear-dialog');
    if (dialog) return dialog;

    dialog = document.createElement('dialog');
    dialog.id = 'history-clear-dialog';
    dialog.className = 'history-dialog';
    dialog.innerHTML = `
      <form method="dialog">
        <span class="eyebrow">CLEAR PRICE HISTORY</span>
        <h2 id="history-dialog-title">Clear recorded history?</h2>
        <p>This removes the stored chart and table history while retaining one current-price baseline.</p>
        <p id="history-dialog-target" class="history-dialog-target"></p>
        <p class="history-dialog-note">For security, GitHub will open a pre-filled request. Review it and click <strong>Submit new issue</strong> while signed in as the repository owner. Requests from anyone else are rejected automatically.</p>
        <div class="history-dialog-actions">
          <button class="history-dialog-cancel" value="cancel">Cancel</button>
          <button id="history-dialog-confirm" class="history-dialog-confirm" type="button">Continue to GitHub</button>
        </div>
      </form>`;
    document.body.append(dialog);

    dialog.querySelector('#history-dialog-confirm').addEventListener('click', () => {
      if (!pendingReset) return;
      window.open(buildIssueUrl(pendingReset), '_blank', 'noopener,noreferrer');
      dialog.close();
      pendingReset = null;
    });
    dialog.addEventListener('close', () => {
      if (dialog.returnValue === 'cancel') pendingReset = null;
    });
    return dialog;
  }

  function requestReset(request) {
    pendingReset = request;
    const dialog = ensureDialog();
    const all = request.scope === 'all';
    dialog.querySelector('#history-dialog-title').textContent = all
      ? 'Clear all recorded price history?'
      : 'Clear this item’s price history?';
    dialog.querySelector('#history-dialog-target').textContent = all
      ? 'All tracked products'
      : request.productName;

    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
      return;
    }

    const confirmed = window.confirm(
      `${all ? 'Clear all recorded price history' : `Clear price history for ${request.productName}`}?\n\n` +
      'A current-price baseline will be retained. GitHub will open so you can submit the secure owner request.'
    );
    if (confirmed) window.open(buildIssueUrl(request), '_blank', 'noopener,noreferrer');
    pendingReset = null;
  }

  function ensureGlobalControl() {
    const filterRow = document.querySelector('.catalogue .filter-row');
    if (!filterRow || document.getElementById('clear-all-history')) return;

    let controls = filterRow.parentElement.querySelector('.history-catalogue-controls');
    if (!controls) {
      controls = document.createElement('div');
      controls.className = 'history-catalogue-controls';
      filterRow.before(controls);
      controls.append(filterRow);
    }

    const button = document.createElement('button');
    button.id = 'clear-all-history';
    button.className = 'history-clear-all';
    button.type = 'button';
    button.textContent = 'Clear all price history';
    button.addEventListener('click', () => requestReset({ scope: 'all' }));
    controls.append(button);
  }

  function createCardClearButton(card) {
    const productId = escapeText(card.dataset.productId);
    const productName = escapeText(card.querySelector('h3')?.textContent || productId || 'Selected product');
    const button = document.createElement('button');
    button.className = 'history-card-clear';
    button.type = 'button';
    button.dataset.clearHistoryId = productId;
    button.innerHTML = '<span aria-hidden="true">↺</span>Clear price history';
    button.setAttribute('aria-label', `Clear price history for ${productName}`);
    button.addEventListener('click', () => requestReset({
      scope: 'product',
      productId,
      productName,
    }));
    return button;
  }

  function enhanceProductCards() {
    const grid = document.getElementById('product-grid');
    if (!grid || enhancingCards) return;
    enhancingCards = true;
    observer?.disconnect();

    [...grid.children].forEach((child) => {
      if (!(child instanceof HTMLElement) || !child.classList.contains('product-card')) return;
      const shell = document.createElement('div');
      shell.className = 'history-card-shell';
      child.before(shell);
      shell.append(child, createCardClearButton(child));
    });

    observer?.observe(grid, { childList: true });
    enhancingCards = false;
  }

  function setup() {
    ensureGlobalControl();
    ensureDialog();
    const grid = document.getElementById('product-grid');
    if (!grid) return;
    observer = new MutationObserver(() => queueMicrotask(enhanceProductCards));
    observer.observe(grid, { childList: true });
    enhanceProductCards();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup, { once: true });
  } else {
    setup();
  }
})();
