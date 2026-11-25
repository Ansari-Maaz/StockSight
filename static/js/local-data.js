/* StockSight — shared local-storage helpers (no account, no server state). */
(function () {
  'use strict';

  var KEYS = {
    positions: 'mm-positions',
    watchlist: 'mm-watchlist',
    alerts: 'mm-alerts'
  };

  function read(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  function normaliseSymbol(symbol) {
    return String(symbol || '').trim().toUpperCase();
  }

  function getPositions() {
    var items = read(KEYS.positions, []);
    return Array.isArray(items) ? items : [];
  }
  function setPositions(items) { write(KEYS.positions, items); }

  function getWatchlist() {
    var items = read(KEYS.watchlist, []);
    return Array.isArray(items) ? items.map(normaliseSymbol) : [];
  }
  function setWatchlist(items) {
    var unique = [];
    items.map(normaliseSymbol).forEach(function (symbol) {
      if (symbol && unique.indexOf(symbol) === -1) { unique.push(symbol); }
    });
    write(KEYS.watchlist, unique);
    renderWatchlist();
    syncWatchButtons();
  }
  function toggleWatch(symbol) {
    symbol = normaliseSymbol(symbol);
    if (!symbol) { return false; }
    var list = getWatchlist();
    var index = list.indexOf(symbol);
    if (index === -1) { list.push(symbol); } else { list.splice(index, 1); }
    setWatchlist(list);
    return index === -1;
  }

  function getAlerts() {
    var items = read(KEYS.alerts, []);
    return Array.isArray(items) ? items : [];
  }
  function setAlerts(items) { write(KEYS.alerts, items); updateAlertCount(); }

  function fetchQuotes(symbols) {
    var list = (symbols || []).map(normaliseSymbol).filter(Boolean).slice(0, 50);
    if (!list.length) { return Promise.resolve([]); }
    return fetch('/api/quotes/?symbols=' + encodeURIComponent(list.join(',')), {
      credentials: 'same-origin'
    })
      .then(function (response) {
        if (!response.ok) { throw new Error('quotes unavailable'); }
        return response.json();
      })
      .then(function (payload) { return (payload && payload.quotes) || []; })
      .catch(function () { return []; });
  }

  function toast(message, kind) {
    var stack = document.querySelector('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      document.body.appendChild(stack);
    }
    var el = document.createElement('div');
    el.className = 'toast toast-' + (kind || 'info');
    el.setAttribute('role', 'status');
    el.textContent = message;
    stack.appendChild(el);
    window.setTimeout(function () {
      el.classList.add('leaving');
      window.setTimeout(function () {
        if (el.parentNode) { el.parentNode.removeChild(el); }
      }, 230);
    }, 3200);
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function renderWatchlist() {
    var panel = document.getElementById('myWatchlistPanel');
    var container = document.getElementById('myWatchlist');
    if (!panel || !container) { return; }
    var list = getWatchlist();
    panel.hidden = !list.length;
    container.innerHTML = list.map(function (symbol) {
      return '<span class="local-chip">' +
        '<a href="/dashboard/?symbol=' + encodeURIComponent(symbol) + '">' + esc(symbol) + '</a>' +
        '<button type="button" data-unwatch="' + esc(symbol) + '" aria-label="Remove ' + esc(symbol) + '">×</button>' +
        '</span>';
    }).join('');
  }

  function syncWatchButtons() {
    var list = getWatchlist();
    document.querySelectorAll('[data-watch]').forEach(function (button) {
      var symbol = normaliseSymbol(button.getAttribute('data-watch'));
      var active = list.indexOf(symbol) !== -1;
      button.classList.toggle('active', active);
      button.textContent = active ? '★ Watching' : '☆ Watch';
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
      button.title = active ? 'Remove from your watchlist' : 'Add to your watchlist';
    });
  }

  function updateAlertCount() {
    var badge = document.getElementById('alertCount');
    if (!badge) { return; }
    var triggered = getAlerts().filter(function (alert) { return alert.triggered; }).length;
    badge.textContent = String(triggered);
    badge.hidden = !triggered;
  }

  function bindGlobalEvents() {
    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) { return; }
      var unwatch = target.closest('[data-unwatch]');
      if (unwatch) {
        toggleWatch(unwatch.getAttribute('data-unwatch'));
        toast('Removed from your watchlist', 'info');
        return;
      }
      var watch = target.closest('[data-watch]');
      if (watch) {
        var added = toggleWatch(watch.getAttribute('data-watch'));
        toast(added ? 'Added to your watchlist' : 'Removed from your watchlist', 'success');
      }
    });
  }

  function init() {
    renderWatchlist();
    syncWatchButtons();
    updateAlertCount();
    bindGlobalEvents();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.StockSightLocal = {
    getPositions: getPositions,
    setPositions: setPositions,
    getWatchlist: getWatchlist,
    setWatchlist: setWatchlist,
    toggleWatch: toggleWatch,
    getAlerts: getAlerts,
    setAlerts: setAlerts,
    fetchQuotes: fetchQuotes,
    normaliseSymbol: normaliseSymbol,
    toast: toast,
    esc: esc
  };
})();
