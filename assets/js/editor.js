/* Local writing room. Source files remain the single saved manuscript. */
(() => {
  "use strict";
  const editor = document.querySelector("[data-editor]");
  if (!editor) return;
  const $ = (selector) => editor.querySelector(selector);
  const $$ = (selector) => [...editor.querySelectorAll(selector)];
  const base = document.documentElement.dataset.base || "";
  const form = $("[data-editor-form]");
  const input = (name) => form.elements.namedItem(name);
  const status = $("[data-save-status]");
  const saveButton = $("[data-save]");
  const bookSelect = $("[data-book-select]");
  const error = $("[data-editor-error]");
  let books = [], current = null, saved = "", saving = false, loading = false;
  let view = "write", previewTimer, previewSequence = 0, recovery = null, loadSequence = 0;
  let cacheAvailable = true;

  async function api(path, payload) {
    const response = await fetch(`${base}/__editor/api/${path}`, payload === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json", "X-Insignia-Editor": "1" },
      body: JSON.stringify(payload),
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error("편집 서버에 연결할 수 없습니다. 로컬 서버를 확인해 주세요."); }
    if (!response.ok) throw new Error(result.error || "처리하지 못했습니다. 다시 시도해 주세요.");
    return result;
  }

  function showError(message = "") {
    error.textContent = message;
    error.hidden = !message;
  }

  function fields() {
    const result = { title: input("title").value };
    const keys = current.kind === "chapter"
      ? ["alternate_title", "subtitle", "date", "body"]
      : ["author", "genres", "status", "cover", "synopsis"];
    for (const key of keys) result[key] = input(key).value;
    result.draft = input(current.kind === "chapter" ? "draft" : "book_draft").checked;
    if (current.kind === "book") result.subtitle = input("book_subtitle").value;
    return result;
  }

  const signature = () => JSON.stringify(fields());
  const dirty = () => current && signature() !== saved;
  const draftKey = () => `insignia:manuscript:${current.book}:${current.new ? "new" : current.chapter || "book"}`;
  const cache = {
    get() { try { return JSON.parse(localStorage.getItem(draftKey())); } catch { return null; } },
    remove() { try { localStorage.removeItem(draftKey()); } catch { /* Storage may be disabled. */ } },
    write() {
      if (!current || recovery || loading || saving) return;
      try {
        if (dirty()) localStorage.setItem(draftKey(), JSON.stringify({ fields: fields(), revision: current.revision }));
        else this.remove();
        cacheAvailable = true;
      } catch { cacheAvailable = false; $("[data-editor-hint]").textContent = "임시 보관을 사용할 수 없습니다. 저장해 주세요."; }
    },
  };

  function setFields(values) {
    for (const element of form.elements) {
      if (!element.name) continue;
      const key = element.name === "book_subtitle" ? "subtitle" : element.name === "book_draft" ? "draft" : element.name;
      if (element.type === "checkbox") element.checked = Boolean(values[key]);
      else element.value = values[key] ?? "";
    }
  }

  function updateStatus(message) {
    if (!current) return;
    const changed = dirty();
    status.textContent = saving ? "저장하는 중…" : message || (recovery ? "임시 원고 복구 가능" : changed ? "저장하지 않은 변경" : current.new ? "새 초안" : "저장됨");
    status.classList.toggle("is-dirty", changed && !saving);
    $("[data-delete-document]").disabled = saving || loading || Boolean(recovery);
    saveButton.disabled = saving || loading || Boolean(recovery) || (!changed && !current.new);
    bookSelect.disabled = saving || loading;
    $("[data-new-chapter]").disabled = saving || loading;
    $("[data-book-info]").disabled = saving || loading;
    $$("[data-chapter-list] button").forEach((button) => { button.disabled = saving || loading; });
    const body = fields()[current.kind === "chapter" ? "body" : "synopsis"] || "";
    $("[data-word-count]").textContent = `${[...body].length.toLocaleString("ko-KR")}자 · 공백 제외 ${[...body.replace(/\s/g, "")].length.toLocaleString("ko-KR")}자`;
  }

  function renderLibrary() {
    bookSelect.replaceChildren(...books.map((book) => {
      const option = document.createElement("option");
      option.value = book.id;
      option.textContent = (book.draft ? "[비공개] " : "") + book.title + (book.subtitle ? ` · ${book.subtitle}` : "");
      return option;
    }));
    if (current) bookSelect.value = current.book;
    const book = books.find((item) => item.id === bookSelect.value);
    const list = $("[data-chapter-list]");
    list.replaceChildren();
    const chapters = book?.chapters || [];
    $("[data-chapter-count]").textContent = String(chapters.length).padStart(2, "0");
    for (const chapter of chapters) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "editor-chapter";
      if (current?.chapter === chapter.id && !current.new) button.setAttribute("aria-current", "page");
      const number = document.createElement("span"), title = document.createElement("span"), tag = document.createElement("small");
      number.className = "label";
      number.textContent = chapter.number;
      title.textContent = chapter.title;
      tag.textContent = chapter.draft ? "초안" : "";
      button.append(number, title, tag);
      button.addEventListener("click", () => navigate(book.id, chapter.id));
      list.append(button);
    }
    if (!chapters.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "첫 챕터를 써보세요.";
      list.append(empty);
    }
    $("[data-book-info]").toggleAttribute("aria-current", current?.kind === "book");
  }

  function switchView(next) {
    view = next;
    previewSequence++;
    $("[data-write-pane]").hidden = view !== "write";
    $("[data-preview-pane]").hidden = view !== "preview";
    $$("[data-editor-view]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.editorView === view)));
    if (view === "preview" && current) renderPreview();
  }

  function display(doc, { checkRecovery = true } = {}) {
    current = doc;
    $("[data-delete-document]").hidden = Boolean(doc.new);
    recovery = null;
    form.reset();
    form.querySelectorAll("input, textarea").forEach((element) => { element.disabled = false; });
    setFields(doc.fields);
    $("[data-chapter-fields]").hidden = doc.kind !== "chapter";
    $("[data-book-fields]").hidden = doc.kind !== "book";
    $("[data-chapter-fields]").querySelectorAll("input, textarea").forEach((element) => { element.disabled = doc.kind !== "chapter"; });
    $("[data-book-fields]").querySelectorAll("input, textarea").forEach((element) => { element.disabled = doc.kind !== "book"; });
    saved = signature();
    form.hidden = false;
    $("[data-editor-loading]").hidden = true;
    $("[data-document-label]").textContent = doc.kind === "book" ? "BOOK INFORMATION / 책 정보" : doc.new ? "NEW CHAPTER / 새로운 이야기" : "MANUSCRIPT / 챕터 원고";
    const link = $("[data-read-link]");
    link.hidden = !doc.read_url;
    if (doc.read_url) link.href = doc.read_url;
    $("[data-editor-hint]").textContent = "Ctrl + S로 저장";
    if (checkRecovery) {
      const candidate = cache.get();
      if (candidate?.fields && JSON.stringify(candidate.fields) !== saved) recovery = candidate;
    }
    $("[data-recovery]").hidden = !recovery;
    if (recovery) form.querySelectorAll("input, textarea").forEach((element) => { element.disabled = true; });
    renderLibrary();
    const params = new URLSearchParams({ book: doc.book });
    if (doc.new) params.set("new", "1");
    else if (doc.chapter) params.set("chapter", doc.chapter);
    history.replaceState(null, "", `${base}/editor/?${params}`);
    switchView("write");
    updateStatus();
  }

  async function canLeave() {
    if (saving || loading) return false;
    if (!dirty()) return true;
    cache.write();
    const dialog = $("[data-leave-dialog]");
    dialog.querySelector("p").textContent = cacheAvailable
      ? "변경 내용을 아직 저장하지 않았습니다. 임시 원고는 이 브라우저에 보관됩니다."
      : "임시 보관을 사용할 수 없습니다. 이동하면 변경 내용이 사라집니다. 계속 편집하여 먼저 저장해 주세요.";
    $("[data-leave]").disabled = !cacheAvailable;
    dialog.returnValue = "stay";
    dialog.showModal();
    return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "leave"), { once: true }));
  }

  async function navigate(book, chapter = null) {
    if (!await canLeave()) { bookSelect.value = current.book; return; }
    showError();
    loading = true;
    const sequence = ++loadSequence;
    updateStatus("불러오는 중…");
    try {
      const query = new URLSearchParams({ book });
      if (chapter) query.set("chapter", chapter);
      const doc = await api(`document?${query}`);
      if (sequence === loadSequence) display(doc);
    } catch (reason) {
      showError(reason.message);
      if (current) bookSelect.value = current.book;
    } finally { loading = false; updateStatus(); }
  }

  const escape = (value) => String(value || "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  async function renderPreview() {
    const sequence = ++previewSequence;
    const values = fields();
    const previewStatus = $("[data-preview-status]");
    previewStatus.textContent = "미리보기를 만드는 중…";
    try {
      const result = await api("preview", { kind: current.kind, fields: values });
      if (sequence !== previewSequence) return;
      const theme = document.documentElement.dataset.theme;
      const stylesheet = document.querySelector('link[href*="/assets/site.css"]').href;
      const fonts = document.querySelector('link[href*="fonts.googleapis.com/css"]')?.href;
      const origin = location.origin;
      const preview = `<!doctype html><html lang="ko" data-theme="${escape(theme)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><base href="${escape(origin + base)}/" target="_blank"><link rel="stylesheet" href="${escape(stylesheet)}">${fonts ? `<link rel="stylesheet" href="${escape(fonts)}">` : ""}<style>body{display:block;min-height:0} .reader{padding:24px 20px 48px} .reader-title{font-size:32px;line-height:1.4}.reader-subtitle{font-size:18px}.prose{margin-top:28px;font-size:18px;line-height:1.9}</style></head><body class="mode-reader"><article class="reader"><h1 class="reader-title">${escape(values.title) || "제목 없는 이야기"}</h1>${values.alternate_title ? `<p class="reader-alternate-title">${escape(values.alternate_title)}</p>` : ""}${values.subtitle ? `<p class="reader-subtitle">${escape(values.subtitle)}</p>` : ""}<div class="prose">${result.html || '<p style="color:var(--ink-3)">이야기가 시작될 자리입니다.</p>'}</div>${result.notes ? `<section class="reader-notes">${result.notes}</section>` : ""}</article></body></html>`;
      $("[data-preview-frame]").srcdoc = preview;
      previewStatus.textContent = `읽기 약 ${result.minutes}분 · 저장하기 전의 미리보기입니다.`;
    } catch (reason) {
      if (sequence === previewSequence) previewStatus.textContent = reason.message;
    }
  }

  form.addEventListener("input", () => {
    updateStatus();
    cache.write();
    if (view === "preview") { clearTimeout(previewTimer); previewTimer = setTimeout(renderPreview, 500); }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current || saving || loading || recovery || (!dirty() && !current.new)) return;
    if (!form.checkValidity()) { switchView("write"); form.reportValidity(); return; }
    cache.write();
    saving = true;
    showError();
    updateStatus();
    const oldKey = draftKey();
    const submitted = fields();
    form.querySelectorAll("input, textarea").forEach((element) => { element.readOnly = true; });
    input("draft").disabled = true;
    try {
      const result = await api("save", { book: current.book, chapter: current.chapter, new: Boolean(current.new), revision: current.revision, fields: submitted });
      try { localStorage.removeItem(oldKey); } catch { /* Storage may be disabled. */ }
      books = result.books;
      display(result.document, { checkRecovery: false });
      const time = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
      status.textContent = `저장됨 · ${time}`;
    } catch (reason) { showError(reason.message); }
    finally {
      saving = false;
      form.querySelectorAll("input, textarea").forEach((element) => { element.readOnly = false; });
      input("draft").disabled = current.kind !== "chapter";
      updateStatus(error.hidden ? status.textContent : "저장 실패 · 원고 유지됨");
    }
  });

  bookSelect.addEventListener("change", () => navigate(bookSelect.value));
  $("[data-book-info]").addEventListener("click", () => navigate(bookSelect.value));
  $("[data-new-chapter]").addEventListener("click", async () => {
    if (!await canLeave()) return;
    showError();
    display({ book: bookSelect.value, chapter: null, kind: "chapter", new: true, revision: null, read_url: null,
      fields: { title: "", alternate_title: "", subtitle: "", date: "", draft: true, body: "" } });
    if (!recovery) input("title").focus();
  });
  $$("[data-editor-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.editorView)));
  $("[data-stay]").addEventListener("click", () => $("[data-leave-dialog]").close("stay"));
  $("[data-leave]").addEventListener("click", () => $("[data-leave-dialog]").close("leave"));
  $("[data-restore]").addEventListener("click", () => {
    const recovered = recovery;
    const doc = { ...current, fields: fields() };
    display(doc, { checkRecovery: false });
    setFields(recovered.fields);
    if (recovered.revision !== current.revision) {
      current.revision = recovered.revision;
      showError("임시 원고를 복구했습니다. 원본도 변경되어 있으므로 저장 전 내용을 복사해 비교해 주세요.");
    }
    updateStatus("임시 원고 복구됨 · 저장 필요");
    cache.write();
  });
  $("[data-discard]").addEventListener("click", () => {
    cache.remove();
    display({ ...current, fields: fields() }, { checkRecovery: false });
  });

  $$("[data-format]").forEach((button) => button.addEventListener("click", () => {
    if (saving || loading || recovery) return;
    const body = input("body"), start = body.selectionStart, end = body.selectionEnd;
    const selection = body.value.slice(start, end);
    const wrappers = { bold: ["**", "**", "강조할 문장"], italic: ["*", "*", "기울일 문장"],
      heading: ["\n\n## ", "\n", "소제목"], quote: ["\n\n> ", "\n", "인용할 문장"],
      break: ["\n\n---\n\n", "", ""], link: ["[[", "]]", "아카이브 항목"] };
    const [before, after, placeholder] = wrappers[button.dataset.format];
    const content = selection || placeholder;
    body.setRangeText(before + content + after, start, end, "end");
    body.focus();
    body.setSelectionRange(start + before.length, start + before.length + content.length);
    body.dispatchEvent(new Event("input", { bubbles: true }));
  }));
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (!saveButton.disabled) form.requestSubmit();
    }
  });
  $("[data-delete-document]").addEventListener("click", async () => {
    if (!current || current.new || saving || loading) return;
    if (!window.confirm(`‘${current.fields.title}’을 휴지통으로 이동할까요? 외부 공개가 중단되며, 관리 화면에서 비공개로 복원할 수 있습니다.`)) return;
    saving = true; updateStatus(); showError();
    try {
      await api("content/trash", { kind: current.kind === "book" ? "books" : "chapters", id: current.book + (current.chapter ? "/" + current.chapter : ""), revision: current.revision, action: "trash" });
      current = null; saving = false; location.assign(base + "/editor/manage/?section=trash");
    } catch (reason) { showError(reason.message); saving = false; updateStatus(); }
  });
  addEventListener("beforeunload", (event) => {
    if (dirty()) {
      cache.write();
      if (!cacheAvailable) { event.preventDefault(); event.returnValue = ""; }
    }
  });
  new MutationObserver(() => { if (view === "preview") renderPreview(); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  (async () => {
    try {
      books = (await api("library")).books;
      if (!books.length) throw new Error("편집할 책이 없습니다. 먼저 책을 추가해 주세요.");
      renderLibrary();
      const params = new URLSearchParams(location.search);
      const book = books.find((item) => item.id === params.get("book")) || books[0];
      if (params.get("new") === "1") {
        display({ book: book.id, chapter: null, kind: "chapter", new: true, revision: null, read_url: null,
          fields: { title: "", alternate_title: "", subtitle: "", date: "", draft: true, body: "" } });
      } else {
        const query = new URLSearchParams({ book: book.id });
        if (params.get("chapter")) query.set("chapter", params.get("chapter"));
        display(await api(`document?${query}`));
      }
    } catch (reason) {
      showError(reason.message);
      $("[data-editor-loading]").textContent = "원고를 불러오지 못했습니다. 페이지를 새로고침해 주세요.";
      status.textContent = "연결 실패";
    }
  })();
})();
