/* StockSight alerts — localStorage rules checked in the open browser tab. */
(function () {
  'use strict';

  var L = window.StockSightLocal;
  var money = new Intl.NumberFormat(undefined, {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2
  });

  var CONDITIONS = {
    price_above: { label: 'Price rises above', kind: 'price' },
    price_below: { label: 'Price falls below', kind: 'price' },
    change_above: { label: 'Daily gain above', kind: 'percent' },
    change_below: { label: 'Daily drop below', kind: 'percent' }
  };

  function condition(alert) {
    return CONDITIONS[alert.condition] || CONDITIONS.price_above;
  }

  function evaluate(alert, quote) {
    var target = Number(alert.threshold);
    var current = null;
    if (condition(alert).kind === 'percent') {
      current = Number(quote && quote.change_pct);
    } else {
      current = Number(quote && quote.close);
    }
    if (!isFinite(current)) { return { triggered: false, current: null }; }

    var triggered = false;
    switch (alert.condition) {
      case 'price_above':
        triggered = current > target;
        break;
      case 'price_below':
        triggered = current < target;
        break;
      case 'change_above':
        triggered = current > target;
        break;
      case 'change_below':
        triggered = current < -Math.abs(target);
        break;
      default:
        triggered = false;
    }
    return { triggered: triggered, current: current };
  }

  function displayCurrent(alert, value) {
    if (value === null || value === undefined || !isFinite(Number(value))) { return '—'; }
    var n = Number(value);
    if (condition(alert).kind === 'percent') { return (n > 0 ? '+' : '') + n.toFixed(2) + '%'; }
    return money.format(n);
  }

  function displayTarget(alert) {
    var n = Number(alert.threshold);
    if (!isFinite(n)) { return '—'; }
    if (alert.condition === 'change_below') { return '−' + Math.abs(n).toFixed(2) + '%'; }
    if (condition(alert).kind === 'percent') { return '+' + Math.abs(n).toFixed(2) + '%'; }
    return money.format(n);
  }

  function notify(alert, detail) {
    if (!('Notification' in window) || window.Notification.permission !== 'granted') { return; }
    try {
      new window.Notification('StockSight alert · ' + alert.symbol, {
        body: detail,
        tag: 'stocksight-' + alert.id
      });
    } catch (e) { /* Some browsers block notifications in headless/private contexts. */ }
  }

  function quoteMap(quotes) {
    var map = {};
    (quotes || []).forEach(function (quote) {
      if (quote && quote.symbol) { map[quote.symbol] = quote; }
    });
    return map;
  }

  function render() {
    var body = document.getElementById('alertsBody');
    var sub = document.getElementById('alertsSub');
    if (!body) { return; }
    var alerts = L.getAlerts();

    if (!alerts.length) {
      body.innerHTML = '<tr><td colspan="7" class="muted center">No alerts yet — create one above.</td></tr>';
      if (sub) { sub.textContent = 'No alerts yet'; }
      return;
    }

    var triggered = alerts.filter(function (alert) { return alert.triggered; }).length;
    if (sub) {
      sub.textContent = alerts.length + ' alert' + (alerts.length === 1 ? '' : 's') +
        ' · ' + triggered + ' triggered · stored in this browser';
    }

    body.innerHTML = alerts.map(function (alert, index) {
      var def = condition(alert);
      var status = alert.triggered
        ? '<span class="badge badge-buy">TRIGGERED</span>'
        : '<span class="badge badge-neutral">WATCHING</span>';
      return '<tr>' +
        '<td><a class="symbol-link" href="/dashboard/?symbol=' + encodeURIComponent(alert.symbol) + '">' + L.esc(alert.symbol) + '</a></td>' +
        '<td>' + L.esc(def.label) + '</td>' +
        '<td class="num">' + L.esc(displayTarget(alert)) + '</td>' +
        '<td class="num">' + L.esc(displayCurrent(alert, alert.current)) + '</td>' +
        '<td>' + status + '</td>' +
        '<td class="num muted">' + L.esc(alert.checkedAt || '—') + '</td>' +
        '<td><button type="button" class="text-link link-button" data-delete="' + index + '">Delete</button></td>' +
        '</tr>';
    }).join('');
  }

  function nowLabel() {
    return new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  function checkPriceAlerts(quiet) {
    var alerts = L.getAlerts();
    var priceAlerts = alerts;
    if (!priceAlerts.length) {
      if (!quiet) { L.toast('No price alerts to check.', 'info'); }
      return Promise.resolve();
    }
    var symbols = priceAlerts.map(function (a) { return a.symbol; })
      .filter(function (s, i, arr) { return arr.indexOf(s) === i; });
    return L.fetchQuotes(symbols).then(function (quotes) {
      var map = quoteMap(quotes);
      var triggered = 0;
      priceAlerts.forEach(function (alert) {
        var result = evaluate(alert, map[alert.symbol]);
        var wasTriggered = !!alert.triggered;
        alert.current = result.current;
        alert.triggered = result.triggered;
        alert.checkedAt = nowLabel();
        if (result.triggered) {
          triggered += 1;
          if (!wasTriggered || !alert.notified) {
            notify(alert, condition(alert).label + ' ' + displayTarget(alert) +
              ' · now ' + displayCurrent(alert, result.current));
            alert.notified = true;
          }
        } else {
          alert.notified = false;
        }
      });
      L.setAlerts(alerts);
      render();
      if (!quiet) {
        L.toast('Checked ' + priceAlerts.length + ' price alert' + (priceAlerts.length === 1 ? '' : 's') +
          ' · ' + triggered + ' triggered', triggered ? 'success' : 'info');
      }
    });
  }

  function syncNotifyButton() {
    var button = document.getElementById('notifyBtn');
    if (!button) { return; }
    var supported = 'Notification' in window;
    var granted = supported && window.Notification.permission === 'granted';
    button.textContent = granted ? 'Notifications on' :
      (supported ? 'Enable notifications' : 'Notifications unavailable');
    button.disabled = granted || !supported;
  }

  function init() {
    render();

    var form = document.getElementById('alertForm');
    var conditionInput = document.getElementById('aCondition');
    var hint = document.getElementById('thresholdHint');
    if (conditionInput && hint) {
      conditionInput.addEventListener('change', function () {
        var def = CONDITIONS[conditionInput.value];
        hint.textContent = def && def.kind === 'percent'
          ? 'Enter a positive percentage. “Daily drop below 2%” triggers at −2% or worse.'
          : 'Enter a price target, or a percentage for daily-change alerts.';
      });
    }

    if (form) {
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var symbol = L.normaliseSymbol(document.getElementById('aSymbol').value);
        var threshold = Number(document.getElementById('aThreshold').value);
        var selected = conditionInput ? conditionInput.value : 'price_above';
        if (!symbol || !isFinite(threshold)) {
          L.toast('Enter a symbol and a valid threshold.', 'error');
          return;
        }
        var alerts = L.getAlerts();
        alerts.push({
          id: String(Date.now()) + Math.random().toString(36).slice(2, 7),
          symbol: symbol,
          condition: selected,
          threshold: threshold,
          current: null,
          triggered: false,
          notified: false,
          checkedAt: null,
          createdAt: new Date().toISOString()
        });
        L.setAlerts(alerts);
        form.reset();
        if (hint) { hint.textContent = 'Enter a price target, or a percentage for daily-change alerts.'; }
        render();
        L.toast('Alert saved in this browser', 'success');
      });
    }

    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) { return; }
      var remove = target.closest('[data-delete]');
      if (remove) {
        var alerts = L.getAlerts();
        alerts.splice(Number(remove.getAttribute('data-delete')), 1);
        L.setAlerts(alerts);
        render();
      }
    });

    var notifyButton = document.getElementById('notifyBtn');
    if (notifyButton) {
      notifyButton.addEventListener('click', function () {
        if (!('Notification' in window)) { return; }
        window.Notification.requestPermission().then(syncNotifyButton);
      });
    }
    var checkButton = document.getElementById('checkBtn');
    if (checkButton) {
      checkButton.addEventListener('click', function () {
        checkButton.disabled = true;
        checkPriceAlerts(false).then(function () { checkButton.disabled = false; });
      });
    }
    syncNotifyButton();
    checkPriceAlerts(true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
