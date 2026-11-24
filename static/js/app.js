/* ==========================================================================
   StockSight — front-end behaviour (vanilla JS, global Chart.js only)
   Reads window.MM_CHART_DATA, mounted on DOMContentLoaded.
   ========================================================================== */
(function () {
  'use strict';

  /* ── Small utilities ──────────────────────────────────────────────── */

  function getCookie(name) {
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var i = 0; i < parts.length; i += 1) {
      var part = parts[i].trim();
      if (part.indexOf(name + '=') === 0) {
        try { return decodeURIComponent(part.slice(name.length + 1)); }
        catch (e) { return part.slice(name.length + 1); }
      }
    }
    return '';
  }

  function hexToRgba(color, alpha) {
    var c = String(color || '').trim();
    if (!c) { return 'rgba(148, 163, 184, ' + alpha + ')'; }
    if (c.charAt(0) !== '#') { return c; } // already an rgba()/named colour
    var hex = c.slice(1);
    if (hex.length === 3) {
      hex = hex.charAt(0) + hex.charAt(0) + hex.charAt(1) + hex.charAt(1) + hex.charAt(2) + hex.charAt(2);
    }
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) { return 'rgba(148, 163, 184, ' + alpha + ')'; }
    var r = parseInt(hex.slice(0, 2), 16);
    var g = parseInt(hex.slice(2, 4), 16);
    var b = parseInt(hex.slice(4, 6), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
  }

  /* Read a theme token from CSS so charts follow the active palette. */
  function themeVar(name, fallback) {
    var value = '';
    try { value = getComputedStyle(document.documentElement).getPropertyValue(name); } catch (e) {}
    return (value && value.trim()) || fallback || '';
  }

  var LEGACY_COLORS = {
    '#4f46e5': '--chart-1', '#22d3ee': '--chart-1',
    '#059669': '--chart-2', '#34d399': '--chart-2',
    '#7c3aed': '--chart-3', '#a78bfa': '--chart-3'
  };
  function chartColor(color, fallbackVar) {
    if (!color) { return themeVar(fallbackVar || '--chart-1', '#4f46e5'); }
    var key = LEGACY_COLORS[String(color).toLowerCase()];
    return key ? themeVar(key, color) : color;
  }

  function compactNumber(value) {
    var n = Number(String(value).replace(/,/g, ''));
    if (!isFinite(n)) { return null; }
    var sign = n < 0 ? '-' : '';
    var abs = Math.abs(n);
    if (abs >= 1e12) { return sign + (abs / 1e12).toFixed(2) + 'T'; }
    if (abs >= 1e9)  { return sign + (abs / 1e9).toFixed(2) + 'B'; }
    if (abs >= 1e6)  { return sign + (abs / 1e6).toFixed(2) + 'M'; }
    if (abs >= 1e3)  { return sign + (abs / 1e3).toFixed(1) + 'K'; }
    return String(Math.round(n));
  }

  /* ── Toast system ─────────────────────────────────────────────────── */

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
    }, 3600);
  }

  /* ── Chart helpers ────────────────────────────────────────────────── */

  function areaGradient(color) {
    return function (context) {
      var chart = context && context.chart;
      if (!chart || !chart.chartArea) { return 'transparent'; }
      var area = chart.chartArea;
      var gradient = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
      gradient.addColorStop(0, hexToRgba(color, 0.22));
      gradient.addColorStop(0.6, hexToRgba(color, 0.06));
      gradient.addColorStop(1, hexToRgba(color, 0.004));
      return gradient;
    };
  }

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 550 },
      interaction: { mode: 'index', intersect: false },
      layout: { padding: { top: 4, right: 6, bottom: 0, left: 0 } },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'end',
          labels: {
            color: themeVar('--chart-legend', '#334155'),
            usePointStyle: true,
            pointStyle: 'circle',
            boxWidth: 7,
            boxHeight: 7,
            padding: 14,
            font: { family: 'Plus Jakarta Sans, system-ui, sans-serif', size: 11, weight: 600 }
          }
        },
        tooltip: {
          backgroundColor: themeVar('--chart-tooltip-bg', '#ffffff'),
          borderColor: themeVar('--chart-tooltip-border', '#e4eaf3'),
          borderWidth: 1,
          titleColor: themeVar('--chart-tooltip-title', '#0f172a'),
          bodyColor: themeVar('--chart-tooltip-body', '#334155'),
          padding: 10,
          cornerRadius: 9,
          titleFont: { family: 'Plus Jakarta Sans, system-ui, sans-serif', size: 11, weight: 700 },
          bodyFont: { family: 'JetBrains Mono, monospace', size: 11 },
          displayColors: true
        }
      },
      scales: {
        x: {
          grid: { color: themeVar('--chart-grid', 'rgba(148,163,184,.18)'), drawTicks: false },
          border: { display: false },
          ticks: { color: themeVar('--chart-tick', '#64748b'), maxTicksLimit: 8, maxRotation: 0, autoSkip: true, font: { family: 'JetBrains Mono, monospace', size: 10 }, padding: 6 }
        },
        y: {
          grid: { color: themeVar('--chart-grid', 'rgba(148,163,184,.18)'), drawTicks: false },
          border: { display: false },
          ticks: { color: themeVar('--chart-tick', '#64748b'), maxTicksLimit: 6, font: { family: 'JetBrains Mono, monospace', size: 10 }, padding: 8 }
        }
      },
      elements: {
        line: { tension: 0.35, borderWidth: 2, borderJoinStyle: 'round' },
        point: { radius: 0, hoverRadius: 4, hitRadius: 10, borderWidth: 2 },
        bar: { borderRadius: 4, borderSkipped: false }
      }
    };
  }

  function normaliseDatasets(datasets, type) {
    return (datasets || []).map(function (ds) {
      var d = Object.assign({}, ds);
      d.borderColor = chartColor(d.borderColor, '--chart-1');
      if (d.backgroundColor && typeof d.backgroundColor === 'string') {
        d.backgroundColor = chartColor(d.backgroundColor, '--chart-1');
      }
      if (d.fill === true) {
        d.backgroundColor = areaGradient(d.borderColor || themeVar('--chart-1', '#4f46e5'));
      }
      if (type === 'line') {
        if (typeof d.tension !== 'number') { d.tension = 0.35; }
        if (typeof d.pointRadius !== 'number') { d.pointRadius = 0; }
        if (typeof d.pointHoverRadius !== 'number') { d.pointHoverRadius = 4; }
        if (typeof d.borderWidth !== 'number') { d.borderWidth = 2; }
      }
      return d;
    });
  }

  var chartRegistry = [];

  function mountChart(canvasId, cfg) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !cfg) { return null; }
    if (typeof Chart === 'undefined') { return null; }
    try {
      var type = cfg.type || 'line';
      var config = {
        type: type,
        data: { labels: cfg.labels || [], datasets: normaliseDatasets(cfg.datasets, type) },
        options: baseOptions()
      };
      if (type === 'bar') {
        config.options.scales.y.beginAtZero = true;
      }
      return new Chart(canvas.getContext('2d'), config);
    } catch (err) {
      if (window.console && console.warn) { console.warn('Chart ' + canvasId + ' failed:', err); }
      return null;
    }
  }

  function renderCharts() {
    chartRegistry.forEach(function (entry) {
      if (entry.chart) {
        try { entry.chart.destroy(); } catch (e) {}
      }
      entry.chart = mountChart(entry.id, entry.factory());
    });
  }

  function buildForecastConfig(raw) {
    var historyDates = raw.history_dates || [];
    var historyClose = (raw.history_close || []).map(Number);
    var dates = raw.dates || [];
    var predictions = (raw.predictions || []).map(Number);
    var labels = historyDates.concat(dates);

    var histData = historyClose.concat(new Array(predictions.length).fill(null));
    var predData = historyClose.map(function () { return null; });
    if (historyClose.length) { predData[historyClose.length - 1] = historyClose[historyClose.length - 1]; }
    predData = predData.concat(predictions);
    var c1 = themeVar('--chart-1', '#4f46e5');
    var c2 = themeVar('--chart-2', '#059669');

    return {
      type: 'line',
      labels: labels,
      datasets: [
        { label: 'Historical close', data: histData, borderColor: c1, backgroundColor: c1, fill: true, borderWidth: 2 },
        { label: 'AI forecast', data: predData, borderColor: c2, backgroundColor: c2, borderDash: [6, 4], borderWidth: 2, fill: false }
      ]
    };
  }

  function initCharts() {
    var data = window.MM_CHART_DATA;
    if (!data || typeof Chart === 'undefined') { return; }
    var map = [
      ['priceChart', 'price'],
      ['volumeChart', 'volume'],
      ['compareChart', 'compare'],
      ['normChart', 'norm'],
      ['detailChart', 'detail'],
      ['detailVolume', 'detailVolume']
    ];
    chartRegistry = [];
    map.forEach(function (pair) {
      if (data[pair[1]]) {
        var key = pair[1];
        chartRegistry.push({ id: pair[0], factory: function () { return data[key]; }, chart: null });
      }
    });
    if (data.forecast) {
      chartRegistry.push({ id: 'forecastChart', factory: function () { return buildForecastConfig(data.forecast); }, chart: null });
    }
    renderCharts();
  }

  /* ── Tables built from chart data ─────────────────────────────────── */

  function buildOhlcTable() {
    var body = document.getElementById('ohlcBody');
    var data = window.MM_CHART_DATA;
    if (!body || !data || !data.ohlc) { return; }
    var o = data.ohlc;
    var labels = o.labels || [];
    var start = Math.max(0, labels.length - 8);
    body.textContent = '';
    for (var i = start; i < labels.length; i += 1) {
      var tr = document.createElement('tr');
      var values = [labels[i], o.open[i], o.high[i], o.low[i], o.close[i]];
      values.forEach(function (v, idx) {
        var td = document.createElement('td');
        td.textContent = (v === null || v === undefined) ? '—' : v;
        if (idx > 0) { td.className = 'num'; }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    }
    if (!body.childNodes.length) {
      var row = document.createElement('tr');
      var cell = document.createElement('td');
      cell.colSpan = 5;
      cell.className = 'muted center';
      cell.textContent = 'No sessions available.';
      row.appendChild(cell);
      body.appendChild(row);
    }
  }

  function buildForecastTable() {
    var body = document.getElementById('forecastBody');
    var data = window.MM_CHART_DATA;
    if (!body || !data || !data.forecast) { return; }
    var f = data.forecast;
    var dates = f.dates || [];
    var prices = (f.predictions || []).map(Number);
    var history = (f.history_close || []).map(Number);
    var lastHistory = history.length ? history[history.length - 1] : null;
    body.textContent = '';

    dates.forEach(function (date, i) {
      var price = prices[i];
      var previous = i > 0 ? prices[i - 1] : lastHistory;
      var change = null;
      if (isFinite(price) && isFinite(previous) && previous !== 0) {
        change = ((price - previous) / previous) * 100;
      }
      var tr = document.createElement('tr');

      var dateCell = document.createElement('td');
      dateCell.textContent = date;
      tr.appendChild(dateCell);

      var priceCell = document.createElement('td');
      priceCell.className = 'num';
      priceCell.textContent = isFinite(price) ? price.toFixed(2) : '—';
      tr.appendChild(priceCell);

      var changeCell = document.createElement('td');
      changeCell.className = 'num';
      if (change === null) {
        changeCell.textContent = '—';
      } else {
        changeCell.textContent = (change > 0 ? '+' : '') + change.toFixed(2) + '%';
        changeCell.classList.add(change > 0 ? 'pos' : (change < 0 ? 'neg' : ''));
      }
      tr.appendChild(changeCell);
      body.appendChild(tr);
    });

    if (!dates.length) {
      var row = document.createElement('tr');
      var cell = document.createElement('td');
      cell.colSpan = 3;
      cell.className = 'muted center';
      cell.textContent = 'No forecast points available.';
      row.appendChild(cell);
      body.appendChild(row);
    }
  }

  /* ── Table / number cosmetics ─────────────────────────────────────── */

  function colourNumericCells() {
    document.querySelectorAll('[data-num]').forEach(function (cell) {
      var raw = cell.textContent.replace(/[%,\s]/g, '').trim();
      if (!raw || raw === '—' || raw === '-') { return; }
      var value = Number(raw);
      if (!isFinite(value)) { return; }
      if (value > 0) { cell.classList.add('pos'); }
      else if (value < 0) { cell.classList.add('neg'); }
    });
  }

  function formatShortNumbers() {
    document.querySelectorAll('[data-shortnum]').forEach(function (el) {
      var formatted = compactNumber(el.textContent.trim());
      if (formatted !== null) { el.textContent = formatted; }
    });
  }

  /* ── Range slider ↔ number input ─────────────────────────────────── */

  function initRangeSync() {
    var range = document.getElementById('daysRange');
    var number = document.getElementById('daysNumber');
    var output = document.querySelector('.field-range .accent-text');
    if (!range || !number) { return; }
    range.addEventListener('input', function () {
      number.value = range.value;
      if (output) { output.textContent = range.value + ' days'; }
    });
    number.addEventListener('input', function () {
      var max = Number(range.max) || 90;
      var value = Math.max(1, Math.min(max, Number(number.value) || 1));
      range.value = value;
      if (output) { output.textContent = value + ' days'; }
    });
  }

  /* ── Debounced global symbol search ──────────────────────────────── */

  function initSymbolSearch() {
    var input = document.getElementById('globalSymbol');
    var list = document.getElementById('globalSymbols');
    if (!input || !list) { return; }
    var timer = null;

    input.addEventListener('input', function () {
      if (timer) { window.clearTimeout(timer); }
      var query = input.value.trim();
      if (query.length < 2) { return; }
      timer = window.setTimeout(function () {
        fetch('/api/search/?q=' + encodeURIComponent(query), { credentials: 'same-origin' })
          .then(function (response) {
            if (!response.ok) { throw new Error('search failed'); }
            return response.json();
          })
          .then(function (payload) {
            var results = (payload && payload.results) || [];
            Array.prototype.forEach.call(list.querySelectorAll('option[data-live]'), function (opt) {
              if (opt.parentNode) { opt.parentNode.removeChild(opt); }
            });
            results.slice(0, 10).forEach(function (item) {
              var option = document.createElement('option');
              option.setAttribute('data-live', '1');
              option.value = item.label || item.Symbol || '';
              option.textContent = item.Name || '';
              list.appendChild(option);
            });
          })
          .catch(function () { /* Search is a progressive enhancement — stay silent. */ });
      }, 260);
    });
  }

  /* ── Refresh button ──────────────────────────────────────────────── */

  var savedLabels = new WeakMap();

  function initRefreshButtons() {
    document.addEventListener('click', function (event) {
      var target = event.target && event.target.closest ? event.target.closest('[data-refresh]') : null;
      if (!target || target.disabled) { return; }
      event.preventDefault();

      if (!savedLabels.has(target)) { savedLabels.set(target, target.innerHTML); }
      var original = savedLabels.get(target);
      var label = target.querySelector('.refresh-label');

      target.disabled = true;
      target.classList.add('is-loading');
      if (label) { label.textContent = 'Refreshing…'; }
      else { target.textContent = 'Refreshing…'; }
      toast('Refreshing market data…', 'info');

      fetch('/api/refresh/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({})
      })
        .then(function (response) {
          if (!response.ok) { throw new Error('HTTP ' + response.status); }
          return response.json();
        })
        .then(function (payload) {
          var results = (payload && payload.results) || [];
          toast('Done — ' + results.length + ' symbol' + (results.length === 1 ? '' : 's') + ' updated', 'success');
          window.setTimeout(function () { window.location.reload(); }, 1100);
        })
        .catch(function (error) {
          toast('Refresh failed: ' + (error && error.message ? error.message : 'unknown error'), 'error');
        })
        .then(function () {
          target.disabled = false;
          target.classList.remove('is-loading');
          target.innerHTML = original;
        });
    });
  }

  /* ── Theme switcher ───────────────────────────────────────────────── */

  function syncThemeButton() {
    var btn = document.getElementById('themeToggle');
    if (!btn) { return; }
    var dark = document.documentElement.dataset.theme === 'dark';
    var label = dark ? 'Switch to light theme' : 'Switch to dark theme';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', label);
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('mm-theme', theme); } catch (e) {}
    syncThemeButton();
    renderCharts();
  }

  function initTheme() {
    syncThemeButton();
    var btn = document.getElementById('themeToggle');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      var current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });
  }

  /* ── Collapsible sidebar ──────────────────────────────────────────── */

  function syncSidebarButton() {
    var btn = document.getElementById('sidebarToggle');
    if (!btn) { return; }
    var collapsed = document.documentElement.classList.contains('sidebar-collapsed');
    var label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute('title', label);
  }

  function initSidebar() {
    syncSidebarButton();
    var btn = document.getElementById('sidebarToggle');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      var root = document.documentElement;
      root.classList.toggle('sidebar-collapsed');
      try {
        localStorage.setItem('mm-sidebar', root.classList.contains('sidebar-collapsed') ? 'collapsed' : 'expanded');
      } catch (e) {}
      syncSidebarButton();
    });
  }

  /* ── Boot ─────────────────────────────────────────────────────────── */

  function boot() {
    initCharts();
    buildOhlcTable();
    buildForecastTable();
    colourNumericCells();
    formatShortNumbers();
    initRangeSync();
    initSymbolSearch();
    initRefreshButtons();
    initTheme();
    initSidebar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
