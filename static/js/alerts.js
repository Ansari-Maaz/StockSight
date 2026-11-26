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
    change_below: { label: 'Daily drop below', kind: 'percent' },
    forecast_above: { label: '7-day forecast above', kind: 'forecast' },
    forecast_below: { label: '7-day forecast below', kind: 'forecast' }
  };

  function condition(alert) {
    return CONDITIONS[alert.condition] || CONDITIONS.price_above;
  }

  function evaluate(alert, quote, forecast) {
    var target = Number(alert.threshold);
    var current = null;
    if (condition(alert).kind === 'forecast') {
      current = forecast;
    } else if (condition(alert).kind === 'percent') {
      current = Number(quote && quote.change_pct);
    } else {
      current = Number(quote && quote.close);
    }
    if (!isFinite(current)) { return { triggered: false, current: null }; }

    var triggered = false;
    switch (alert.condition) {
      case 'price_above':
      case 'forecast_above':
        triggered = current > target;
        break;
      case 'price_below':
      case 'forecast_below':
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
        '<td>' + L.esc(def.label) + (def.kind === 'forecast' ? ' <span class="muted mono">AI</span>' : '') + '</td>' +
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
    var priceAlerts = alerts.filter(function (alert) { return condition(alert).kind !== 'forecast'; });
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
        var result = evaluate(alert, map[alert.symbol], null);
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

  function postJson(url, payload) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (response) { return response.json(); });
  }

  function checkForecastAlerts() {
    var alerts = L.getAlerts();
    var forecastAlerts = alerts.filter(function (alert) { return condition(alert).kind === 'forecast'; });
    if (!forecastAlerts.length) {
      L.toast('No forecast alerts to check.', 'info');
      return;
    }
    var button = document.getElementById('checkForecastBtn');
    if (button) { button.disabled = true; button.textContent = 'Checking…'; }

    var symbols = forecastAlerts.map(function (a) { return a.symbol; })
      .filter(function (s, i, arr) { return arr.indexOf(s) === i; });
    var forecasts = {};

    symbols.reduce(function (chain, symbol) {
      return chain.then(function () {
        return postJson('/api/predict/', { symbol: symbol, days: 7 })
          .then(function (payload) {
            var values = (payload.result && payload.result.predictions) || [];
            forecasts[symbol] = values.length ? Number(values[values.length - 1]) : null;
          })
          .catch(function () { forecasts[symbol] = null; });
      });
    }, Promise.resolve()).then(function () {
      var triggered = 0;
      forecastAlerts.forEach(function (alert) {
        var result = evaluate(alert, null, forecasts[alert.symbol]);
        alert.current = result.current;
        alert.triggered = result.triggered;
        alert.checkedAt = nowLabel();
        if (result.triggered) {
          triggered += 1;
          if (!alert.notified) {
            notify(alert, 'Forecast now ' + displayCurrent(alert, result.current));
            alert.notified = true;
          }
        } else {
          alert.notified = false;
        }
      });
      L.setAlerts(alerts);
      render();
      L.toast('Checked ' + symbols.length + ' forecast' + (symbols.length === 1 ? '' : 's') +
        ' · ' + triggered + ' triggered', 'success');
    }).then(function () {
      if (button) { button.disabled = false; button.textContent = 'Check forecasts'; }
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
          : 'Enter a price target. Forecast alerts reuse the local 7-day model when checked.';
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
        if (hint) { hint.textContent = 'Enter a price target. Forecast alerts reuse the local 7-day model when checked.'; }
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
    var forecastButton = document.getElementById('checkForecastBtn');
    if (forecastButton) {
      forecastButton.addEventListener('click', checkForecastAlerts);
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
