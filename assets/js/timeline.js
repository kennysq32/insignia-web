/* Private chronology canvas. Content is always rendered as text, never HTML. */
(() => {
  "use strict";
  const studio = document.querySelector("[data-timeline]");
  if (!studio) return;
  const $ = (selector) => studio.querySelector(selector);
  const base = document.documentElement.dataset.base || "";
  const viewport = $("[data-viewport]"), world = $("[data-world]");
  const form = $("[data-event-form]"), fields = $("[data-form-fields]");
  const workspace = $(".tl-workspace"), error = $("[data-timeline-error]");
  const input = (name) => form.elements.namedItem(name);
  const COLUMN = 390, CARD_STEP = 180, CARD_TOP = 224;
  const VERTICAL_WIDTH = 640, VERTICAL_CARD_LEFT = 230, VERTICAL_CARD_TOP = 24, VERTICAL_CARD_WIDTH = 380;
  let layout = "horizontal";
  try { if (localStorage.getItem("insignia:timeline:view") === "vertical") layout = "vertical"; } catch { /* Preferences are optional. */ }
  const cameras = {};
  let board = null, selected = null, baseline = "", busy = false, loaded = false, conflicted = false;
  let groups = [], positions = new Map(), worldWidth = 390, worldHeight = 600;
  let camera = { x: 32, y: 12, scale: 1 }, currentYear = null, filterTimer;
  const pointers = new Map();
  let gesture = null;

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function formValue() {
    return { title: input("title").value, year: input("year").value, month: input("month").value,
      day: input("day").value, date_label: input("date_label").value,
      description: input("description").value, color: input("color").value };
  }
  const dirty = () => loaded && JSON.stringify(formValue()) !== baseline;
  const canLeave = () => !busy && (!dirty() || confirm("저장하지 않은 사건의 변경 사항을 버릴까요?"));
  function status(message, failed = false) {
    $("[data-save-state]").textContent = message;
    $("[data-save-state]").classList.toggle("is-error", failed);
  }
  function showError(message = "", login = false) {
    error.hidden = !message;
    $("[data-error-message]").textContent = message;
    $("[data-login]").hidden = !login;
  }
  function lock(value) {
    busy = value;
    fields.disabled = value || !loaded;
    $("[data-save-event]").disabled = value || !loaded || conflicted;
    $("[data-delete-event]").disabled = value || !loaded || conflicted;
    $("[data-add]").disabled = value || !loaded;
    $("[data-mobile-add]").disabled = value || !loaded;
    $("[data-empty-add]").disabled = value || !loaded;
    $("[data-rename]").disabled = value || !loaded || conflicted;
    $("[data-reload]").disabled = value;
  }
  async function api(path, payload) {
    let response;
    try {
      response = await fetch(`${base}/__editor/api/timeline${path}`, {
        credentials: "same-origin", redirect: "error", cache: "no-store",
        ...(payload ? { method: "POST", headers: { "Content-Type": "application/json", "X-Insignia-Editor": "1" }, body: JSON.stringify(payload) } : {}),
      });
    } catch { throw new Error("편집 서버 연결이 끊겼습니다. 입력 내용은 유지됩니다. 서버와 로그인을 확인하고 다시 시도해 주세요."); }
    let result;
    try { result = await response.json(); }
    catch { throw new Error("편집 서버에 연결할 수 없습니다. 서버 실행 상태와 로그인을 확인해 주세요."); }
    if (!response.ok) {
      const failure = new Error(result.error || "타임라인을 처리하지 못했습니다.");
      failure.status = response.status;
      throw failure;
    }
    return result;
  }
  function failed(failure) {
    if (failure.status === 409) conflicted = true;
    showError(failure.message || "연결이 끊겼습니다. 입력 내용은 유지됩니다. 다시 시도해 주세요.", [401, 403].includes(failure.status));
    status(conflicted ? "저장 충돌 · 새로 불러오기 필요" : "저장되지 않음", true);
  }
  function dateText(event, withYear = false) {
    if (event.date_label) return event.date_label;
    if (event.month === null) return `${event.year}년`;
    const text = `${String(event.month).padStart(2, "0")}${event.day === null ? "" : `.${String(event.day).padStart(2, "0")}`}`;
    return withYear ? `${event.year}년 ${event.month}월${event.day === null ? "" : ` ${event.day}일`}` : text;
  }
  function inspector(open) {
    workspace.classList.toggle("inspector-closed", !open);
    $("[data-toggle-inspector]").setAttribute("aria-expanded", String(open));
    requestAnimationFrame(applyCamera);
  }
  function setForm(event = null, year = "") {
    selected = event?.id || null;
    form.reset();
    for (const key of ["title", "year", "month", "day", "date_label", "description"]) {
      input(key).value = event ? (event[key] ?? "") : ({ year, month: 1 }[key] ?? "");
    }
    input("color").value = event?.color || "red";
    $("[data-form-eyebrow]").textContent = event ? "EDIT EVENT" : "NEW EVENT";
    $("[data-form-title]").textContent = event ? "사건 편집" : "사건 추가";
    $("[data-delete-event]").hidden = !event;
    $("[data-event-source]").hidden = !event?.source_url;
    if (event?.source_url) $("[data-source-link]").href = event.source_url;
    $("[data-save-event]").firstChild.textContent = event ? "변경 사항 저장 " : "사건 저장 ";
    validateDay();
    baseline = JSON.stringify(formValue());
    for (const card of world.querySelectorAll(".tl-event")) {
      card.classList.toggle("is-selected", card.dataset.eventId === selected);
      card.setAttribute("aria-pressed", String(card.dataset.eventId === selected));
    }
  }
  function addEvent(year = currentYear ?? board?.events.at(-1)?.year ?? "") {
    if (!loaded || !canLeave()) return;
    setForm(null, year);
    inspector(true);
    input("title").focus();
    if (!conflicted) status("새 사건 작성 중");
  }
  function chooseEvent(id, navigate = false) {
    if (!loaded || (selected !== id && !canLeave())) return;
    const event = board.events.find((item) => item.id === id);
    if (!event) return;
    if (selected !== id) setForm(event);
    inspector(true);
    if (navigate) requestAnimationFrame(() => focusEvent(id));
    if (!conflicted) status(dirty() ? "저장하지 않은 변경" : "모든 변경 사항 저장됨");
  }
  function matchingEvents() {
    const query = $("[data-event-search]").value.trim().toLocaleLowerCase();
    return board.events.filter((event) => !query || `${event.title} ${event.description} ${dateText(event, true)}`.toLocaleLowerCase().includes(query));
  }
  function updateLayout() {
    studio.dataset.layout = layout;
    for (const button of studio.querySelectorAll("[data-layout]")) {
      button.setAttribute("aria-pressed", String(button.dataset.layout === layout));
    }
    viewport.setAttribute("aria-label", layout === "vertical"
      ? "세로 타임라인 캔버스. 휠로 위아래 이동하고 Ctrl+휠로 확대·축소합니다."
      : "가로 타임라인 캔버스. 빈 공간을 드래그해 이동하고 휠로 확대·축소합니다.");
    $(".tl-canvas-help").textContent = layout === "vertical"
      ? "휠로 위아래 이동 · Ctrl+휠 확대/축소 · F 전체 보기"
      : "드래그로 이동 · 휠로 확대/축소 · F 전체 보기";
  }
  function resetView() {
    if (layout === "horizontal") { fit(); return; }
    camera.scale = Math.min(1, Math.max(.05, (viewport.clientWidth - 32) / VERTICAL_WIDTH));
    camera.x = (viewport.clientWidth - VERTICAL_WIDTH * camera.scale) / 2;
    camera.y = 20;
    applyCamera();
  }
  function setLayout(next) {
    if (next === layout || !["horizontal", "vertical"].includes(next)) return;
    cameras[layout] = { ...camera };
    layout = next;
    updateLayout();
    try { localStorage.setItem("insignia:timeline:view", layout); } catch { /* Storage may be disabled. */ }
    if (!board) return;
    render();
    if (selected && positions.has(selected)) focusEvent(selected);
    else if (cameras[layout]) { camera = { ...cameras[layout] }; applyCamera(); }
    else resetView();
  }
  function render() {
    const events = matchingEvents();
    const byYear = new Map();
    for (const event of events) {
      if (!byYear.has(event.year)) byYear.set(event.year, []);
      byYear.get(event.year).push(event);
    }
    const vertical = layout === "vertical";
    let nextY = 0;
    groups = [...byYear].map(([year, rows], index) => {
      const group = { year, rows, x: vertical ? 0 : index * COLUMN, y: vertical ? nextY : 0,
        height: VERTICAL_CARD_TOP + rows.length * CARD_STEP + 40 };
      nextY += group.height;
      return group;
    });
    worldWidth = vertical ? VERTICAL_WIDTH : Math.max(COLUMN, groups.length * COLUMN);
    worldHeight = vertical ? Math.max(244, nextY)
      : Math.max(540, CARD_TOP + Math.max(0, ...groups.map((group) => group.rows.length)) * CARD_STEP + 36);
    positions = new Map();
    world.replaceChildren();
    const nav = $("[data-year-nav]");
    nav.replaceChildren();
    for (const group of groups) {
      const column = element("section", "tl-year-column");
      column.setAttribute("aria-label", `${group.year}년`);
      column.style.left = `${group.x}px`;
      column.style.top = `${group.y}px`;
      column.style.height = `${vertical ? group.height : worldHeight}px`;
      const year = element("div", `tl-year-watermark${String(group.year).length > 4 ? " is-long" : ""}`, group.year);
      year.setAttribute("aria-hidden", "true");
      const meta = element("div", "tl-column-meta");
      meta.append(element("span", "", `${group.year} YEAR`), element("span", "", `${String(group.rows.length).padStart(2, "0")} EVENTS`));
      const spine = element("div", "tl-spine");
      if (vertical) spine.style.height = `${group === groups.at(-1) ? (group.rows.length - 1) * CARD_STEP : group.height}px`;
      column.append(year, meta, spine);
      for (const [index, event] of group.rows.entries()) {
        const card = element("button", "tl-event");
        card.type = "button";
        card.dataset.eventId = event.id;
        card.dataset.color = event.color;
        const top = (vertical ? VERTICAL_CARD_TOP : CARD_TOP) + index * CARD_STEP;
        card.style.top = `${top}px`;
        card.classList.toggle("is-selected", event.id === selected);
        card.setAttribute("aria-pressed", String(event.id === selected));
        card.setAttribute("aria-label", `${dateText(event, true)}: ${event.title}`);
        const date = element("span", "tl-event-date");
        date.append(element("i"), document.createTextNode(dateText(event)));
        if (event.date_label) date.append(element("small", "", "대략적인 시점"));
        else if (event.month === null) date.append(element("small", "", "월·일 미정"));
        else if (event.day === null) date.append(element("small", "", "일자 미정"));
        card.append(date, element("span", "tl-event-title", event.title), element("span", "tl-event-description", event.description));
        card.addEventListener("click", () => chooseEvent(event.id));
        column.append(card);
        positions.set(event.id, { x: group.x + (vertical ? VERTICAL_CARD_LEFT : 56),
          y: group.y + top, groupY: group.y, width: vertical ? VERTICAL_CARD_WIDTH : 300 });
      }
      world.append(column);
      const jump = element("button", "tl-year-link", `${group.year}`);
      jump.type = "button";
      jump.dataset.year = group.year;
      jump.setAttribute("aria-label", `${group.year}년, ${group.rows.length}개의 사건으로 이동`);
      jump.append(element("span", "", String(group.rows.length).padStart(2, "0")));
      jump.addEventListener("click", () => jumpYear(group.year));
      nav.append(jump);
      if ($("[data-event-search]").value.trim()) {
        for (const event of group.rows) {
          const result = element("button", "tl-search-result", event.title);
          result.type = "button";
          result.addEventListener("click", () => chooseEvent(event.id, true));
          nav.append(result);
        }
      }
    }
    if (!groups.length) nav.append(element("p", "tl-nav-empty", board.events.length ? "일치하는 사건이 없습니다." : "첫 사건을 추가하면\n연도가 여기에 표시됩니다."));
    $("[data-year-count]").textContent = String(groups.length).padStart(2, "0");
    $("[data-event-count]").textContent = `${board.events.length}개의 사건`;
    $("[data-board-name]").textContent = board.title;
    $("[data-empty]").hidden = Boolean(board.events.length);
    $("[data-no-results]").hidden = !board.events.length || Boolean(events.length);
    $("[data-timeline-range]").textContent = board.events.length ? `${board.events[0].year} — ${board.events.at(-1).year}` : "—";
    applyCamera();
  }
  function minScale() {
    return Math.min(.15, Math.max(.00001, (viewport.clientWidth - 64) / worldWidth),
      Math.max(.00001, (viewport.clientHeight - 100) / worldHeight));
  }
  function applyCamera() {
    world.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
    viewport.style.backgroundSize = `${20 * Math.max(.4, camera.scale)}px ${20 * Math.max(.4, camera.scale)}px`;
    viewport.style.backgroundPosition = `${camera.x}px ${camera.y}px`;
    const percent = camera.scale * 100;
    $("[data-zoom-reset]").textContent = `${percent < 1 ? percent.toFixed(1) : Math.round(percent)}%`;
    const vertical = layout === "vertical";
    const center = vertical ? (Math.min(100, viewport.clientHeight / 4) - camera.y) / camera.scale
      : (viewport.clientWidth / 2 - camera.x) / camera.scale;
    const distance = (group) => Math.abs(group.x + COLUMN / 2 - center);
    const nearest = vertical
      ? groups.find((group) => group.y <= center && center < group.y + group.height) || (center < 0 ? groups[0] : groups.at(-1))
      : groups.reduce((best, group) => !best || distance(group) < distance(best) ? group : best, null);
    currentYear = nearest?.year ?? null;
    $("[data-visible-year]").textContent = nearest ? `${nearest.year}년` : "";
    for (const button of $("[data-year-nav]").querySelectorAll("[data-year]")) {
      const active = Number(button.dataset.year) === currentYear;
      button.classList.toggle("is-current", active);
      if (active) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current");
    }
  }
  function zoom(next, x = viewport.clientWidth / 2, y = viewport.clientHeight / 2) {
    const scale = Math.max(minScale(), Math.min(2.2, next));
    camera.x = x - (x - camera.x) * scale / camera.scale;
    camera.y = y - (y - camera.y) * scale / camera.scale;
    camera.scale = scale;
    applyCamera();
  }
  function fit() {
    if (!groups.length) return;
    camera.scale = Math.max(.00001, Math.min(1, (viewport.clientWidth - 64) / worldWidth, (viewport.clientHeight - 100) / worldHeight));
    camera.x = (viewport.clientWidth - worldWidth * camera.scale) / 2;
    camera.y = Math.max(20, (viewport.clientHeight - worldHeight * camera.scale - 45) / 2);
    applyCamera();
  }
  function jumpYear(year) {
    const group = groups.find((item) => item.year === year);
    if (!group) return;
    const width = layout === "vertical" ? VERTICAL_WIDTH : COLUMN;
    camera.scale = Math.min(1, Math.max(.05, (viewport.clientWidth - 32) / width));
    camera.x = (viewport.clientWidth - width * camera.scale) / 2 - group.x * camera.scale;
    camera.y = 20 - group.y * camera.scale;
    applyCamera();
  }
  function focusEvent(id) {
    const point = positions.get(id);
    if (!point) return;
    const width = layout === "vertical" ? VERTICAL_WIDTH : point.width;
    camera.scale = Math.min(1, (viewport.clientWidth - 32) / width);
    camera.x = layout === "vertical" ? (viewport.clientWidth - VERTICAL_WIDTH * camera.scale) / 2
      : viewport.clientWidth / 2 - (point.x + point.width / 2) * camera.scale;
    camera.y = viewport.clientHeight / 2 - (point.y + 79) * camera.scale;
    if (layout === "vertical") camera.y = Math.min(camera.y, 20 - point.groupY * camera.scale);
    applyCamera();
  }
  function validateDay() {
    input("day").disabled = input("month").value === "";
    if (input("day").disabled) input("day").value = "";
    const year = Number(input("year").value), month = Number(input("month").value);
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const max = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] || 31;
    input("day").max = max;
  }
  async function persist(events, title = board.title) {
    lock(true);
    showError();
    status("저장하는 중…");
    try {
      board = await api("/save", { title, events, version: board.version });
      render();
      status("모든 변경 사항 저장됨");
      return true;
    } catch (failure) { failed(failure); return false; }
    finally { lock(false); }
  }
  async function load() {
    lock(true);
    showError();
    status("불러오는 중…");
    try {
      board = await api("");
      loaded = true;
      conflicted = false;
      render();
      setForm();
      if (board.events.length) resetView();
      status("모든 변경 사항 저장됨");
    } catch (failure) { failed(failure); }
    finally { lock(false); }
  }
  form.addEventListener("input", () => {
    validateDay();
    if (!busy && !conflicted) status(dirty() ? "저장하지 않은 변경" : "모든 변경 사항 저장됨");
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !loaded || conflicted || !form.reportValidity()) return;
    const values = formValue();
    const record = { ...board.events.find((item) => item.id === selected), ...values,
      id: selected || crypto.randomUUID(), title: values.title.trim(),
      year: Number(values.year), month: values.month === "" ? null : Number(values.month),
      day: values.day === "" ? null : Number(values.day) };
    if (!record.title) { input("title").setCustomValidity("사건 제목을 입력해 주세요."); input("title").reportValidity(); input("title").setCustomValidity(""); return; }
    const events = board.events.filter((item) => item.id !== record.id).concat(record);
    if (await persist(events)) {
      $("[data-event-search]").value = "";
      render();
      setForm(board.events.find((item) => item.id === record.id));
      if (matchMedia("(max-width: 600px)").matches) inspector(false);
      requestAnimationFrame(() => focusEvent(record.id));
    }
  });
  $("[data-delete-event]").addEventListener("click", async () => {
    if (!selected || busy || conflicted || !confirm("이 사건을 삭제할까요? 저장된 타임라인에서도 삭제됩니다.")) return;
    if (await persist(board.events.filter((item) => item.id !== selected))) {
      setForm();
      if (board.events.length) resetView();
    }
  });
  $("[data-rename]").addEventListener("click", async () => {
    if (busy || !loaded || conflicted) return;
    const title = prompt("타임라인 이름 (최대 120자)", board.title)?.trim();
    if (!title || title === board.title) return;
    if (title.length > 120) { showError("타임라인 이름은 120자 이하로 입력해 주세요."); return; }
    await persist(board.events, title);
    if (dirty()) status("저장하지 않은 사건 변경");
  });
  $("[data-add]").addEventListener("click", () => addEvent());
  $("[data-mobile-add]").addEventListener("click", () => addEvent());
  $("[data-empty-add]").addEventListener("click", () => addEvent());
  $("[data-reload]").addEventListener("click", () => { if (canLeave()) load(); });
  $("[data-toggle-inspector]").addEventListener("click", () => inspector(workspace.classList.contains("inspector-closed")));
  $("[data-zoom-in]").addEventListener("click", () => zoom(camera.scale * 1.2));
  $("[data-zoom-out]").addEventListener("click", () => zoom(camera.scale / 1.2));
  $("[data-zoom-reset]").addEventListener("click", () => zoom(1));
  $("[data-fit]").addEventListener("click", fit);
  for (const button of studio.querySelectorAll("[data-layout]")) {
    button.addEventListener("click", () => setLayout(button.dataset.layout));
  }
  function search() { if (!board) return; render(); resetView(); }
  $("[data-event-search]").addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(search, 120); });
  $("[data-clear-search]").addEventListener("click", () => { $("[data-event-search]").value = ""; search(); });
  viewport.addEventListener("wheel", (event) => {
    if (event.target.closest(".tl-canvas-controls")) return;
    event.preventDefault();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
    if (layout === "vertical" && !event.ctrlKey && !event.metaKey) {
      camera.y -= event.shiftKey ? 0 : event.deltaY * unit;
      camera.x -= (event.shiftKey ? event.deltaY : event.deltaX) * unit;
      applyCamera();
      return;
    }
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      camera.x -= event.shiftKey ? event.deltaY : event.deltaX;
      applyCamera();
    } else {
      const bounds = viewport.getBoundingClientRect();
      const delta = event.deltaY * unit;
      zoom(camera.scale * Math.exp(-Math.max(-400, Math.min(400, delta)) * .0018), event.clientX - bounds.left, event.clientY - bounds.top);
    }
  }, { passive: false });
  function startGesture() {
    const points = [...pointers.values()];
    if (points.length > 1) {
      gesture = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2,
        distance: Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y), camera: { ...camera } };
    } else gesture = points.length ? { ...points[0], camera: { ...camera } } : null;
  }
  viewport.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button, a, .tl-empty-canvas, .tl-no-results") || (event.button !== 0 && event.button !== 1)) return;
    event.preventDefault();
    viewport.focus({ preventScroll: true });
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-panning");
    startGesture();
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = [...pointers.values()];
    if (points.length > 1 && gesture.distance) {
      const bounds = viewport.getBoundingClientRect();
      const x = (points[0].x + points[1].x) / 2, y = (points[0].y + points[1].y) / 2;
      const distance = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
      const scale = Math.max(minScale(), Math.min(2.2, gesture.camera.scale * distance / gesture.distance));
      camera = { scale, x: x - bounds.left - (gesture.x - bounds.left - gesture.camera.x) * scale / gesture.camera.scale,
        y: y - bounds.top - (gesture.y - bounds.top - gesture.camera.y) * scale / gesture.camera.scale };
    } else { camera.x = gesture.camera.x + event.clientX - gesture.x; camera.y = gesture.camera.y + event.clientY - gesture.y; }
    applyCamera();
  });
  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    if (!pointers.size) viewport.classList.remove("is-panning");
    startGesture();
  }
  viewport.addEventListener("pointerup", endPointer);
  viewport.addEventListener("pointercancel", endPointer);
  viewport.addEventListener("keydown", (event) => {
    if (event.target !== viewport || !event.key.startsWith("Arrow")) return;
    event.preventDefault();
    camera.x += event.key === "ArrowLeft" ? 80 : event.key === "ArrowRight" ? -80 : 0;
    camera.y += event.key === "ArrowUp" ? 80 : event.key === "ArrowDown" ? -80 : 0;
    applyCamera();
  });
  document.addEventListener("keydown", (event) => {
    if (event.isComposing || event.target.closest("input, textarea, select, [contenteditable], dialog[open]")) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.toLowerCase() === "n") { event.preventDefault(); addEvent(); }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); fit(); }
    if (event.key === "+" || event.key === "=") { event.preventDefault(); zoom(camera.scale * 1.2); }
    if (event.key === "-") { event.preventDefault(); zoom(camera.scale / 1.2); }
    if (event.key === "Escape" && !busy) inspector(false);
  });
  window.addEventListener("beforeunload", (event) => { if (dirty() || busy) { event.preventDefault(); event.returnValue = ""; } });
  new ResizeObserver(applyCamera).observe(viewport);
  if (matchMedia("(max-width: 600px)").matches) inspector(false);
  updateLayout();
  load();
})();
