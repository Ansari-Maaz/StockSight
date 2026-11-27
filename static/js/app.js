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

  function readJsonScript(id) {
    var el = document.getElementById(id);
    if (!el) { return null; }
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
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
      ['detailVolume', 'detailVolume'],
      ['backtestChart', 'backtest']
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

  /* ── Technical indicators (RSI, MACD, overlays) ───────────────────── */

  var indicatorCharts = { rsi: null, macd: null };
  var indicatorState = { sma20: false, sma50: false, ema20: false, bb: false };
  var indicatorTogglesBound = false;

  function getChart(id) {
    for (var i = 0; i < chartRegistry.length; i += 1) {
      if (chartRegistry[i].id === id) { return chartRegistry[i].chart; }
    }
    return null;
  }

  function indicatorColor(token) {
    return themeVar(token, '#6366f1');
  }

  function applyIndicatorOverlays(ind) {
    var chart = getChart('priceChart') || getChart('detailChart');
    if (!chart || !chart.data) { return; }

    chart.data.datasets = chart.data.datasets.filter(function (ds) { return !ds.__indicator; });
    var bandColor = indicatorColor('--dim');
    var overlays = [
      { key: 'sma20', label: 'SMA 20', data: ind.sma20, color: indicatorColor('--amber'), dash: [] },
      { key: 'sma50', label: 'SMA 50', data: ind.sma50, color: indicatorColor('--violet'), dash: [] },
      { key: 'ema20', label: 'EMA 20', data: ind.ema20, color: indicatorColor('--cyan'), dash: [4, 3] },
      { key: 'bb_upper', label: 'Bollinger upper', data: ind.bb_upper, color: bandColor, dash: [3, 3] },
      { key: 'bb_lower', label: 'Bollinger lower', data: ind.bb_lower, color: bandColor, dash: [3, 3],
        fill: '-1', backgroundColor: hexToRgba(bandColor, 0.06) }
    ];

    overlays.forEach(function (def) {
      if (!def.data) { return; }
      chart.data.datasets.push({
        label: def.label,
        data: def.data,
        borderColor: def.color,
        backgroundColor: def.backgroundColor || 'transparent',
        borderWidth: 1.4,
        borderDash: def.dash,
        pointRadius: 0,
        pointHoverRadius: 3,
        fill: def.fill || false,
        tension: 0.25,
        hidden: def.key.indexOf('bb_') === 0 ? !indicatorState.bb : !indicatorState[def.key],
        __indicator: true,
        __key: def.key
      });
    });
    chart.update();
  }

  function applyIndicatorVisibility() {
    var chart = getChart('priceChart') || getChart('detailChart');
    if (chart) {
      chart.data.datasets.forEach(function (ds, index) {
        if (!ds.__indicator) { return; }
        var visible = ds.__key.indexOf('bb_') === 0 ? indicatorState.bb : indicatorState[ds.__key];
        chart.setDatasetVisibility(index, !!visible);
      });
      chart.update();
    }

    document.querySelectorAll('.indicator-toggle').forEach(function (btn) {
      var key = btn.getAttribute('data-indicator');
      var on = key === 'bb' ? indicatorState.bb : indicatorState[key];
      btn.classList.toggle('active', !!on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function buildRsiChart(ind) {
    var canvas = document.getElementById('rsiChart');
    if (!canvas || typeof Chart === 'undefined') { return; }
    if (indicatorCharts.rsi) {
      try { indicatorCharts.rsi.destroy(); } catch (e) {}
    }
    var options = baseOptions();
    options.plugins.legend.display = false;
    options.scales.y.min = 0;
    options.scales.y.max = 100;
    options.scales.y.ticks.stepSize = 25;
    options.plugins.tooltip.filter = function (item) { return item.datasetIndex === 0; };

    var labels = ind.labels || [];
    var overbought = labels.map(function () { return 70; });
    var oversold = labels.map(function () { return 30; });
    indicatorCharts.rsi = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'RSI 14', data: ind.rsi || [], borderColor: indicatorColor('--chart-1'),
            backgroundColor: 'transparent', borderWidth: 1.8, pointRadius: 0, pointHoverRadius: 3,
            fill: false, tension: 0.25 },
          { label: '70', data: overbought, borderColor: hexToRgba(indicatorColor('--rose'), .4),
            borderWidth: 1, borderDash: [4, 4], pointRadius: 0, fill: false },
          { label: '30', data: oversold, borderColor: hexToRgba(indicatorColor('--emerald'), .4),
            borderWidth: 1, borderDash: [4, 4], pointRadius: 0, fill: false }
        ]
      },
      options: options
    });
  }

  function buildMacdChart(ind) {
    var canvas = document.getElementById('macdChart');
    if (!canvas || typeof Chart === 'undefined') { return; }
    if (indicatorCharts.macd) {
      try { indicatorCharts.macd.destroy(); } catch (e) {}
    }
    var options = baseOptions();
    options.scales.y.ticks.maxTicksLimit = 5;
    var positive = hexToRgba(indicatorColor('--emerald'), .45);
    var negative = hexToRgba(indicatorColor('--rose'), .45);
    var histogram = (ind.macd_hist || []).map(function (value) {
      if (value === null || value === undefined) { return 'transparent'; }
      return value >= 0 ? positive : negative;
    });

    indicatorCharts.macd = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: ind.labels || [],
        datasets: [
          { type: 'bar', label: 'Histogram', data: ind.macd_hist || [], backgroundColor: histogram,
            borderColor: histogram, borderWidth: 0, order: 2 },
          { type: 'line', label: 'MACD', data: ind.macd || [], borderColor: indicatorColor('--chart-1'),
            backgroundColor: 'transparent', borderWidth: 1.8, pointRadius: 0, fill: false, order: 1 },
          { type: 'line', label: 'Signal', data: ind.macd_signal || [], borderColor: indicatorColor('--amber'),
            backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 3], pointRadius: 0,
            fill: false, order: 1 }
        ]
      },
      options: options
    });
  }

  function initIndicators() {
    var ind = readJsonScript('mm-indicators');
    if (!ind) { return; }
    applyIndicatorOverlays(ind);
    buildRsiChart(ind);
    buildMacdChart(ind);
    applyIndicatorVisibility();

    if (!indicatorTogglesBound) {
      document.querySelectorAll('.indicator-toggle').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var key = btn.getAttribute('data-indicator');
          indicatorState[key] = !indicatorState[key];
          applyIndicatorVisibility();
        });
      });
      indicatorTogglesBound = true;
    }
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
      var max = Number(range.max) || 60;
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
    initIndicators();
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
    if (window.matchMedia('(max-width: 900px)').matches) {
      var open = document.body.classList.contains('mobile-nav-open');
      btn.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.setAttribute('title', 'Navigation menu');
      return;
    }
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
      if (window.matchMedia('(max-width: 900px)').matches) {
        var open = document.body.classList.toggle('mobile-nav-open');
        syncSidebarButton();
        return;
      }
      var root = document.documentElement;
      root.classList.toggle('sidebar-collapsed');
      try {
        localStorage.setItem('mm-sidebar', root.classList.contains('sidebar-collapsed') ? 'collapsed' : 'expanded');
      } catch (e) {}
      syncSidebarButton();
    });

    document.querySelectorAll('.sidebar-nav .nav-link').forEach(function (link) {
      link.addEventListener('click', function () {
        if (window.matchMedia('(max-width: 900px)').matches) {
          document.body.classList.remove('mobile-nav-open');
          syncSidebarButton();
        }
      });
    });

    window.addEventListener('resize', function () {
      if (!window.matchMedia('(max-width: 900px)').matches) {
        document.body.classList.remove('mobile-nav-open');
      }
      syncSidebarButton();
    });
  }

  /* ── PWA: service worker + install prompt ────────────────────────── */
  function initPwa() {
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
          .catch(function () { /* Offline support is a progressive enhancement. */ });
      });
    }

    var button = document.getElementById('installApp');
    var deferred = null;
    window.addEventListener('beforeinstallprompt', function (event) {
      event.preventDefault();
      deferred = event;
      if (button) { button.hidden = false; }
    });
    if (button) {
      button.addEventListener('click', function () {
        if (!deferred) { return; }
        deferred.prompt();
        deferred.userChoice.then(function () {
          deferred = null;
          button.hidden = true;
        });
      });
    }
    window.addEventListener('appinstalled', function () {
      if (button) { button.hidden = true; }
    });
  }

  /* ── Command palette ────────────────────────────────────────────── */
  function initCommandPalette() {
    var overlay = document.getElementById('cmdOverlay');
    var input = document.getElementById('cmdInput');
    var results = document.getElementById('cmdResults');
    var trigger = document.getElementById('cmdTrigger');
    if (!overlay || !input || !results) { return; }

    var commands = [
      { label: 'Overview', hint: 'Dashboard', href: '/dashboard/' },
      { label: 'Compare', hint: 'Two symbols', href: '/compare/' },
      { label: 'AI Forecast', hint: 'Price projection', href: '/predict/' },
      { label: 'Market Screener', hint: 'Browse symbols', href: '/stocks/' },
      { label: 'Alerts', hint: 'Price & forecast', href: '/alerts/' },
      { label: 'API Docs', hint: 'JSON endpoints', href: '/api-docs/' },
      { label: 'Landing page', hint: 'About StockSight', href: '/' }
    ];
    var datalist = document.getElementById('globalSymbols');
    var symbols = [];
    if (datalist) {
      symbols = Array.prototype.map.call(datalist.querySelectorAll('option'), function (option) {
        return option.value;
      }).filter(function (value, index, all) { return value && all.indexOf(value) === index; });
    }

    var items = [];
    var active = 0;

    function escapeHtml(value) {
      return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function build(query) {
      var q = query.trim().toLowerCase();
      var list = [];
      commands.forEach(function (command) {
        if (!q || command.label.toLowerCase().indexOf(q) !== -1 ||
            command.hint.toLowerCase().indexOf(q) !== -1) { list.push(command); }
      });
      symbols.forEach(function (symbol) {
        if (!q || symbol.toLowerCase().indexOf(q) !== -1) {
          list.push({ label: symbol, hint: 'Open symbol', href: '/dashboard/?symbol=' + encodeURIComponent(symbol) });
        }
      });
      return list.slice(0, 12);
    }

    function setActive(index) {
      if (!items.length) { return; }
      active = (index + items.length) % items.length;
      Array.prototype.forEach.call(results.querySelectorAll('.cmd-item'), function (item, i) {
        item.classList.toggle('active', i === active);
        if (i === active) { item.scrollIntoView({ block: 'nearest' }); }
      });
    }

    function render(query) {
      items = build(query);
      active = 0;
      if (!items.length) {
        results.innerHTML = '<div class="cmd-empty">No matching commands or symbols.</div>';
        return;
      }
      results.innerHTML = items.map(function (item, index) {
        return '<button type="button" class="cmd-item' + (index === 0 ? ' active' : '') +
          '" data-index="' + index + '" data-href="' + escapeHtml(item.href) + '">' +
          '<span class="cmd-item-label">' + escapeHtml(item.label) + '</span>' +
          '<span class="cmd-item-hint">' + escapeHtml(item.hint) + '</span>' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>' +
          '</button>';
      }).join('');
    }

    function openPalette() {
      overlay.hidden = false;
      input.value = '';
      render('');
      window.setTimeout(function () { input.focus(); }, 0);
    }
    function closePalette() { overlay.hidden = true; }
    function go(index) {
      if (items[index]) { window.location.href = items[index].href; }
    }

    if (trigger) { trigger.addEventListener('click', openPalette); }
    overlay.querySelector('[data-cmd-close]').addEventListener('click', closePalette);

    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); setActive(active + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(active - 1); }
      else if (event.key === 'Enter') { event.preventDefault(); go(active); }
      else if (event.key === 'Escape') { event.preventDefault(); closePalette(); }
    });

    results.addEventListener('click', function (event) {
      var item = event.target && event.target.closest ? event.target.closest('.cmd-item') : null;
      if (item) { go(Number(item.getAttribute('data-index'))); }
    });

    document.addEventListener('keydown', function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K')) {
        event.preventDefault();
        openPalette();
      } else if (event.key === 'Escape' && !overlay.hidden) {
        closePalette();
      }
    });
  }

  /* ── Boot ─────────────────────────────────────────────────────────── */

  function boot() {
    initCharts();
    initIndicators();
    buildOhlcTable();
    buildForecastTable();
    colourNumericCells();
    formatShortNumbers();
    initRangeSync();
    initSymbolSearch();
    initRefreshButtons();
    initTheme();
    initSidebar();
    initPwa();
    initCommandPalette();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
