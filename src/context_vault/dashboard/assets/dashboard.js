/* ContextVault Dashboard — local, read-only interactions (search, filters, sorting, theme, navigation).
 * No network access, no file access, no commands: it only shows and hides what is already in the page. */
(function () {
  "use strict";
  var doc = document;
  var root = doc.documentElement;

  function norm(text) {
    return (text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
  }
  function all(sel, base) { return Array.prototype.slice.call((base || doc).querySelectorAll(sel)); }

  /* ---------- theme: automatic (browser preference) → light → dark */
  var THEMES = ["auto", "light", "dark"];
  var THEME_LABEL = { auto: "Tema: automático", light: "Tema: claro", dark: "Tema: escuro" };
  function storedTheme() {
    try { return localStorage.getItem("cv-dashboard-theme"); } catch (e) { return null; }
  }
  function applyTheme(theme) {
    if (THEMES.indexOf(theme) < 0) { theme = "auto"; }
    root.setAttribute("data-theme", theme);
    all("[data-cv-theme]").forEach(function (btn) {
      var label = btn.querySelector("[data-cv-theme-label]");
      if (label) { label.textContent = THEME_LABEL[theme]; }
      btn.setAttribute("aria-label", THEME_LABEL[theme] + " (alternar)");
    });
    try { localStorage.setItem("cv-dashboard-theme", theme); } catch (e) { /* storage unavailable: ignore */ }
  }
  applyTheme(storedTheme() || "auto");
  window.requestAnimationFrame(function () {
    window.requestAnimationFrame(function () { root.classList.add("cv-ready"); });
  });
  all("[data-cv-theme]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") || "auto";
      applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
    });
  });

  /* ---------- section navigation, built from the section headers */
  var nav = doc.querySelector("nav.sections");
  if (nav) {
    all("section.block[id]").forEach(function (section) {
      var heading = section.querySelector("h2");
      if (!heading) { return; }
      var link = doc.createElement("a");
      link.href = "#" + section.id;
      link.textContent = heading.textContent;
      nav.appendChild(link);
    });
  }

  /* ---------- table filters and counts */
  function rowMatchesFilters(row, tools) {
    var ok = true;
    all("[data-cv-filter]", tools).forEach(function (select) {
      var value = select.value;
      if (!value) { return; }
      var tokens = (row.getAttribute("data-f-" + select.getAttribute("data-cv-filter")) || "").split(" ");
      if (tokens.indexOf(value) < 0) { ok = false; }
    });
    all("[data-cv-flag]", tools).forEach(function (box) {
      if (box.checked && row.getAttribute("data-flag-" + box.getAttribute("data-cv-flag")) !== "1") { ok = false; }
    });
    return ok;
  }
  function updateCount(tableId) {
    var table = doc.getElementById(tableId);
    if (!table) { return; }
    var rows = all("tbody tr", table);
    var visible = rows.filter(function (r) {
      return !r.classList.contains("cv-hide-filter") && !r.classList.contains("cv-hide-search");
    }).length;
    all("[data-cv-count='" + tableId + "']").forEach(function (el) {
      el.textContent = visible === rows.length ? rows.length + " registro(s)" : visible + " de " + rows.length + " registro(s) visíveis";
    });
    var empty = doc.querySelector("[data-cv-empty='" + tableId + "']");
    if (empty) { empty.hidden = visible !== 0; }
  }
  function applyFilters(tools) {
    var tableId = tools.getAttribute("data-cv-table-tools");
    var table = doc.getElementById(tableId);
    if (!table) { return; }
    all("tbody tr", table).forEach(function (row) {
      row.classList.toggle("cv-hide-filter", !rowMatchesFilters(row, tools));
    });
    updateCount(tableId);
  }
  all("[data-cv-table-tools]").forEach(function (tools) {
    all("select, input[type=checkbox]", tools).forEach(function (input) {
      input.addEventListener("change", function () { applyFilters(tools); });
    });
    var reset = tools.querySelector("[data-cv-reset]");
    if (reset) {
      reset.addEventListener("click", function () {
        all("select", tools).forEach(function (s) { s.value = ""; });
        all("input[type=checkbox]", tools).forEach(function (c) { c.checked = false; });
        applyFilters(tools);
      });
    }
    applyFilters(tools);
  });
  all("table[id]").forEach(function (t) { updateCount(t.id); });

  /* ---------- sorting */
  all("th [data-cv-sort]").forEach(function (button) {
    button.addEventListener("click", function () {
      var th = button.closest("th");
      var table = button.closest("table");
      var key = button.getAttribute("data-cv-sort");
      var ascending = th.getAttribute("aria-sort") !== "ascending";
      all("th", table).forEach(function (other) { other.removeAttribute("aria-sort"); });
      th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      var body = table.tBodies[0];
      var rows = all("tr", body);
      rows.sort(function (a, b) {
        var x = a.getAttribute("data-s-" + key) || "";
        var y = b.getAttribute("data-s-" + key) || "";
        var cmp = x.localeCompare(y, "pt-BR", { numeric: true, sensitivity: "base" });
        return ascending ? cmp : -cmp;
      });
      rows.forEach(function (row) { body.appendChild(row); });
    });
  });

  /* ---------- icons: official Lucide SVGs when the pinned library loaded; embedded SVGs otherwise */
  doc.addEventListener("DOMContentLoaded", function () {
    var lib = window.lucide;
    if (!lib || typeof lib.createElement !== "function" || !lib.icons) { return; }
    all("i[data-lucide]").forEach(function (slot) {
      var key = slot.getAttribute("data-lucide").replace(/(^|-)([a-z])/g, function (_, d, c) { return c.toUpperCase(); });
      var node = lib.icons[key];
      if (!node) { return; }
      var size = slot.getAttribute("data-size") || "16";
      var svg = lib.createElement(node);
      svg.setAttribute("class", slot.getAttribute("data-icon-class") || "icon");
      svg.setAttribute("width", size);
      svg.setAttribute("height", size);
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      slot.replaceChildren(svg);
    });
  });

  /* ---------- text search over every item of the report */
  var search = doc.querySelector("[data-cv-search]");
  if (search) {
    var timer = null;
    var items = all("[data-cv-item]");
    var status = doc.querySelector("[data-cv-search-status]");
    var run = function () {
      var query = norm(search.value);
      var shown = 0;
      items.forEach(function (item) {
        var hit = !query || norm(item.textContent).indexOf(query) >= 0;
        item.classList.toggle("cv-hide-search", !hit);
        if (hit) { shown += 1; }
      });
      all("table[id]").forEach(function (t) { updateCount(t.id); });
      if (status) { status.textContent = query ? shown + " item(ns) correspondem à busca." : ""; }
    };
    search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(run, 120);
    });
  }
})();
