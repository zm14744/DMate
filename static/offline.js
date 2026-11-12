(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DB_NAME = "dmate-offline-workspace";
  const DB_VERSION = 2;
  const NOTE_JOURNAL_KEY = "dmate:offline:notebook-journal:v1";
  const state = {
    db: null, concepts: [], questions: [], graph: null,
    panel: "", selectedQuestion: null, selectedConcept: null,
    selectedOption: [], revealed: false, recordKind: "note", editingId: null,
    drawingController: null, backgroundUrl: "", graphCategory: "", questionCategory: "",
    questionDifficulty: "", conceptQuery: "", graphQuery: "", graphController: null,
    selectedNoteId: null, noteQuery: "", noteRows: [], noteSaveQueue: Promise.resolve(),
    questionResponses: new Map(), appearanceQueue: Promise.resolve(),
    notebookController: null, notebookSnapshot: {notes:[],deleted:{}}, mistakeFilter:"all", mistakeSearch:"", mistakeSort:"recent", graphFocus:false
  };
  const panelMeta = {
    mistakes: ["错题本", "在本机查看、整理和复习已保存的错题。"],
    notes: ["笔记本", "把自己的理解、推导和学习记录保存在本机。"],
    drawing: ["绘图", "使用 DMate 图形编辑器，在本机创建和保存数学图形。"],
    graph: ["知识图谱", "浏览离散数学知识点及其前置关系。"],
    questions: ["题库", "按章节和难度练习，查看参考答案与解析。"],
    concepts: ["概念库", "使用简体中文查看定义、解释、例题和易错点。"],
    review: ["学习回顾", "查看保存在本机的学习记录。"]
  };

  function toast(message) {
    const node = $("offlineToast");
    node.textContent = String(message || "操作未完成");
    node.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { node.hidden = true; }, 3600);
  }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function button(text, className, handler) {
    const node = el("button", className || "", text);
    node.type = "button";
    node.addEventListener("click", event => {
      try { Promise.resolve(handler(event)).catch(error => toast(error?.message || "操作未完成")); }
      catch (error) { toast(error?.message || "操作未完成"); }
    });
    return node;
  }
  function action(text, className, handler, icon) {
    const node = button("", className, handler);
    const mark = window.DMateOfflineIcons?.create(icon);
    if (mark) node.append(mark);
    node.append(el("span", "dmate-ui-label", text));
    node.setAttribute("aria-label", text);
    node.title = text;
    return node;
  }
  const escapeHtml = value => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  function configureRenderer() {
    window.DMateAIAnswer?.configure({
      markdownToHtml(value) {
        if (!window.marked?.parse || !window.DOMPurify?.sanitize) return escapeHtml(value).replace(/\n/g, "<br>");
        // Use the online renderer's formula protection and final sanitization:
        // Markdown must not consume LaTeX escapes or create unsafe attributes.
        const segments = [];
        let source = String(value ?? "");
        const stash = math => {
          const token = "\uE000DMATE_MATH_" + segments.length + "_END\uE001";
          segments.push([token, math]);
          return token;
        };
        source = source.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$(?!\$)(?:\\.|[^$\n])+\$/g, stash);
        let html = window.marked.parse(source);
        for (const [token, math] of segments) html = html.split(token).join(escapeHtml(math));
        return window.DOMPurify.sanitize(html);
      },
      async renderMath(target) {
        await window.MathJax?.startup?.promise;
        if (window.MathJax?.typesetPromise) await window.MathJax.typesetPromise([target]);
      }
    });
  }
  function rich(className, value) {
    const node = el("div", className);
    node.setAttribute("data-i18n-content", "");
    if (window.DMateAIAnswer?.render) void window.DMateAIAnswer.render(node, value);
    else node.textContent = String(value ?? "");
    return node;
  }
  function answerDetails(title, value, className = "wrong-answer-details") {
    const details = el("details", className);
    details.append(el("summary", className === "wrong-analysis-details" ? "wrong-analysis-summary" : "wrong-answer-summary", title));
    details.append(rich(className === "wrong-analysis-details" ? "wrong-analysis-body" : "wrong-answer-inner", value));
    details.addEventListener("toggle", () => {
      if (details.open) void window.DMateAIAnswer?.render(details.lastElementChild, value);
    });
    return details;
  }
  async function confirmDelete(owner, title, content) {
    if (!window.DMateDeleteConfirm?.request) { toast("删除确认组件尚未加载，请刷新后重试"); return false; }
    return window.DMateDeleteConfirm.request(owner, {title, body:"删除后无法恢复。", content, confirmText:"删除"});
  }
  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        for (const store of ["mistakes", "notes", "practice", "settings"]) {
          if (!db.objectStoreNames.contains(store)) {
            const objectStore = db.createObjectStore(store, { keyPath: "id" });
            objectStore.createIndex("updatedAt", "updatedAt");
          }
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("无法打开本地学习数据库"));
    });
  }
  function transaction(store, mode, action) {
    return new Promise((resolve, reject) => {
      const tx = state.db.transaction(store, mode);
      const objectStore = tx.objectStore(store);
      let request;
      try { request = action(objectStore); }
      catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = () => reject(tx.error || request?.error || new Error("本地保存失败"));
      tx.onabort = () => reject(tx.error || new Error("本地保存已取消"));
    });
  }
  const all = store => transaction(store, "readonly", os => os.getAll());
  const put = (store, value) => transaction(store, "readwrite", os => os.put(value));
  const remove = (store, id) => transaction(store, "readwrite", os => os.delete(id));
  async function applyOriginalAppearance() {
    let saved = null;
    try { saved = await transaction("settings", "readonly", os => os.get("appearance")); } catch (_) {}
    let settings = saved?.settings || null;
    if (!settings) {
      try { settings = JSON.parse(localStorage.getItem("dmate:offline:appearance:v1") || "null"); } catch (_) {}
    }
    window.DMateOfflineAppearance?.apply(settings || {}, saved?.backgroundBlob || null);
  }

  const stamp = () => new Date().toISOString();
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : "local-" + Date.now() + "-" + Math.random().toString(36).slice(2));

  async function migrateCurrentAccountData() {
    let payload;
    try { payload = JSON.parse(sessionStorage.getItem("dmate_offline_migration_v1") || "null"); }
    catch (_) { payload = null; }
    if (!payload || typeof payload !== "object") return;
    const timestamp = value => {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? Math.max(0, numeric) : Date.parse(value) || 0;
    };
    const toIso = value => new Date(timestamp(value) || Date.now()).toISOString();
    // Apply locally acknowledged edits first. Otherwise the later journal
    // replay could overwrite a newer import or hide newly imported note IDs.
    try {
      const raw = localStorage.getItem(NOTE_JOURNAL_KEY), pending = raw ? JSON.parse(raw) : null;
      if (pending?.version === 1 && Array.isArray(pending.rows) && Array.isArray(pending.snapshot?.notes)) {
        await queueNotebook(pending, raw);
      }
    } catch (error) {
      toast("本机笔记草稿尚未写入，已保留当前内容，稍后重试导入。");
      return;
    }
    const mistakes = new Map((await all("mistakes")).map(row => [row.id, row]));
    for (const item of Array.isArray(payload.wrongQuestions) ? payload.wrongQuestions : []) {
      if (!item || typeof item.question !== "string" || !item.question.trim()) continue;
      const id = String(item.id || uid()), existing = mistakes.get(id);
      if (existing && timestamp(item.updatedAt) <= timestamp(existing.updatedAt)) continue;
      const reference = item.referenceAnswer;
      const answer = item.answer || (typeof reference === "string" ? reference
        : reference && typeof reference === "object" ? (reference.text || reference.answer || JSON.stringify(reference)) : "");
      const row = {
        ...(existing || {}), id,
        title: String(item.category || item.question).slice(0, 72) || "错题",
        statement: item.question,
        answer: String(answer || ""),
        explanation: String(item.analysis || item.solution || ""),
        knowledgePoints: Array.isArray(item.knowledgePoints) ? item.knowledgePoints : [],
        status: item.corrected ? "resolved" : "pending",
        updatedAt: toIso(item.updatedAt)
      };
      await put("mistakes", row); mistakes.set(id, row);
    }
    const notes = new Map((await all("notes")).map(row => [row.id, row]));
    const metadata = await transaction("settings", "readonly", os => os.get("notebook-deletions"));
    const deleted = metadata?.deleted || {};
    for (const note of Array.isArray(payload.notes) ? payload.notes : []) {
      if (!note || typeof note.title !== "string" || typeof note.content !== "string") continue;
      const id = String(note.id || uid()), existing = notes.get(id), incomingAt = timestamp(note.updatedAt);
      if (Object.hasOwn(deleted, id) && incomingAt <= timestamp(deleted[id])) continue;
      if (existing && incomingAt <= timestamp(existing.updatedAt)) continue;
      const row = {...(existing || {}), id, title:note.title, content:note.content, updatedAt:toIso(note.updatedAt)};
      await put("notes", row); notes.set(id, row);
    }
    if (typeof payload.drawings === "string" && payload.drawings) {
      try {
        const key = "dmate:offline:drawing-gallery:v1", current = localStorage.getItem(key);
        if (!current) localStorage.setItem(key, payload.drawings);
        else {
          const local = JSON.parse(current), incoming = JSON.parse(payload.drawings);
          if (Array.isArray(local?.pages) && Array.isArray(incoming?.pages)) {
            const pages = local.pages.slice(), ids = new Set(pages.map(page => page.id));
            for (const page of incoming.pages) if (page && typeof page.id === "string" && !ids.has(page.id) && pages.length < 50) {
              pages.push(page); ids.add(page.id);
            }
            // Local page positions, documents and the active page stay intact.
            localStorage.setItem(key, JSON.stringify({...local, pages}));
          }
        }
      } catch (error) { toast("本机绘图库已保留，部分在线绘图未能导入：" + (error?.message || "")); }
    }
    sessionStorage.removeItem("dmate_offline_migration_v1");
    toast("已导入当前账号的错题、笔记和绘图到本机离线区");
  }

  async function loadResources() {
    const [concepts, questions, graph] = await Promise.all([
      fetch("/static/offline-content/concepts.zh-CN.json", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("概念库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/questions.zh-CN.json", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("题库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/knowledge_graph.json", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("知识图谱资源不可用"); return r.json(); })
    ]);
    state.concepts = Array.isArray(concepts.concepts) ? concepts.concepts : [];
    state.questions = Array.isArray(questions.questions) ? questions.questions : [];
    state.graph = graph;
  }

  function setNetworkStatus() {
    const online = navigator.onLine;
    const status = $("networkStatus");
    status.className = "offline-status " + (online ? "online" : "offline");
    status.lastElementChild.textContent = online ? "网络已连接 · 本地可用" : "离线状态 · 本地运行";
    $("returnOnline").disabled = !online;
    $("returnOnline").title = online ? "返回在线版" : "网络恢复后可返回在线版";
  }

  async function switchPanel(name, trigger) {
    if (!panelMeta[name]) return;
    state.panel = name;
    const section = $(name + "Panel");
    if (section) section.hidden = false;
    if ($("panelTitle")) $("panelTitle").textContent = panelMeta[name][0];
    if ($("panelDescription")) $("panelDescription").textContent = panelMeta[name][1];
    // Open before drawing/graph mount so their camera measures the actual modal.
    window.DMateOfflineShell?.openModule(name, trigger);
    if (name === "mistakes") await renderMistakes();
    if (name === "notes") await renderNotes();
    if (name === "drawing") mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
    if (name === "review") await renderReview();
    window.dispatchEvent(new CustomEvent("dmate:offlinepanelchange", {detail:{panel:name}}));
  }

  async function renderMistakes() {
    const saved = await all("mistakes");
    if ($("mistakeCount")) $("mistakeCount").textContent = saved.length + " 道错题";
    const label = $("wrongBookBtn")?.querySelector(".dmate-ui-label");
    if (label) label.textContent = "错题本 (" + saved.length + ")";
    if ($("wrongBookStats")) $("wrongBookStats").textContent = "共 " + saved.length + " 道 · 待处理 " + saved.filter(row => row.status !== "resolved").length + " 道";
    const query = state.mistakeSearch.toLocaleLowerCase();
    const rows = saved.filter(row => (state.mistakeFilter === "all" || (state.mistakeFilter === "corrected") === (row.status === "resolved"))
      && (!query || [row.title,row.statement,row.content,row.answer,row.explanation].join("\n").toLocaleLowerCase().includes(query)));
    rows.sort((a,b) => state.mistakeSort === "oldest" ? String(a.updatedAt).localeCompare(String(b.updatedAt))
      : state.mistakeSort === "mistakes" ? (Number(b.wrongCount) || 1) - (Number(a.wrongCount) || 1)
      : String(b.updatedAt).localeCompare(String(a.updatedAt)));
    document.querySelectorAll("[data-wrong-filter]").forEach(button => {
      const active = button.dataset.wrongFilter === state.mistakeFilter;
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    });
    const list = $("mistakeList");
    list.classList.add("wrong-book-list");
    list.replaceChildren();
    if (!rows.length) {
      list.append(el("div", "wrong-empty", "无"));
      return;
    }
    for (const row of rows) {
      const card = el("article", "wrong-card");
      card.dataset.recordId = row.id;
      const top = el("div", "wrong-card-top");
      top.append(el("span", "wrong-status" + (row.status === "resolved" ? " corrected" : ""), row.status === "resolved" ? "已完成订正" : "待订正"),
        el("span", "wrong-date", new Date(row.updatedAt).toLocaleString()));
      card.append(top, rich("wrong-question", row.statement || row.content || ""));
      const knowledgeLabels = [...new Set((row.knowledgePoints || []).map(point =>
        state.graph?.nodes?.find(node => node.id === point)?.name
        || state.concepts.find(concept => concept.id === point)?.title
        || (typeof point === "string" && /[\u3400-\u9fff]/.test(point) ? point : "")
      ).filter(Boolean))];
      if (knowledgeLabels.length) {
        const meta = el("div", "wrong-meta"), line = el("div", "wrong-meta-row");
        line.append(el("span", "wrong-meta-label", "整题涉及"), el("span", "wrong-meta-value", knowledgeLabels.join("、")));
        meta.append(line); card.append(meta);
      }
      card.append(answerDetails("查看答案", row.answer || "这条记录没有保存参考答案。"));
      if (row.explanation) card.append(answerDetails("查看解析", row.explanation, "wrong-analysis-details"));
      const actions = el("div", "wrong-actions");
      if (row.status !== "resolved") actions.append(button("完成订正", "", async () => {
        await put("mistakes", {...row, status:"resolved", updatedAt:stamp()}); renderMistakes();
      }));
      const edit = button("编辑/笔记", "secondary", () => openRecord("mistakes", row));
      edit.dataset.action = "edit-mistake";
      const deletion = button("移出错题本", "secondary danger", async () => {
        if (await confirmDelete($("mistakesPanel"), "移出这道错题？", row.statement || row.title)) {
          await remove("mistakes", row.id); await renderMistakes();
        }
      });
      deletion.dataset.action = "delete-mistake";
      for (const control of [edit, deletion]) { control.setAttribute("aria-label",control.textContent); control.title=control.textContent; }
      actions.append(edit, deletion); card.append(actions); list.append(card);
    }
  }

  function notebookRows(snapshot) {
    const previous = new Map(state.noteRows.map(row => [row.id, row]));
    return snapshot.notes.map(note => ({...(previous.get(note.id) || {}), id:note.id, title:note.title,
      content:note.content, updatedAt:new Date(note.updatedAt).toISOString()}));
  }

  function writeNotebook(payload) {
    return new Promise((resolve, reject) => {
      const tx = state.db.transaction(["notes", "settings"], "readwrite");
      const notes = tx.objectStore("notes");
      for (const row of payload.rows) notes.put(row);
      const current = new Map(payload.snapshot.notes.map(note => [note.id, note.updatedAt]));
      for (const [id, deletedAt] of Object.entries(payload.snapshot.deleted || {})) {
        if (!(current.get(id) > deletedAt)) notes.delete(id);
      }
      tx.objectStore("settings").put({id:"notebook-deletions", deleted:payload.snapshot.deleted || {}, updatedAt:stamp()});
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = () => reject(tx.error || new Error("笔记保存失败"));
    });
  }

  function queueNotebook(payload, journal) {
    const operation = state.noteSaveQueue.then(async () => {
      await writeNotebook(payload);
      // A newer edit may already be queued; never remove its recovery copy.
      if (localStorage.getItem(NOTE_JOURNAL_KEY) === journal) localStorage.removeItem(NOTE_JOURNAL_KEY);
      if ($("noteCount")) $("noteCount").textContent = state.notebookSnapshot.notes.length + " 条笔记";
    });
    state.noteSaveQueue = operation.catch(error => {
      // The synchronous journal remains durable even when IndexedDB is full.
      // Keep the error visible; a later edit/open retries that latest snapshot.
      const saved = $("conceptNotebookDialog")?.querySelector(".dcn-saved");
      if (saved) saved.textContent = "笔记暂存于本机，数据库保存失败，请重试。";
      toast(error?.message || "笔记保存失败，已保留本机草稿");
    });
    return operation;
  }

  function saveNotebook(snapshot) {
    snapshot = JSON.parse(JSON.stringify(snapshot));
    for (const note of snapshot.notes) if (note.updatedAt > (snapshot.deleted[note.id] ?? Infinity)) delete snapshot.deleted[note.id];
    const rows = notebookRows(snapshot), payload = {version:1, snapshot, rows};
    const journal = JSON.stringify(payload);
    // The shared component has a synchronous persistence contract. Only
    // acknowledge an edit after a recoverable local copy was really written.
    localStorage.setItem(NOTE_JOURNAL_KEY, journal);
    state.notebookSnapshot = JSON.parse(JSON.stringify(snapshot));
    state.noteRows = rows;
    void queueNotebook(payload, journal).catch(() => {});
  }

  async function initNotebook() {
    state.noteRows = await all("notes");
    const metadata = await transaction("settings", "readonly", os => os.get("notebook-deletions"));
    state.notebookSnapshot = {notes:state.noteRows.map(row => ({id:row.id, title:String(row.title || ""), content:String(row.content || ""),
      updatedAt:Number.isFinite(Number(row.updatedAt)) ? Number(row.updatedAt) : Date.parse(row.updatedAt) || Date.now()})), deleted:metadata?.deleted || {}};
    state.notebookSnapshot.notes = state.notebookSnapshot.notes.filter(note =>
      !(state.notebookSnapshot.deleted[note.id] >= note.updatedAt));
    for (const note of state.notebookSnapshot.notes) if (note.updatedAt > (state.notebookSnapshot.deleted[note.id] ?? Infinity)) delete state.notebookSnapshot.deleted[note.id];
    try {
      const raw = localStorage.getItem(NOTE_JOURNAL_KEY), pending = raw ? JSON.parse(raw) : null;
      if (pending?.version === 1 && Array.isArray(pending.rows) && Array.isArray(pending.snapshot?.notes)) {
        state.notebookSnapshot = pending.snapshot;
        state.noteRows = pending.rows;
        await queueNotebook(pending, raw).catch(() => {});
      }
    } catch (error) { toast(error?.message || "笔记草稿暂时无法恢复"); }
    state.notebookController = window.DMateConceptNotebook.mount({
      button:$("conceptNotebookBtn"), dialog:$("conceptNotebookDialog"),
      getContextKey:() => "offline-local", getState:() => state.notebookSnapshot,
      onChange:saveNotebook,
      confirmDelete:options => window.DMateDeleteConfirm.request($("conceptNotebookDialog"), options),
      // Keep the shared analysis controls and their normal error presentation,
      // without ever issuing a network request for an offline-only operation.
      fetch:async () => ({ok:false, json:async () => ({ok:false, error:"AI 解释与关联分析需要联网；离线可编辑笔记，或在概念库查看内置解释。"})})
    });
  }

  async function renderNotes() {
    if (!state.notebookController) await initNotebook();
    const raw = localStorage.getItem(NOTE_JOURNAL_KEY);
    if (raw) {
      try { await queueNotebook(JSON.parse(raw), raw); } catch (_) {}
    }
    state.notebookController.refresh();
    state.notebookController.open();
  }

  async function createNote() {
    await switchPanel("notes");
    $("conceptNotebookDialog").querySelector(".dcn-primary")?.click();
  }

  function openRecord(kind, row = null) {
    state.recordKind = kind;
    state.editingId = row?.id || null;
    $("recordDialogTitle").textContent = row ? (kind === "notes" ? "编辑笔记" : "编辑错题") : (kind === "notes" ? "新建笔记" : "添加错题");
    $("recordTitle").value = row?.title || "";
    $("recordContent").value = row?.content || row?.statement || "";
    const titleLabel = $("recordTitle").closest("label");
    const contentLabel = $("recordContent").closest("label");
    if (titleLabel?.firstChild?.nodeType === Node.TEXT_NODE) titleLabel.firstChild.textContent = "题目名称";
    if (contentLabel?.firstChild?.nodeType === Node.TEXT_NODE) contentLabel.firstChild.textContent = "题目内容";
    $("recordTitle").setAttribute("aria-label", "题目名称");
    $("recordContent").setAttribute("aria-label", "题目内容");
    $("recordDialog").showModal();
    $("recordTitle").focus();
  }

  async function saveRecord(event) {
    event.preventDefault();
    const title = $("recordTitle").value.trim();
    const content = $("recordContent").value.trim();
    if (!title || !content) return toast("标题和内容不能为空");
    const store = state.recordKind;
    const old = state.editingId ? (await all(store)).find(row => row.id === state.editingId) : null;
    const row = {
      ...(old || {}), id: state.editingId || uid(), title,
      updatedAt: stamp(), status: old?.status || "pending"
    };
    if (store === "notes") row.content = content;
    else row.statement = content;
    await put(store, row);
    $("recordDialog").close();
    if (store === "notes") renderNotes(); else renderMistakes();
    toast("已保存在本机");
  }

  async function addQuestionMistake(question) {
    const rows = await all("mistakes");
    const existing = rows.find(row => row.questionId === question.id);
    const record = {
      id: existing?.id || uid(), questionId: question.id, title: question.title,
      statement: question.statement, answer: question.answer_text || (question.answer || []).join("、"),
      explanation: question.explanation, knowledgePoints: question.knowledge_points || [],
      status: "pending", updatedAt: stamp()
    };
    await put("mistakes", record);
    toast(existing ? "已更新错题记录" : "已加入错题本");
    if (state.panel === "mistakes") renderMistakes();
  }

  function fillQuestionFilters() {
    const select = $("questionCategory");
    if (select.options.length > 1) return;
    const categories = [...new Set(state.questions.map(q => q.category))].sort();
    for (const value of categories) select.add(new Option(value, value));
  }

  function renderQuestions() {
    fillQuestionFilters();
    const filtered = state.questions.filter(q =>
      (!state.questionCategory || q.category === state.questionCategory) &&
      (!state.questionDifficulty || q.difficulty === state.questionDifficulty)
    );
    $("questionCount").textContent = filtered.length + " 道题目";
    const list = $("questionList");
    list.replaceChildren();
    for (const question of filtered) {
      const item = button("", "question-item" + (state.selectedQuestion?.id === question.id ? " active" : ""), () => selectQuestion(question));
      item.dataset.questionId = question.id;
      item.setAttribute("aria-current", String(state.selectedQuestion?.id === question.id));
      item.append(el("strong", "", question.title), el("small", "", question.category + " · " + question.difficulty + " · " + question.type));
      list.append(item);
    }
    if (state.selectedQuestion && filtered.some(q => q.id === state.selectedQuestion.id)) {
      renderQuestionDetail(state.selectedQuestion);
    } else if (filtered.length) selectQuestion(filtered[0]);
    else {
      state.selectedQuestion = null;
      $("questionDetail").replaceChildren(el("div","offline-empty","没有符合条件的题目。"));
    }
  }

  function selectQuestion(question) {
    state.selectedQuestion = question;
    state.selectedOption = [];
    state.revealed = false;
    document.querySelectorAll(".question-item").forEach(node => {
      const selected = node.dataset.questionId === question.id;
      node.classList.toggle("active", selected); node.setAttribute("aria-current", String(selected));
    });
    renderQuestionDetail(question);
  }

  function renderQuestionDetail(question) {
    const detail = $("questionDetail");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", question.category + " / " + question.difficulty + " / " + question.type));
    detail.append(el("h2", "detail-title", question.title));
    const statement = el("div", "detail-section wrong-question-section");
    statement.append(el("h3", "", "题目"));
    statement.append(rich("wrong-question", question.statement));
    detail.append(statement);

    if (Array.isArray(question.options) && question.options.length) {
      const options = el("div", "detail-section");
      options.append(el("h3", "", question.type === "多项选择" ? "选择所有正确选项" : "选择一个答案"));
      for (const option of question.options) {
        const node = button("",
          "question-option" + (state.selectedOption.includes(option.key) ? " selected" : ""),
          () => {
            if (question.type === "多项选择") {
              state.selectedOption = state.selectedOption.includes(option.key)
                ? state.selectedOption.filter(x => x !== option.key) : [...state.selectedOption, option.key];
            } else state.selectedOption = [option.key];
            renderQuestionDetail(question);
          });
        node.append(el("span", "question-option-key", option.key + "."), rich("question-option-text", option.text));
        node.setAttribute("aria-pressed", String(state.selectedOption.includes(option.key)));
        options.append(node);
      }
      detail.append(options);
    } else {
      const response = el("div", "detail-section");
      response.append(el("h3", "", "你的作答"));
      const textarea = el("textarea", "");
      textarea.id = "questionResponse";
      textarea.value = state.questionResponses.get(question.id) || "";
      textarea.setAttribute("aria-label", "你的作答");
      textarea.addEventListener("input", () => state.questionResponses.set(question.id, textarea.value));
      textarea.placeholder = question.type === "证明" ? "在这里写出完整证明过程…" : "在这里填写你的答案…";
      response.append(textarea); detail.append(response);
    }

    const actions = el("div", "question-actions wrong-actions");
    actions.append(action("记录本次练习", "secondary", async () => {
      const response = $("questionResponse")?.value || "";
      await put("practice", {id:uid(), questionId:question.id, response, selected:state.selectedOption, createdAt:stamp()});
      toast("练习记录已保存在本机");
    }, "save"));
    actions.append(action(state.revealed ? "收起参考答案" : "查看参考答案", "offline-primary", () => {
      state.revealed = !state.revealed;
      renderQuestionDetail(question);
    }, "eye"));
    actions.append(action("加入错题本", "secondary", () => addQuestionMistake(question), "book-open"));
    detail.append(actions);

    if (state.revealed) {
      const answer = el("section", "answer-panel wrong-answer-details");
      answer.append(el("h3", "", "参考答案"));
      answer.append(rich("wrong-answer-inner", question.answer_text || (question.answer || []).join("、")));
      answer.append(el("h3", "", "解析"));
      answer.append(rich("wrong-analysis-body", question.explanation || "暂无解析。"));
      if (question.grading_criteria) {
        answer.append(el("h3", "", "评分要点"), rich("wrong-feedback-body", question.grading_criteria));
      }
      detail.append(answer);
    }
  }

  function fillConceptDetail(concept) {
    state.selectedConcept = concept;
    const detail = $("conceptDetail");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", concept.category));
    detail.append(el("h2", "detail-title", concept.title));
    detail.append(rich("concept-summary", concept.summary));
    document.querySelectorAll(".concept-item").forEach(item => {
      const selected = item.dataset.conceptId === concept.id;
      item.classList.toggle("active", selected); item.setAttribute("aria-current", String(selected));
    });
    const section = (title, content) => {
      const box = el("section", "detail-section");
      box.append(el("h3", "", title));
      if (Array.isArray(content)) {
        const ul = el("ul", "");
        for (const item of content) { const li = el("li"); li.append(rich("concept-detail-text", item)); ul.append(li); }
        box.append(ul);
      } else box.append(rich("concept-detail-text", content || "暂无内容。"));
      detail.append(box);
    };
    section("基本定义", concept.definition);
    section("理解与说明", concept.explanation);
    section("数学符号", concept.notation || []);
    section("典型例题", concept.example);
    section("常见错误", concept.common_mistakes || []);
    const related = el("section", "detail-section");
    related.append(el("h3", "", "关联知识点"));
    const prereqs = el("div", "prereq-list");
    for (const id of concept.prerequisites || []) {
      const item = state.concepts.find(c => c.id === id);
      if (item) prereqs.append(button(item.title, "", () => fillConceptDetail(item)));
    }
    for (const id of concept.related_questions || []) {
      const q = state.questions.find(x => x.id === id);
      if (q) prereqs.append(button("练习：" + q.title, "", () => {
        state.questionCategory = ""; state.questionDifficulty = "";
        $("questionCategory").value = ""; $("questionDifficulty").value = "";
        switchPanel("questions"); selectQuestion(q);
      }));
    }
    if (!prereqs.children.length) prereqs.append(el("span", "", "暂无已关联条目"));
    related.append(prereqs); detail.append(related);
  }

  function renderConcepts() {
    const query = $("conceptSearch").value.trim().toLocaleLowerCase();
    const rows = state.concepts.filter(c => !query || [c.title,c.category,c.summary,c.definition].join(" ").toLocaleLowerCase().includes(query));
    $("conceptCount").textContent = rows.length + " 个概念";
    const list = $("conceptList"); list.replaceChildren();
    for (const concept of rows) {
      const item = button("", "concept-item" + (state.selectedConcept?.id === concept.id ? " active" : ""), () => {
        fillConceptDetail(concept);
      });
      item.dataset.conceptId = concept.id;
      item.setAttribute("aria-current", String(state.selectedConcept?.id === concept.id));
      item.append(el("strong", "", concept.title), el("small", "", concept.category));
      list.append(item);
    }
    if (state.selectedConcept && rows.some(c => c.id === state.selectedConcept.id)) fillConceptDetail(state.selectedConcept);
    else if (rows.length) fillConceptDetail(rows[0]);
    else $("conceptDetail").replaceChildren(el("div","offline-empty","没有找到匹配的概念。"));
  }

  function renderGraph() {
    if (!state.graph?.nodes) return;
    const query = ($("knowledgeGraphSearch") || $("graphSearch"))?.value.trim().toLocaleLowerCase() || "";
    const categories = [...new Set(state.graph.nodes.map(node => node.category))];
    const category = $("knowledgeGraphCategory");
    if (category && category.options.length !== categories.length + 1) {
      category.replaceChildren(new Option("全部", ""), ...categories.map(value => new Option(value, value)));
      category.value=state.graphCategory;
    }
    if ($("knowledgeGraphCategoryTrigger")) $("knowledgeGraphCategoryTrigger").textContent = "模块：" + (state.graphCategory || "全部");
    const nodes = state.graph.nodes.filter(node => (!state.graphCategory || node.category === state.graphCategory)
      && (!query || [node.name,node.category].join(" ").toLocaleLowerCase().includes(query)));
    if ($("graphCount")) $("graphCount").textContent = nodes.length + " 个知识点";
    const host = $("knowledgeGraphCanvas") || $("graphNodes");
    state.graphController?.destroy(); state.graphController = null;
    host.replaceChildren();
    if (!window.DMateOfflineGraph?.mount) {
      host.append(el("div", "wrong-empty", "知识图谱组件尚未加载，请刷新后重试。")); return;
    }
    state.graphController = window.DMateOfflineGraph.mount(host, {nodes, onNotice:toast, onSelect(node) {
      const concept = state.concepts.find(item => item.id === node.id || item.title === node.name);
      if (concept) {
        $("conceptSearch").value = ""; state.selectedConcept = concept;
        void switchPanel("concepts");
      } else toast("该知识点尚无独立概念条目");
    }});
    if ($("knowledgeGraphSummary")) $("knowledgeGraphSummary").textContent = (state.graphCategory || "全部知识") + " · " + nodes.length + " 个知识点";
    applyGraphFocus();
  }

  async function applyGraphFocus() {
    const controller=state.graphController;
    $("knowledgeGraphScopeBtn")?.classList.toggle("active", state.graphFocus);
    $("knowledgeGraphScopeBtn")?.setAttribute("aria-pressed", String(state.graphFocus));
    $("knowledgeGraphFocusBtn")?.classList.toggle("active", !state.graphFocus);
    $("knowledgeGraphFocusBtn")?.setAttribute("aria-pressed", String(!state.graphFocus));
    if (!controller) return;
    if (!state.graphFocus) { controller.showAll(); return; }
    let question=state.selectedQuestion;
    if (!question) {
      const recent=(await all("practice")).sort((a,b) => String(b.createdAt).localeCompare(String(a.createdAt)))[0];
      question=state.questions.find(item => item.id === recent?.questionId);
    }
    if (controller !== state.graphController) return;
    if (!question?.knowledge_points?.length) { controller.showAll(); toast("暂无最近练习，先显示全部知识。完成练习后可查看关联知识。"); return; }
    controller.focus(question.knowledge_points);
  }

  async function showGraphHistory() {
    $("knowledgeGraphDetailTab")?.classList.remove("active"); $("knowledgeGraphHistoryTab")?.classList.add("active");
    $("knowledgeGraphDetailWrap")?.classList.add("hidden"); $("knowledgeGraphHistoryWrap")?.classList.remove("hidden");
    const history=$("knowledgeGraphHistory"), rows=(await all("practice")).sort((a,b) => String(b.createdAt).localeCompare(String(a.createdAt)));
    history.replaceChildren();
    for (const row of rows) {
      const question=state.questions.find(item => item.id === row.questionId); if (!question) continue;
      const item=button("", "kg-history-item", () => { state.selectedQuestion=question; state.graphFocus=true; void applyGraphFocus(); });
      item.append(el("div", "kg-history-item-top", question.title), el("div", "small", new Date(row.createdAt).toLocaleString())); history.append(item);
    }
    if (!history.childElementCount) history.append(el("div", "wrong-empty", "无"));
  }

  function mountDrawing() {
    if (state.drawingController) return;
    const host = $("offlineDrawingHost");
    if (!window.DMateDrawingWorkspace?.mount) {
      toast("绘图组件尚未加载，请刷新页面后重试");
      return;
    }
    try {
      state.drawingController = window.DMateDrawingWorkspace.mount(host, {
        storageKey: "dmate:offline:drawing-gallery:v1",
        persistent: true,
        sessionState: {},
        legacyDocument: {body_text:"",graphs:[{id:"G1",name:"我的图形",directed:false,weighted:false,vertices:[],edges:[]}]},
        onUpload: async () => { throw new Error("离线模式不支持上传或在线识图"); },
        onChange: () => {}
      });
    } catch (error) {
      toast(error?.message || "绘图工作区无法启动");
    }
  }

  async function exportData() {
    await state.noteSaveQueue;
    const [mistakes, practice] = await Promise.all([all("mistakes"), all("practice")]);
    // Include the durable journal's latest edits even if IndexedDB is full.
    const notes = notebookRows(state.notebookSnapshot);
    const drawings = localStorage.getItem("dmate:offline:drawing-gallery:v1") || "";
    const payload = {format:"dmate-offline-backup",version:1,createdAt:stamp(),mistakes,notes,practice,drawings};
    const blob = new Blob([JSON.stringify(payload,null,2)], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "dmate-offline-backup.json";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("本地学习数据已导出");
  }

  async function returnOnline() {
    if (!navigator.onLine) return toast("当前没有网络，在线版暂时无法打开");
    window.location.assign("/");
  }

  async function saveAppearance(changes) {
    const saved = await transaction("settings", "readonly", os => os.get("appearance"));
    let previous = saved?.settings;
    if (!previous) {
      try { previous = JSON.parse(localStorage.getItem("dmate:offline:appearance:v1") || "null"); } catch (_) {}
    }
    const patch = changes?.settings || changes || {};
    const fields = ["mode", "accent", "fontSize", "panelOpacity", "bubbleOpacity", "backgroundFit", "blur", "mask"];
    const next = {...(previous || {})};
    for (const key of fields) if (Object.hasOwn(patch, key)) next[key] = patch[key];
    const value = {...(saved || {}), id:"appearance", settings:next, updatedAt:stamp()};
    if (changes?.removeBackground) delete value.backgroundBlob;
    else if (changes?.backgroundBlob instanceof Blob) value.backgroundBlob = changes.backgroundBlob;
    await put("settings", value);
    try { localStorage.setItem("dmate:offline:appearance:v1", JSON.stringify(next)); } catch (_) {}
    window.DMateOfflineAppearance?.apply(next, value.backgroundBlob || null);
    window.dispatchEvent(new CustomEvent("offline:appearance-applied", {detail:{settings:next}}));
  }

  async function renderReview() {
    const [mistakes, practice] = await Promise.all([all("mistakes"), all("practice")]);
    const body = $("learningReviewBody");
    let summary = body.querySelector("[data-offline-review-summary]");
    if (!summary) { summary = el("section", "learning-review-section"); summary.dataset.offlineReviewSummary = ""; body.prepend(summary); }
    summary.replaceChildren(el("h3", "", "学习记录"));
    summary.append(el("p", "", "共完成 " + practice.length + " 次练习，保存 " + mistakes.length + " 道错题、" + state.notebookSnapshot.notes.length + " 条概念笔记。"));
  }

  function queryLocal(text, mode) {
    const query = String(text || "").trim();
    if (!query) return;
    const chat = $("chat");
    chat.closest(".center")?.classList.remove("chat-empty");
    const message = (role, content) => {
      const bubble = el("div", "msg " + role), inner = el("div", "msg-content");
      if (typeof content === "string") inner.textContent = content; else inner.append(content);
      bubble.append(inner); chat.append(bubble); return inner;
    };
    message("user", query);
    const key = query.toLocaleLowerCase(), ignored = new Set(["什么","么是","是什","解释","说明","一下","帮我","讲讲","告诉","怎么","如何"]);
    const chinese = (key.match(/[\u3400-\u9fff]{2,}/g) || []).flatMap(part =>
      Array.from({length:part.length-1}, (_,index) => part.slice(index,index+2)).filter(term => !ignored.has(term)));
    const tokens = [...new Set([...(key.match(/[a-z0-9]+|[\u3400-\u9fff]{2,}/g) || [key]), ...chinese,
      ...state.concepts.flatMap(item => [item.title,item.category]).filter(term => key.includes(term.toLocaleLowerCase()))])];
    const score = text => {
      const source = String(text).toLocaleLowerCase();
      return (source.includes(key) ? 20 : 0) + tokens.reduce((sum, token) => sum + (source.includes(token) ? Math.min(token.length, 8) : 0), 0);
    };
    const concepts = state.concepts.map(item => ({item, rank:score([item.title,item.category,item.summary,item.definition].join(" "))}))
      .filter(row => row.rank > 0).sort((a,b) => b.rank-a.rank).slice(0,3);
    const questions = state.questions.map(item => ({item, rank:score([item.title,item.category,item.statement].join(" "))}))
      .filter(row => row.rank > 0).sort((a,b) => b.rank-a.rank).slice(0,3);
    const response = el("div", "ai-content");
    if (!concepts.length && !questions.length) response.append(el("p", "", "离线资料中没有找到匹配内容。可在学习工具中查看概念、练习、错题和笔记；联网后可使用完整聊天与解题。"));
    else {
      response.append(el("p", "", "在本机资料中找到以下内容："));
      const addConcept = ({item}) => {
        const section = el("section", ""); section.append(el("h3", "", item.title), rich("", item.definition));
        section.append(button("查看概念", "", async () => { state.selectedConcept=item; $("conceptSearch").value=""; await switchPanel("concepts"); })); response.append(section);
      };
      const addQuestion = ({item}) => response.append(button(item.title, "", async () => {
        state.questionCategory=""; state.questionDifficulty=""; $("questionCategory").value=""; $("questionDifficulty").value="";
        await switchPanel("questions"); selectQuestion(item);
      }));
      if (mode === "question") { questions.forEach(addQuestion); concepts.forEach(addConcept); }
      else { concepts.forEach(addConcept); questions.forEach(addQuestion); }
    }
    message("ai", response); chat.scrollTop=chat.scrollHeight;
  }

  let choiceResolver=null;
  function closeChoice(result=null) {
    const modal=$("mobileChoiceModal"), resolve=choiceResolver; choiceResolver=null;
    if (modal) { modal.classList.add("hidden"); modal.setAttribute("aria-hidden","true"); if (modal.open) modal.close(); }
    if (resolve) resolve(result);
  }
  function openChoice({title="请选择", intro="", options=[], value=""}={}) {
    const modal=$("mobileChoiceModal"); if (!modal) return Promise.resolve(null);
    closeChoice(); $("mobileChoiceTitle").textContent=title; $("mobileChoiceIntro").textContent=intro;
    $("mobileChoiceIntro").hidden=!intro; $("mobileChoiceIntro").classList.toggle("hidden", !intro);
    $("mobileChoiceList").replaceChildren(...options.map(option => {
      const item=button("", "mobile-choice-option" + (String(option.value) === String(value) ? " active" : ""), () => closeChoice(option));
      item.disabled=Boolean(option.disabled); item.setAttribute("role","radio"); item.setAttribute("aria-checked",String(String(option.value) === String(value)));
      item.append(el("span","mobile-choice-option-text",option.label), el("span","mobile-choice-option-check")); return item;
    }));
    modal.classList.remove("hidden"); modal.setAttribute("aria-hidden","false");
    if (!modal.open) modal.showModal();
    requestAnimationFrame(() => (modal.querySelector(".mobile-choice-option.active:not(:disabled)") || modal.querySelector("button:not(:disabled)"))?.focus({preventScroll:true}));
    return new Promise(resolve => { choiceResolver=resolve; });
  }
  async function chooseSelect(select, title) {
    const result=await openChoice({title,value:select.value, options:[...select.options].map(option => ({value:option.value,label:option.label,disabled:option.disabled}))});
    if (result && select.isConnected && select.value !== result.value) { select.value=result.value; select.dispatchEvent(new Event("change",{bubbles:true})); }
  }
  window.openMobileChoiceModal=openChoice;
  window.closeMobileChoiceModal=()=>closeChoice();

  function bind() {
    document.querySelectorAll("[data-offline-panel]").forEach(item => item.addEventListener("click", () => {
      void switchPanel(item.dataset.offlinePanel, item).catch(error => toast(error?.message || "无法打开学习工具"));
    }));
    $("addMistake")?.addEventListener("click", () => openRecord("mistakes"));
    $("addNote")?.addEventListener("click", () => createNote().catch(error => toast(error?.message || "无法新建笔记")));
    $("recordForm").addEventListener("submit", event => saveRecord(event).catch(error => toast(error?.message || "本地保存失败")));
    $("cancelRecord").addEventListener("click", () => $("recordDialog").close());
    $("cancelRecordSecondary")?.addEventListener("click", () => $("recordDialog").close());
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    ($("knowledgeGraphSearch") || $("graphSearch"))?.addEventListener("input", renderGraph);
    $("wrongBookSearch")?.addEventListener("input", event => {
      state.mistakeSearch=event.target.value.trim(); $("wrongBookSearchClear")?.classList.toggle("hidden", !event.target.value); void renderMistakes();
    });
    $("wrongBookSearchClear")?.addEventListener("click", () => {
      $("wrongBookSearch").value=""; state.mistakeSearch=""; $("wrongBookSearchClear").classList.add("hidden"); void renderMistakes();
    });
    $("wrongBookSort")?.addEventListener("change", event => {
      state.mistakeSort=event.target.value;
      if ($("wrongBookSortTrigger")) $("wrongBookSortTrigger").textContent=event.target.selectedOptions[0].textContent;
      void renderMistakes();
    });
    $("wrongBookSortTrigger")?.addEventListener("click", () => { void chooseSelect($("wrongBookSort"), "错题排序"); });
    document.querySelectorAll("[data-wrong-filter]").forEach(item => item.addEventListener("click", () => {
      state.mistakeFilter=state.mistakeFilter===item.dataset.wrongFilter ? "all" : item.dataset.wrongFilter; void renderMistakes();
    }));
    $("wrongPdfBtn")?.addEventListener("click", () => window.print());
    $("mobileChoiceClose")?.addEventListener("click", () => closeChoice());
    $("mobileChoiceModal")?.addEventListener("cancel", event => { event.preventDefault(); closeChoice(); });
    $("mobileChoiceModal")?.addEventListener("click", event => { if (event.target === event.currentTarget) closeChoice(); });
    $("knowledgeGraphCategory")?.addEventListener("change", event => { state.graphCategory=event.target.value; state.graphFocus=false; renderGraph(); });
    $("knowledgeGraphCategoryTrigger")?.addEventListener("click", () => { void chooseSelect($("knowledgeGraphCategory"), "知识图谱分类"); });
    $("knowledgeGraphScopeBtn")?.addEventListener("click", () => { state.graphFocus=true; void applyGraphFocus(); });
    $("knowledgeGraphFocusBtn")?.addEventListener("click", () => { state.graphFocus=false; void applyGraphFocus(); });
    $("knowledgeGraphHistoryTab")?.addEventListener("click", () => { void showGraphHistory(); });
    $("knowledgeGraphDetailTab")?.addEventListener("click", () => {
      $("knowledgeGraphDetailTab").classList.add("active"); $("knowledgeGraphHistoryTab").classList.remove("active");
      $("knowledgeGraphDetailWrap").classList.remove("hidden"); $("knowledgeGraphHistoryWrap").classList.add("hidden");
    });
    window.addEventListener("offline:query", event => queryLocal(event.detail?.text, event.detail?.mode));
    window.addEventListener("offline:toast", event => toast(event.detail?.message || event.detail));
    $("exportLocalData").addEventListener("click", () => exportData().catch(error => toast(error.message)));
    $("returnOnline").addEventListener("click", returnOnline);
    window.addEventListener("online", setNetworkStatus);
    window.addEventListener("offline", setNetworkStatus);
    window.addEventListener("offline:appearance-change", event => {
      state.appearanceQueue = state.appearanceQueue.then(() => saveAppearance(event.detail))
        .catch(error => { window.DMateOfflineAppearance?.fail(error); toast(error?.message || "外观保存失败"); });
    });
  }

  async function init() {
    try {
      setNetworkStatus();
      if ($("info")) { $("info").textContent="无"; $("info").classList.add("is-empty"); }
      state.db = await openDb();
      await applyOriginalAppearance();
      configureRenderer();
      await migrateCurrentAccountData();
      await loadResources();
      await initNotebook();
      bind();
      $("saveState").textContent = "本地保存已启用";
      await renderMistakes();
      document.documentElement.dataset.offlineReady = "true";
    } catch (error) {
      $("saveState").textContent = "初始化失败";
      toast(error?.message || "离线工作区初始化失败");
    }
  }
  window.DMateOfflineWorkspace = {openPanel:switchPanel, closeNotebook() {
    state.notebookController?.close(); return !$("conceptNotebookDialog").open;
  }};
  init();
})();
