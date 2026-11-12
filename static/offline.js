(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DB_NAME = "dmate-offline-workspace";
  const DB_VERSION = 2;
  const NOTE_JOURNAL_KEY = "dmate:offline:notebook-journal:v1";
  const state = {
    db: null, concepts: [], questions: [], graph: null,
    panel: "mistakes", selectedQuestion: null, selectedConcept: null,
    selectedOption: [], revealed: false, recordKind: "note", editingId: null,
    drawingController: null, backgroundUrl: "", graphCategory: "", questionCategory: "",
    questionDifficulty: "", conceptQuery: "", graphQuery: "", graphController: null,
    selectedNoteId: null, noteQuery: "", noteRows: [], noteSaveQueue: Promise.resolve(),
    questionResponses: new Map(), appearanceQueue: Promise.resolve()
  };
  const panelMeta = {
    mistakes: ["错题本", "在本机查看、整理和复习已保存的错题。"],
    notes: ["笔记本", "把自己的理解、推导和学习记录保存在本机。"],
    drawing: ["绘图", "使用 DMate 图形编辑器，在本机创建和保存数学图形。"],
    graph: ["知识图谱", "浏览离散数学知识点及其前置关系。"],
    questions: ["题库", "按章节和难度练习，查看参考答案与解析。"],
    concepts: ["概念库", "使用简体中文查看定义、解释、例题和易错点。"]
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

  async function restoreNotebookDraft() {
    // This journal was written by the temporary notebook UI. Replay it into
    // the original notes store so changing the interface cannot lose edits.
    const raw = localStorage.getItem(NOTE_JOURNAL_KEY);
    if (!raw) return;
    const pending = JSON.parse(raw);
    if (pending?.version !== 1 || !Array.isArray(pending.rows) || !Array.isArray(pending.snapshot?.notes)) {
      throw new Error("本机笔记草稿无法读取，已保留原数据，请保留此页面后重试。");
    }
    const time = value => {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? Math.max(0,numeric) : Date.parse(value) || 0;
    };
    const [rows, metadata] = await Promise.all([all("notes"), transaction("settings", "readonly", store => store.get("notebook-deletions"))]);
    const byId = new Map(rows.map(row => [row.id,row])), deleted = {...(metadata?.deleted || {})};
    for (const [id, at] of Object.entries(pending.snapshot.deleted || {})) deleted[id] = Math.max(time(deleted[id]), time(at));
    for (const draft of pending.rows) {
      if (!draft || typeof draft.id !== "string" || typeof draft.title !== "string" || typeof draft.content !== "string") continue;
      const previous = byId.get(draft.id);
      if (!previous || time(draft.updatedAt) >= time(previous.updatedAt)) {
        byId.set(draft.id, {...(previous || {}), ...draft, updatedAt:new Date(time(draft.updatedAt) || Date.now()).toISOString()});
      }
    }
    await new Promise((resolve,reject) => {
      const tx = state.db.transaction(["notes","settings"], "readwrite"), notes = tx.objectStore("notes");
      for (const [id,row] of byId) {
        if (Object.hasOwn(deleted,id) && time(deleted[id]) >= time(row.updatedAt)) notes.delete(id);
        else notes.put(row);
      }
      for (const id of Object.keys(deleted)) if (!byId.has(id)) notes.delete(id);
      tx.objectStore("settings").put({...(metadata || {}), id:"notebook-deletions", deleted, updatedAt:stamp()});
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = () => reject(tx.error || new Error("笔记草稿尚未恢复，原稿已保留，请重试。"));
    });
    if (localStorage.getItem(NOTE_JOURNAL_KEY) === raw) localStorage.removeItem(NOTE_JOURNAL_KEY);
  }

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
    // Recover edits acknowledged by the temporary shared notebook before
    // comparing incoming account snapshots with this device's current data.
    await restoreNotebookDraft();
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

  function switchPanel(name) {
    if (!panelMeta[name]) return;
    state.panel = name;
    document.querySelectorAll(".offline-nav-item").forEach(item => {
      const selected = item.dataset.panel === name;
      item.classList.toggle("active", selected);
      if (selected) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    });
    for (const key of Object.keys(panelMeta)) {
      const node = $(key + "Panel");
      if (node) node.hidden = key !== name;
    }
    $("panelTitle").textContent = panelMeta[name][0];
    $("panelDescription").textContent = panelMeta[name][1];
    let rendering;
    if (name === "mistakes") rendering = renderMistakes();
    if (name === "notes") rendering = renderNotes();
    if (name === "drawing") mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
    window.dispatchEvent(new CustomEvent("dmate:offlinepanelchange", {detail:{panel:name}}));
    return rendering;
  }

  async function renderMistakes() {
    const rows = (await all("mistakes")).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt));
    $("mistakeCount").textContent = rows.length + " 道错题";
    const list = $("mistakeList");
    list.classList.add("wrong-book-list");
    list.replaceChildren();
    if (!rows.length) {
      list.append(el("div", "wrong-empty offline-empty", "无"));
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
      const actions = el("div", "wrong-actions record-actions");
      if (row.status !== "resolved") actions.append(action("完成订正", "", async () => {
        await put("mistakes", {...row, status:"resolved", updatedAt:stamp()}); renderMistakes();
      }, "check"));
      const edit = action("编辑/笔记", "secondary", () => openRecord("mistakes", row), "edit");
      edit.dataset.action = "edit-mistake";
      const deletion = action("移出错题本", "secondary danger", async () => {
        if (await confirmDelete($("mistakesPanel"), "移出这道错题？", row.statement || row.title)) {
          await remove("mistakes", row.id); await renderMistakes();
        }
      }, "trash");
      deletion.dataset.action = "delete-mistake";
      actions.append(edit, deletion); card.append(actions); list.append(card);
    }
  }

  async function renderNotes() {
    await state.noteSaveQueue;
    const rows = (await all("notes")).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt));
    state.noteRows = rows;
    if (!rows.some(row => row.id === state.selectedNoteId)) state.selectedNoteId = rows[0]?.id || null;
    $("noteCount").textContent = rows.length + " 条笔记";
    const host = $("noteList");
    host.classList.add("dcn-content", "offline-notebook");
    host.replaceChildren();
    const sidebar = el("aside", "dcn-sidebar"), main = el("section", "dcn-main");
    sidebar.setAttribute("aria-label", "概念笔记列表");
    const search = el("input", "dcn-search");
    search.type = "search"; search.placeholder = "搜索"; search.setAttribute("aria-label", "搜索笔记"); search.value = state.noteQuery;
    const list = el("div", "dcn-list");
    function renderList() {
      list.replaceChildren();
      const query = state.noteQuery.toLocaleLowerCase();
      const visible = state.noteRows.filter(row => !query || (row.title + "\n" + row.content).toLocaleLowerCase().includes(query));
      if (!visible.length) list.append(el("p", "dcn-list-empty", rows.length ? "没有匹配的概念。" : "无"));
      for (const row of visible) {
        const item = el("div", "dcn-note" + (row.id === state.selectedNoteId ? " is-current" : ""));
        item.dataset.noteId = row.id;
        const open = button(row.title.trim() || "未命名概念", "dcn-note-open", () => {
          state.selectedNoteId = row.id; renderList(); renderEditor();
        });
        open.setAttribute("aria-current", String(row.id === state.selectedNoteId));
        const deletion = button("", "dcn-note-delete", async () => {
          if (await confirmDelete($("notesPanel"), "删除这个概念？", row.title.trim() || "未命名概念")) {
            await state.noteSaveQueue; await remove("notes", row.id); await renderNotes();
          }
        });
        deletion.title = "删除概念：" + (row.title.trim() || "未命名概念");
        deletion.setAttribute("aria-label", deletion.title);
        item.append(open, deletion); list.append(item);
      }
    }
    function renderEditor() {
      main.replaceChildren();
      const row = state.noteRows.find(note => note.id === state.selectedNoteId);
      if (!row) { main.append(el("div", "offline-empty", "无")); return; }
      const editor = el("section", "dcn-editor");
      const nameLabel = el("label", "", "概念名称"), name = el("input", "dcn-title");
      name.maxLength = 160; name.value = row.title; name.setAttribute("aria-label", "概念名称"); nameLabel.append(name);
      const bodyLabel = el("label", "", "我的概念笔记"), body = el("textarea", "dcn-original");
      body.maxLength = Math.max(12000, row.content.length); body.rows = 9; body.value = row.content; body.setAttribute("aria-label", "我的概念笔记"); bodyLabel.append(body);
      const saved = el("span", "dcn-saved", "已保存在本机"); saved.setAttribute("role", "status");
      const edit = () => {
        row.title = name.value; row.content = body.value; row.updatedAt = stamp();
        const value = {...row}; saved.textContent = "正在保存…";
        state.noteSaveQueue = state.noteSaveQueue.then(() => put("notes", value)).then(() => {
          saved.textContent = "已保存在本机";
        }).catch(error => { saved.textContent = "保存失败，请保留当前页面后重试。"; toast(error?.message || "笔记保存失败"); });
        renderList();
      };
      name.addEventListener("input", edit); body.addEventListener("input", edit);
      editor.append(nameLabel, bodyLabel, saved); main.append(editor);
    }
    search.addEventListener("input", () => { state.noteQuery = search.value.trim(); renderList(); });
    sidebar.append(search, list); host.append(sidebar, main); renderList(); renderEditor();
  }

  async function createNote() {
    await state.noteSaveQueue;
    const row = {id:uid(), title:"", content:"", updatedAt:stamp()};
    await put("notes", row); state.selectedNoteId = row.id; state.noteQuery = "";
    await renderNotes(); $("noteList").querySelector(".dcn-title")?.focus();
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
    const categories = [...new Set(state.graph.nodes.map(n => n.category))];
    const filters = $("graphCategories"); filters.replaceChildren();
    filters.append(button("全部", "offline-chip" + (!state.graphCategory ? " active" : ""), () => { state.graphCategory=""; renderGraph(); }));
    for (const category of categories) {
      filters.append(button(category, "offline-chip" + (state.graphCategory === category ? " active" : ""), () => { state.graphCategory=category; renderGraph(); }));
    }
    const query = $("graphSearch").value.trim().toLocaleLowerCase();
    const nodes = state.graph.nodes.filter(n =>
      (!state.graphCategory || n.category === state.graphCategory) &&
      (!query || [n.name,n.category].join(" ").toLocaleLowerCase().includes(query))
    );
    $("graphCount").textContent = nodes.length + " 个知识点";
    const host = $("graphNodes");
    state.graphController?.destroy(); state.graphController = null;
    host.classList.remove("offline-card-grid"); host.replaceChildren();
    if (!window.DMateOfflineGraph?.mount) {
      host.append(el("div", "kg-empty", "知识图谱组件尚未加载，请刷新后重试。")); return;
    }
    state.graphController = window.DMateOfflineGraph.mount(host, {nodes, onSelect(node) {
      const concept = state.concepts.find(c => c.id === node.id || c.title === node.name);
      if (concept) {
        $("conceptSearch").value = ""; switchPanel("concepts"); fillConceptDetail(concept);
      } else toast("该知识点尚无独立概念条目");
    }});
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
    const [mistakes, notes, practice] = await Promise.all([all("mistakes"), all("notes"), all("practice")]);
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

  function bind() {
    document.querySelectorAll(".offline-nav-item").forEach(item => item.addEventListener("click", () => switchPanel(item.dataset.panel)));
    $("addMistake").addEventListener("click", () => openRecord("mistakes"));
    $("addNote").addEventListener("click", () => createNote().catch(error => toast(error?.message || "无法新建笔记")));
    $("recordForm").addEventListener("submit", event => saveRecord(event).catch(error => toast(error?.message || "本地保存失败")));
    $("cancelRecord").addEventListener("click", () => $("recordDialog").close());
    $("cancelRecordSecondary")?.addEventListener("click", () => $("recordDialog").close());
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    $("graphSearch").addEventListener("input", renderGraph);
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
      state.db = await openDb();
      await restoreNotebookDraft();
      await applyOriginalAppearance();
      configureRenderer();
      await migrateCurrentAccountData();
      await loadResources();
      bind();
      $("saveState").textContent = "本地保存已启用";
      await switchPanel("mistakes");
      document.documentElement.dataset.offlineReady = "true";
    } catch (error) {
      $("saveState").textContent = "初始化失败";
      toast(error?.message || "离线工作区初始化失败");
    }
  }
  init();
})();
