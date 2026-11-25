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
})();
