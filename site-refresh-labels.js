(function () {
  const labels = {
    initial: 'Initial',
    heartbeat: '15-minute check',
    'price-change': 'Price changed',
    'stock-change': 'Stock changed'
  };

  window.reasonLabel = function reasonLabel(reason = '') {
    return reason.split(',').map((item) => labels[item] || item || 'Check').join(' + ');
  };

  function relabelExistingRows() {
    document.querySelectorAll('.reason-pill').forEach((pill) => {
      pill.textContent = pill.textContent.replace(/\bDaily check\b/g, '15-minute check');
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    relabelExistingRows();
    const table = document.getElementById('history-table');
    if (!table) return;
    new MutationObserver(relabelExistingRows).observe(table, { childList: true, subtree: true });
  });
}());
