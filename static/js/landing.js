/* StockSight landing page — motion, navigation and counters. */
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var nav = document.getElementById("nav");
  var navToggle = document.getElementById("navToggle");
  var progress = document.getElementById("scrollProgress");
  var cursorGlow = document.getElementById("cursorGlow");

  /* ── Nav: sticky background + mobile menu ─────────────────────── */
  function onScroll() {
    var y = window.scrollY || 0;
    if (nav) nav.classList.toggle("scrolled", y > 24);
    if (progress) {
      var doc = document.documentElement;
      var max = doc.scrollHeight - window.innerHeight;
      progress.style.width = (max > 0 ? (y / max) * 100 : 0) + "%";
    }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (navToggle) {
    navToggle.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
      navToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });
  }

  document.querySelectorAll("#navLinks a").forEach(function (link) {
    link.addEventListener("click", function () {
      document.body.classList.remove("nav-open");
      if (navToggle) {
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.setAttribute("aria-label", "Open menu");
      }
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) {
      document.body.classList.remove("nav-open");
      if (navToggle) navToggle.setAttribute("aria-expanded", "false");
    }
  });

  /* ── Scroll reveal ────────────────────────────────────────────── */
  var revealItems = document.querySelectorAll(".reveal");

  if (reduced.matches || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

    revealItems.forEach(function (el) { observer.observe(el); });
  }

  /* ── Animated counters ────────────────────────────────────────── */
  function animateCount(el) {
    var target = parseInt(el.dataset.count, 10);
    if (isNaN(target)) return;
    var suffix = el.dataset.suffix || "";
    if (reduced.matches) {
      el.textContent = target + suffix;
      return;
    }
    var duration = 1400;
    var start = null;

    function frame(now) {
      if (start === null) start = now;
      var p = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased) + suffix;
      if (p < 1) window.requestAnimationFrame(frame);
    }
    window.requestAnimationFrame(frame);
  }

  var counters = document.querySelectorAll("[data-count]");
  if (counters.length) {
    if (reduced.matches || !("IntersectionObserver" in window)) {
      counters.forEach(animateCount);
    } else {
      var countObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            animateCount(entry.target);
            countObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.6 });
      counters.forEach(function (el) { countObserver.observe(el); });
    }
  }

  /* ── Pointer glow + hero parallax (fine pointers only) ────────── */
  if (window.matchMedia("(pointer: fine)").matches) {
    document.body.classList.add("pointer-fine");

    var glowTarget = null;
    window.addEventListener("pointermove", function (event) {
      if (!cursorGlow) return;
      cursorGlow.style.setProperty("--mx", event.clientX + "px");
      cursorGlow.style.setProperty("--my", event.clientY + "px");
    }, { passive: true });

    if (!reduced.matches) {
      var parallax = document.querySelector("[data-parallax]");
      var ticking = false;
      window.addEventListener("scroll", function () {
        if (!parallax || ticking) return;
        ticking = true;
        window.requestAnimationFrame(function () {
          var rect = parallax.getBoundingClientRect();
          var offset = Math.max(-28, Math.min(28, rect.top * -0.035));
          parallax.style.transform = "translate3d(0, " + offset.toFixed(2) + "px, 0)";
          ticking = false;
        });
      }, { passive: true });
    }
  }

  /* ── Smooth anchor offset for the fixed nav ───────────────────── */
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      var id = link.getAttribute("href");
      if (!id || id === "#") return;
      var target = document.querySelector(id);
      if (!target) return;
      event.preventDefault();
      var top = target.getBoundingClientRect().top + window.scrollY - 84;
      window.scrollTo({ top: top, behavior: reduced.matches ? "auto" : "smooth" });
      if (history.pushState) history.pushState(null, "", id);
    });
  });

  /* ── Only one FAQ item open at a time ─────────────────────────── */
  var faqs = document.querySelectorAll(".faq-item");
  faqs.forEach(function (item) {
    item.addEventListener("toggle", function () {
      if (!item.open) return;
      faqs.forEach(function (other) {
        if (other !== item) other.open = false;
      });
    });
  });

  /* ── Shared helpers ────────────────────────────────────────────── */
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) { return null; }
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function money(value) {
    return "$" + Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  /* ── Landing theme (shared with the dashboard via mm-theme) ───── */
  var themeToggle = document.getElementById("landingThemeToggle");
  var themeColor = document.getElementById("themeColor");

  function syncThemeMeta() {
    var dark = document.documentElement.dataset.theme === "dark";
    if (themeColor) { themeColor.setAttribute("content", dark ? "#070b18" : "#f5f7fc"); }
    if (themeToggle) {
      var label = dark ? "Switch to light theme" : "Switch to dark theme";
      themeToggle.setAttribute("aria-label", label);
      themeToggle.setAttribute("title", label);
    }
  }
  syncThemeMeta();

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("mm-theme", next); } catch (e) {}
      syncThemeMeta();
    });
  }
  window.addEventListener("storage", function (event) {
    if (event.key === "mm-theme" && (event.newValue === "light" || event.newValue === "dark")) {
      document.documentElement.dataset.theme = event.newValue;
      syncThemeMeta();
    }
  });

  /* ── Live hero chart from the local cache ─────────────────────── */
  function buildSpark(values) {
    var nums = (values || []).filter(function (v) {
      return v !== null && v !== undefined && isFinite(Number(v));
    }).map(Number);
    if (nums.length < 2) { return null; }

    var min = Math.min.apply(null, nums);
    var max = Math.max.apply(null, nums);
    var span = max - min || 1;
    var points = nums.map(function (value, index) {
      return [
        24 + (472 * index) / (nums.length - 1),
        150 - ((value - min) / span) * 112
      ];
    });
    var line = "M" + points.map(function (point) {
      return point[0].toFixed(1) + " " + point[1].toFixed(1);
    }).join(" L");
    return {
      line: line,
      area: line + "V190H24Z",
      end: points[points.length - 1],
      change: nums[0] ? ((nums[nums.length - 1] / nums[0]) - 1) * 100 : 0
    };
  }

  function applyHeroData(symbol, series, quote) {
    var spark = buildSpark((series && series.close ? series.close : []).slice(-60));
    if (spark) {
      var line = document.getElementById("sparkLinePath");
      var area = document.getElementById("sparkAreaPath");
      var dot = document.getElementById("sparkDot");
      var halo = document.getElementById("sparkHalo");
      if (line) { line.setAttribute("d", spark.line); }
      if (area) { area.setAttribute("d", spark.area); }
      if (dot) { dot.setAttribute("cx", spark.end[0].toFixed(1)); dot.setAttribute("cy", spark.end[1].toFixed(1)); }
      if (halo) { halo.setAttribute("cx", spark.end[0].toFixed(1)); halo.setAttribute("cy", spark.end[1].toFixed(1)); }
    }

    var symbolEl = document.getElementById("demoSymbol");
    if (symbolEl) { symbolEl.textContent = symbol; }
    document.querySelectorAll("[data-demo-symbol]").forEach(function (chip) {
      chip.classList.toggle("active", chip.getAttribute("data-demo-symbol") === symbol);
    });

    var periodEl = document.getElementById("demoPeriodChange");
    if (periodEl && spark) {
      periodEl.textContent = (spark.change > 0 ? "+" : "") + spark.change.toFixed(2) + "%";
      periodEl.classList.toggle("up", spark.change >= 0);
      periodEl.classList.toggle("down", spark.change < 0);
    }

    if (!quote) { return; }
    var price = Number(quote.close);
    var change = Number(quote.change_pct);
    var priceEl = document.getElementById("demoPrice");
    if (priceEl && isFinite(price)) { priceEl.textContent = money(price); }
    var changeEl = document.getElementById("demoChange");
    if (changeEl && isFinite(change)) {
      changeEl.textContent = (change > 0 ? "+" : "") + change.toFixed(2) + "%";
      changeEl.classList.toggle("up", change >= 0);
      changeEl.classList.toggle("down", change < 0);
    }
    var range = document.getElementById("demoDayRange");
    if (range && isFinite(Number(quote.low)) && isFinite(Number(quote.high))) {
      range.textContent = money(quote.low) + "–" + money(quote.high);
    }
    var through = document.getElementById("demoDataThrough");
    if (through && quote.date) { through.textContent = quote.date; }
  }

  function initHeroDemo() {
    var series = readJson("mm-hero-series");
    var symbolEl = document.getElementById("demoSymbol");
    var symbol = symbolEl ? symbolEl.textContent.trim() : "AAPL";
    if (series && series.close && series.close.length > 1) {
      applyHeroData(symbol, series, null);
    }

    document.querySelectorAll("[data-demo-symbol]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var next = chip.getAttribute("data-demo-symbol");
        if (!next || next === symbol) { return; }
        Promise.all([
          fetch("/api/history/?symbol=" + encodeURIComponent(next) + "&refresh=never").then(function (r) { return r.json(); }),
          fetch("/api/quotes/?symbols=" + encodeURIComponent(next)).then(function (r) { return r.json(); })
        ]).then(function (results) {
          var quote = (results[1].quotes || [])[0] || {};
          symbol = next;
          applyHeroData(next, results[0].series || { close: [] }, quote);
        }).catch(function () { /* Keep the last working preview on failure. */ });
      });
    });
  }
  initHeroDemo();

  /* ── Landing compare widget ───────────────────────────────────── */
  var cmpWindow = 126;
  var cmpRan = false;

  function fetchCloses(symbol) {
    return fetch("/api/history/?symbol=" + encodeURIComponent(symbol) + "&refresh=never")
      .then(function (response) {
        if (!response.ok) { throw new Error("history unavailable"); }
        return response.json();
      })
      .then(function (payload) { return (payload.series && payload.series.close) || []; });
  }

  function normalise(values, count) {
    var clean = values.slice(-count).map(Number).filter(function (v) { return isFinite(v); });
    var base = clean[0] || 1;
    return clean.map(function (value) { return (value / base) * 100; });
  }

  function cmpPath(values, low, high, length) {
    var span = high - low || 1;
    return "M" + values.map(function (value, index) {
      var x = 40 + (740 * index) / Math.max(1, values.length - 1);
      var y = 240 - ((value - low) / span) * 220;
      return x.toFixed(1) + " " + y.toFixed(1);
    }).join(" L");
  }

  function setReturn(id, value) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.textContent = (value > 0 ? "+" : "") + value.toFixed(2) + "%";
    el.classList.toggle("up", value >= 0);
    el.classList.toggle("down", value < 0);
  }

  function runCompare() {
    var inputA = document.getElementById("cmpA");
    var inputB = document.getElementById("cmpB");
    var status = document.getElementById("cmpStatus");
    if (!inputA || !inputB) { return; }
    var a = inputA.value.trim().toUpperCase();
    var b = inputB.value.trim().toUpperCase();
    if (!a || !b) { if (status) { status.textContent = "Enter two symbols to compare."; } return; }

    if (status) { status.textContent = "Loading cached history…"; }
    Promise.all([fetchCloses(a), fetchCloses(b)]).then(function (results) {
      var seriesA = normalise(results[0], cmpWindow);
      var seriesB = normalise(results[1], cmpWindow);
      var count = Math.min(seriesA.length, seriesB.length);
      if (count < 2) {
        if (status) { status.textContent = "Not enough cached history for that pair. Try another symbol."; }
        return;
      }
      seriesA = seriesA.slice(-count);
      seriesB = seriesB.slice(-count);
      var low = Math.min(Math.min.apply(null, seriesA), Math.min.apply(null, seriesB));
      var high = Math.max(Math.max.apply(null, seriesA), Math.max.apply(null, seriesB));
      var pathA = cmpPath(seriesA, low, high, count);
      var pathB = cmpPath(seriesB, low, high, count);

      var lineA = document.getElementById("cmpLineA");
      var lineB = document.getElementById("cmpLineB");
      var areaA = document.getElementById("cmpAreaA");
      if (lineA) { lineA.setAttribute("d", pathA); }
      if (lineB) { lineB.setAttribute("d", pathB); }
      if (areaA) { areaA.setAttribute("d", pathA + "V240H40Z"); }

      var nameA = document.getElementById("cmpNameA");
      var nameB = document.getElementById("cmpNameB");
      if (nameA) { nameA.textContent = a; }
      if (nameB) { nameB.textContent = b; }
      setReturn("cmpReturnA", seriesA[seriesA.length - 1] - 100);
      setReturn("cmpReturnB", seriesB[seriesB.length - 1] - 100);
      if (status) { status.textContent = count + " sessions · rebased to 100 · cached daily closes"; }
    }).catch(function () {
      if (status) { status.textContent = "Could not load that pair from the local cache."; }
    });
  }

  var compareSection = document.getElementById("compare");
  if (compareSection) {
    var run = document.getElementById("cmpRun");
    if (run) { run.addEventListener("click", runCompare); }
    document.querySelectorAll(".range-switch button").forEach(function (button) {
      button.addEventListener("click", function () {
        document.querySelectorAll(".range-switch button").forEach(function (other) {
          other.classList.remove("active");
        });
        button.classList.add("active");
        cmpWindow = parseInt(button.getAttribute("data-range"), 10) || 126;
        runCompare();
      });
    });
    [document.getElementById("cmpA"), document.getElementById("cmpB")].forEach(function (input) {
      if (!input) { return; }
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); runCompare(); }
      });
    });

    if ("IntersectionObserver" in window) {
      var compareObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && !cmpRan) {
            cmpRan = true;
            runCompare();
            compareObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.2 });
      compareObserver.observe(compareSection);
    } else {
      runCompare();
    }
  }
})();
