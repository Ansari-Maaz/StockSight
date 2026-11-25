/* StockSight portfolio — positions, P&L and watchlist, all in localStorage. */
(function () {
  'use strict';

  var L = window.StockSightLocal;
  var money = new Intl.NumberFormat(undefined, {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2
  });

  function num(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) { return '—'; }
    return n.toLocaleString(undefined, { minimumFractionDigits: digits || 2, maximumFractionDigits: digits || 2 });
  }

  function colourClass(element, value) {
    element.classList.remove('pos', 'neg');
    if (value > 0) { element.classList.add('pos'); }
    else if (value < 0) { element.classList.add('neg'); }
  }

  function quoteMap(quotes) {
    var map = {};
    (quotes || []).forEach(function (quote) {
      if (quote && quote.symbol) { map[quote.symbol] = quote; }
    });
    return map;
  }

  function renderPositions() {
    var body = document.getElementById('positionsBody');
    var bar = document.getElementById('allocationBar');
    var sub = document.getElementById('holdingsSub');
    if (!body) { return; }

    var positions = L.getPositions();
    var symbols = positions.map(function (p) { return p.symbol; })
      .filter(function (s, i, arr) { return arr.indexOf(s) === i; });

    if (!positions.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted center">No positions yet — add one above to get started.</td></tr>';
      if (bar) { bar.innerHTML = ''; }
      if (sub) { sub.textContent = 'No positions yet'; }
      ['portfolioValue', 'portfolioCost', 'portfolioPnl', 'portfolioDay'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) { el.textContent = '—'; }
      });
      var pct = document.getElementById('portfolioPnlPct');
      if (pct) { pct.textContent = '—'; }
      return;
    }

    return L.fetchQuotes(symbols).then(function (quotes) {
      var quotesBySymbol = quoteMap(quotes);
      var totals = { value: 0, cost: 0, day: 0 };
      var allocations = [];
      var palette = ['#4f46e5', '#7c3aed', '#0284c7', '#059669', '#d97706', '#e11d48'];

      var rows = positions.map(function (position, index) {
        var quote = quotesBySymbol[position.symbol] || {};
        var close = Number(quote.close);
        var shares = Number(position.shares);
        var cost = Number(position.cost);
        var value = isFinite(close) ? close * shares : 0;
        var basis = cost * shares;
        var pnl = value - basis;
        var pnlPct = basis ? (pnl / basis) * 100 : 0;
        totals.value += value;
        totals.cost += basis;
        if (isFinite(Number(quote.change))) { totals.day += Number(quote.change) * shares; }
        allocations.push({ symbol: position.symbol, value: value });

        return '<tr>' +
          '<td><a class="symbol-link" href="/dashboard/?symbol=' + encodeURIComponent(position.symbol) + '">' + L.esc(position.symbol) + '</a></td>' +
          '<td class="num">' + num(shares, 4) + '</td>' +
          '<td class="num">' + money.format(cost) + '</td>' +
          '<td class="num">' + (isFinite(close) ? money.format(close) : '—') + '</td>' +
          '<td class="num">' + (isFinite(close) ? money.format(value) : '—') + '</td>' +
          '<td class="num ' + (pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '') + '">' + (isFinite(close) ? money.format(pnl) : '—') + '</td>' +
          '<td class="num ' + (pnlPct > 0 ? 'pos' : pnlPct < 0 ? 'neg' : '') + '">' + (isFinite(close) ? pnlPct.toFixed(2) + '%' : '—') + '</td>' +
          '<td><button type="button" class="text-link link-button" data-remove="' + index + '">Remove</button></td>' +
          '</tr>';
      }).join('');

      body.innerHTML = rows;
      if (sub) { sub.textContent = positions.length + ' position' + (positions.length === 1 ? '' : 's') + ' · local browser data'; }

      var valueEl = document.getElementById('portfolioValue');
      var costEl = document.getElementById('portfolioCost');
      var pnlEl = document.getElementById('portfolioPnl');
      var pnlPctEl = document.getElementById('portfolioPnlPct');
      var dayEl = document.getElementById('portfolioDay');
      var totalPnl = totals.value - totals.cost;
      var totalPnlPct = totals.cost ? (totalPnl / totals.cost) * 100 : 0;

      if (valueEl) { valueEl.textContent = money.format(totals.value); }
      if (costEl) { costEl.textContent = money.format(totals.cost); }
      if (pnlEl) { pnlEl.textContent = money.format(totalPnl); colourClass(pnlEl, totalPnl); }
      if (pnlPctEl) {
        pnlPctEl.textContent = totalPnlPct.toFixed(2) + '% return';
        colourClass(pnlPctEl, totalPnlPct);
      }
      if (dayEl) { dayEl.textContent = (totals.day > 0 ? '+' : '') + money.format(totals.day); colourClass(dayEl, totals.day); }

      if (bar) {
        bar.innerHTML = allocations.map(function (item, index) {
          var width = totals.value ? Math.max(0, (item.value / totals.value) * 100) : 0;
          return '<span class="allocation-segment" style="width:' + width.toFixed(2) + '%;background:' +
            palette[index % palette.length] + '" title="' + L.esc(item.symbol) + ' · ' + width.toFixed(1) + '%"></span>';
        }).join('');
      }
    });
  }

  function renderWatch() {
    var body = document.getElementById('watchBody');
    var count = document.getElementById('watchCount');
    if (!body) { return; }
    var list = L.getWatchlist();

    if (!list.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted center">Your watchlist is empty.</td></tr>';
      if (count) { count.textContent = '0 symbols'; }
      return;
    }

    L.fetchQuotes(list).then(function (quotes) {
      var map = quoteMap(quotes);
      body.innerHTML = list.map(function (symbol) {
        var quote = map[symbol] || {};
        var close = Number(quote.close);
        var change = Number(quote.change_pct);
        return '<tr>' +
          '<td><a class="symbol-link" href="/dashboard/?symbol=' + encodeURIComponent(symbol) + '">' + L.esc(symbol) + '</a></td>' +
          '<td class="num">' + (isFinite(close) ? money.format(close) : '—') + '</td>' +
          '<td class="num ' + (change > 0 ? 'pos' : change < 0 ? 'neg' : '') + '">' +
          (isFinite(change) ? (change > 0 ? '+' : '') + change.toFixed(2) + '%' : '—') + '</td>' +
          '<td><button type="button" class="text-link link-button" data-unwatch="' + L.esc(symbol) + '">Remove</button></td>' +
          '</tr>';
      }).join('');
      if (count) { count.textContent = list.length + ' symbol' + (list.length === 1 ? '' : 's'); }
    });
  }

  function init() {
    renderPositions();
    renderWatch();

    var positionForm = document.getElementById('positionForm');
    if (positionForm) {
      positionForm.addEventListener('submit', function (event) {
        event.preventDefault();
        var symbol = L.normaliseSymbol(document.getElementById('pSymbol').value);
        var shares = Number(document.getElementById('pShares').value);
        var cost = Number(document.getElementById('pCost').value);
        if (!symbol || !(shares > 0) || !(cost > 0)) {
          L.toast('Enter a symbol, shares and a positive average cost.', 'error');
          return;
        }
        var positions = L.getPositions();
        var existing = positions.find(function (p) { return p.symbol === symbol; });
        if (existing) {
          var totalShares = Number(existing.shares) + shares;
          existing.cost = (Number(existing.cost) * Number(existing.shares) + cost * shares) / totalShares;
          existing.shares = totalShares;
        } else {
          positions.push({ symbol: symbol, shares: shares, cost: cost });
        }
        L.setPositions(positions);
        positionForm.reset();
        L.toast(symbol + ' position saved in this browser', 'success');
        renderPositions();
      });
    }

    var watchForm = document.getElementById('watchForm');
    if (watchForm) {
      watchForm.addEventListener('submit', function (event) {
        event.preventDefault();
        var symbol = L.normaliseSymbol(document.getElementById('wSymbol').value);
        if (!symbol) { return; }
        var list = L.getWatchlist();
        if (list.indexOf(symbol) === -1) { list.push(symbol); }
        L.setWatchlist(list);
        watchForm.reset();
        renderWatch();
        L.toast(symbol + ' added to your watchlist', 'success');
      });
    }

    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) { return; }
      var remove = target.closest('[data-remove]');
      if (remove) {
        var positions = L.getPositions();
        positions.splice(Number(remove.getAttribute('data-remove')), 1);
        L.setPositions(positions);
        renderPositions();
      }
      if (target.closest('#watchBody [data-unwatch]')) {
        window.setTimeout(renderWatch, 0);
      }
    });

    var exportButton = document.getElementById('exportPositions');
    if (exportButton) {
      exportButton.addEventListener('click', function () {
        var payload = {
          exported_at: new Date().toISOString(),
          positions: L.getPositions(),
          watchlist: L.getWatchlist(),
          alerts: L.getAlerts()
        };
        var blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = 'stocksight-local-data.json';
        link.click();
        URL.revokeObjectURL(url);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
