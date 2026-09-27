/* INSIGNIA — site behaviour. No dependencies. */
(() => {
  "use strict";

  const root = document.documentElement;
  const base = root.dataset.base || "";
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
  };

  /* ── Theme ─────────────────────────────────────────────────────────────── */

  $$("[data-theme-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      store.set("theme", next);
    })
  );
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!store.get("theme")) root.dataset.theme = e.matches ? "dark" : "light";
  });

  /* ── Header: mobile menu, hide-on-scroll while reading, progress ───────── */

  const header = $("[data-header]");
  const menuBtn = $("[data-menu-toggle]");
  const mobileNav = $("#mobile-nav");
  menuBtn?.addEventListener("click", () => {
    const open = mobileNav.hidden;
    mobileNav.hidden = !open;
    menuBtn.setAttribute("aria-expanded", String(open));
  });

  const progress = $("[data-progress]");
  const reading = $("[data-reading]");
  if (document.body.classList.contains("mode-reader")) {
    let lastY = scrollY;
    let ticking = false;
    const update = () => {
      const y = scrollY;
      const goingDown = y > lastY;
      if (Math.abs(y - lastY) > 4) {
        header.classList.toggle("is-hidden", goingDown && y > 160 && mobileNav.hidden);
        lastY = y;
      }
      if (progress && reading) {
        const r = reading.getBoundingClientRect();
        const total = r.height - innerHeight * 0.6;
        progress.style.transform = `scaleX(${Math.min(1, Math.max(0, -r.top / Math.max(1, total)))})`;
      }
      ticking = false;
    };
    addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    header.addEventListener("focusin", () => header.classList.remove("is-hidden"));
  }

  /* ── Copy link ─────────────────────────────────────────────────────────── */

  $$("[data-copy-link]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(location.href.split("#")[0]);
        btn.classList.add("is-done");
        btn.setAttribute("aria-label", "Link copied");
        setTimeout(() => { btn.classList.remove("is-done"); btn.setAttribute("aria-label", "Copy link"); }, 1600);
      } catch { /* clipboard blocked */ }
    })
  );

  /* ── Search index (shared by search, suggestions, previews, random) ──── */

  let indexPromise;
  const loadIndex = () =>
    (indexPromise ||= fetch(`${base}/search.json`).then((r) => (r.ok ? r.json() : [])).catch(() => []));
  const norm = (s) => String(s || "").normalize("NFKC").toLowerCase();

  function search(items, query, kinds) {
    const q = norm(query).trim();
    if (!q) return [];
    const scored = [];
    for (const it of items) {
      if (kinds && !kinds.includes(it.k)) continue;
      const title = norm(it.t);
      const aliases = (it.a || []).map(norm);
      let score = 0;
      if (title === q || aliases.includes(q)) score = 100;
      else if (title.startsWith(q) || aliases.some((a) => a.startsWith(q))) score = 80;
      else if (title.includes(q) || aliases.some((a) => a.includes(q))) score = 60;
      else if (norm(it.d).includes(q)) score = 35;
      else if (norm(it.s).includes(q)) score = 20;
      if (score) scored.push([score, it]);
    }
    return scored.sort((a, b) => b[0] - a[0] || a[1].t.localeCompare(b[1].t)).slice(0, 12).map((x) => x[1]);
  }

  /** Wires an input to a results list with arrow-key navigation. */
  function bindResults(input, list, render, { kinds, onEmpty } = {}) {
    let active = -1;
    const links = () => $$("a", list);
    const setActive = (i) => {
      const all = links();
      active = all.length ? (i + all.length) % all.length : -1;
      all.forEach((a, n) => a.setAttribute("aria-selected", String(n === active)));
      all[active]?.scrollIntoView({ block: "nearest" });
    };
    const run = async () => {
      const results = search(await loadIndex(), input.value, kinds);
      list.innerHTML = results.length ? results.map(render).join("") : input.value.trim() ? onEmpty(input.value) : "";
      active = -1;
      if (results.length) setActive(0);
      list.dispatchEvent(new Event("results"));
    };
    input.addEventListener("input", run);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter") {
        const target = links()[active];
        if (target) { e.preventDefault(); location.href = target.href; }
      }
    });
    return run;
  }

  // Global search overlay
  const dlg = $("[data-search]");
  if (dlg) {
    const input = $("[data-search-input]", dlg);
    const list = $("[data-search-results]", dlg);
    const run = bindResults(input, list, (it) => `
      <li><a href="${esc(it.u)}" role="option">
        <span class="label sr-kind">${esc(it.k)}</span>
        <span class="sr-title">${esc(it.t)}</span>
        <span class="sr-desc">${esc(it.d || it.s)}</span>
      </a></li>`, { onEmpty: (q) => `<li class="search-empty">Nothing found for “${esc(q)}”.</li>` });
    const open = (query = "") => {
      if (!dlg.open) dlg.showModal();
      input.value = query;
      input.focus();
      loadIndex();
      if (query) run();
    };
    // type=search clears itself on the first Esc; close the dialog instead
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); dlg.close(); } });
    $$("[data-search-open]").forEach((b) => b.addEventListener("click", () => open()));
    $("[data-search-close]", dlg).addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => { input.value = ""; list.innerHTML = ""; });
    document.addEventListener("keydown", (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        open();
      }
    });
  }

  // Archive search box with Wikipedia-style suggestions
  const wikiForm = $("[data-wiki-search]");
  if (wikiForm) {
    const input = $("input", wikiForm);
    const list = $(".wiki-suggest", wikiForm);
    bindResults(input, list, (it) => `
      <li><a href="${esc(it.u)}" role="option">
        <span class="sg-thumb">${it.i ? `<img src="${esc(it.i)}" alt="">` : ""}</span>
        <span class="sg-title">${esc(it.t)}</span>
        <span class="sg-desc">${esc(it.d || it.s)}</span>
      </a></li>`, { kinds: ["Archive"], onEmpty: (q) => `<li class="sg-empty">No entry called “${esc(q)}”.</li>` });
    list.addEventListener("results", () => { list.hidden = !list.children.length; });
    input.addEventListener("focus", loadIndex);
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") list.hidden = true; });
    document.addEventListener("click", (e) => { if (!wikiForm.contains(e.target)) list.hidden = true; });
    wikiForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const [first] = search(await loadIndex(), input.value);
      if (first) location.href = first.u;
    });
  }

  // Random entry
  $$("[data-random]").forEach((a) =>
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const entries = (await loadIndex()).filter((it) => it.k === "Archive" && it.u !== location.pathname);
      if (entries.length) location.href = entries[Math.floor(Math.random() * entries.length)].u;
    })
  );

  /* ── Link previews: hover an Archive link to see its summary ───────────── */

  if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let card, current, showTimer, hideTimer;
    const hide = () => { card?.classList.remove("is-visible"); current = null; };
    const show = async (link) => {
      const items = await loadIndex();
      const path = link.getAttribute("href").split("#")[0];
      const it = items.find((x) => x.u === path);
      if (!it || current !== link) return;
      if (!card) {
        card = document.createElement("div");
        card.className = "preview";
        card.addEventListener("mouseenter", () => clearTimeout(hideTimer));
        card.addEventListener("mouseleave", () => { hideTimer = setTimeout(hide, 200); });
        document.body.append(card);
      }
      card.innerHTML = `
        ${it.i ? `<span class="preview-img"><img src="${esc(it.i)}" alt=""></span>` : ""}
        <span class="preview-body">
          <span class="label preview-kind">${esc(it.k === "Archive" ? "Archive entry" : it.k)}${it.d ? " · " + esc(it.d) : ""}</span>
          <span class="preview-title">${esc(it.t)}</span>
          <p class="preview-text">${esc(it.s)}</p>
        </span>
        <a class="preview-foot label" href="${esc(it.u)}"><span>Open entry</span><span aria-hidden="true">→</span></a>`;
      const r = link.getBoundingClientRect();
      const width = 340;
      const left = Math.max(8, Math.min(r.left, innerWidth - width - 8)) + scrollX;
      card.style.left = `${left}px`;
      card.style.top = "0px";
      card.classList.add("is-visible");
      const h = card.offsetHeight;
      const below = r.bottom + 10;
      const top = below + h > innerHeight && r.top - h - 10 > 0 ? r.top - h - 10 : below;
      card.style.top = `${top + scrollY}px`;
    };
    document.addEventListener("mouseover", (e) => {
      const link = e.target.closest?.("a.wikilink:not(.new)");
      if (!link || link === current) return;
      clearTimeout(showTimer);
      clearTimeout(hideTimer);
      current = link;
      showTimer = setTimeout(() => show(link), 380);
    });
    document.addEventListener("mouseout", (e) => {
      const link = e.target.closest?.("a.wikilink");
      if (!link || link.contains(e.relatedTarget) || card?.contains(e.relatedTarget)) return;
      clearTimeout(showTimer);
      hideTimer = setTimeout(hide, 200);
    });
    addEventListener("scroll", () => { if (card?.classList.contains("is-visible")) hide(); }, { passive: true });
  }

  /* ── YouTube: load the player only when asked ──────────────────────────── */

  document.addEventListener("click", (e) => {
    const box = e.target.closest?.("[data-yt]");
    if (!box || box.classList.contains("is-playing")) return;
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(box.dataset.yt)}?autoplay=1&rel=0&playsinline=1`;
    iframe.title = box.dataset.title || "YouTube video";
    iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    iframe.allowFullscreen = true;
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    box.replaceChildren(iframe);
    box.classList.add("is-playing");
  });
  // maxresdefault doesn't exist for every video; YouTube then serves a 120×90 placeholder
  $$("img[data-yt-thumb]").forEach((img) => {
    const fallback = () => { if (img.src.includes("maxresdefault")) img.src = img.src.replace("maxresdefault", "hqdefault"); };
    const check = () => { if (img.naturalWidth && img.naturalWidth <= 120) fallback(); };
    img.addEventListener("error", fallback, { once: true });
    if (img.complete) check(); else img.addEventListener("load", check, { once: true });
  });

  /* ── Archive: contents sidebar ─────────────────────────────────────────── */

  const toc = $("[data-toc]");
  if (toc) {
    if (innerWidth <= 1000) toc.removeAttribute("open");
    const links = $$("a[href^='#']", toc);
    const targets = links
      .map((a) => [a, document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)))])
      .filter(([, el]) => el);
    let raf = 0;
    const mark = () => {
      raf = 0;
      let current = targets[0]?.[0];
      for (const [a, el] of targets) if (el.getBoundingClientRect().top < 120) current = a;
      links.forEach((a) => a.classList.toggle("is-active", a === current));
    };
    addEventListener("scroll", () => { raf ||= requestAnimationFrame(mark); }, { passive: true });
    mark();
  }

  /* ── Gallery: filters and lightbox ─────────────────────────────────────── */

  const galleryData = $("#gallery-data");
  if (galleryData) {
    const works = JSON.parse(galleryData.textContent);
    const items = $$(".work");
    const box = $("[data-lightbox]");
    const el = (name) => $(`[data-lb-${name}]`, box);
    let order = works.map((_, i) => i);
    let pos = 0;

    const render = () => {
      const w = works[order[pos]];
      el("img").src = w.image;
      el("img").alt = w.alt || w.title;
      el("id").textContent = `work ( ${w.id} )`;
      el("count").textContent = `${pos + 1} / ${order.length}`;
      el("title").textContent = w.title;
      el("meta").textContent = [w.medium, w.date].filter(Boolean).join(" · ");
      el("desc").innerHTML = w.html;
      el("entries").innerHTML = w.entries.map((e) => `<li><a class="chip" href="${esc(e.url)}">${esc(e.title)}</a></li>`).join("");
      history.replaceState(null, "", `#w-${w.id}`);
    };
    const open = (index) => {
      order = items.map((li, i) => (li.hidden ? -1 : i)).filter((i) => i >= 0);
      pos = Math.max(0, order.indexOf(index));
      render();
      if (!box.open) box.showModal();
    };
    const step = (d) => { pos = (pos + d + order.length) % order.length; render(); };

    $$("[data-work]").forEach((btn) => btn.addEventListener("click", () => open(Number(btn.dataset.work))));
    el("prev").addEventListener("click", () => step(-1));
    el("next").addEventListener("click", () => step(1));
    el("close").addEventListener("click", () => box.close());
    box.addEventListener("close", () => history.replaceState(null, "", location.pathname + location.search));
    box.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
    });
    const fromHash = works.findIndex((w) => `#w-${w.id}` === location.hash);
    if (fromHash >= 0) open(fromHash);

    $$("[data-filter]").forEach((chip) =>
      chip.addEventListener("click", () => {
        const f = chip.dataset.filter;
        $$("[data-filter]").forEach((c) => {
          c.classList.toggle("is-active", c === chip);
          c.setAttribute("aria-pressed", String(c === chip));
        });
        items.forEach((li) => { li.hidden = f !== "all" && !li.dataset.tags.split(" ").includes(f); });
      })
    );
  }
})();
