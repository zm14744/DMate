(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const libraryMobile = window.matchMedia("(max-width:1100px)");
  const libraryScroll = {concepts:0, questions:0};
  let libraryDetail = null;
  const state = {
    storage: null, concepts: [], questions: [], graph: null, translations: {concepts:{},questions:{}},
    panel: "graph", selectedQuestion: null, selectedConcept: null,
    revealed: false, analysisRevealed: false,
    drawingController: null, backgroundUrl: "", graphCategory: "", graphSelectedNodeId: "", questionCategory: "",
    questionDifficulty: "", questionType: "", questionSelection: "", questionQuery: "", conceptCategory: "", conceptSelection: "", conceptQuery: "", graphQuery: "", graphController: null,
    librarySelections: {concepts:new Set(), questions:new Set()}, selectionQueue: Promise.resolve(),
    selectedNoteId:null, noteQuery:"", noteRows:[], noteSaveQueue:Promise.resolve(),
    noteDrafts:new Map(), noteSaveStatus:new Map(), noteDeletePending:null,
    appearanceQueue: Promise.resolve(), viewSaveQueue:Promise.resolve(), viewSnapshot:""
  };
  const panelMeta = {
    mistakes: ["错题本", "在本机查看、整理和复习已保存的错题。"],
    notes: ["笔记本", "把自己的理解、推导和学习记录保存在本机。"],
    graph: ["知识图谱", "浏览离散数学知识点及其前置关系。"],
    concepts: ["概念库", "查看定义、解释、公式和易错点，支持中英文切换。"],
    questions: ["练习库", "按章节和难度练习，查看参考答案与解析。"],
    drawing: ["绘图", "使用 DMate 图形编辑器，在本机创建和保存数学图形。"]
  };
  const tr = (value, english) => window.DMateI18n?.t?.(value, english) ?? String(value ?? "");
  const english = () => window.DMateI18n?.isEnglish?.() === true;
  const questionTypeLabels = {
    "单项选择":"Single choice", "多项选择":"Multiple choice", "填空":"Fill in the blank", "计算":"Calculation",
    "简答":"Short answer", "证明":"Proof"
  };
  function localized(value, collection) {
    return english() ? {...value, ...state.translations[collection]?.[value.id]} : value;
  }
  function contentText(tag, className, value) {
    const node = el(tag, className, value);
    node.setAttribute("data-i18n-content", "");
    return node;
  }
  function studySource(value) {
    return window.DMateMathMarkdown?.prepareStudyText?.(value) ?? String(value ?? "");
  }
  function studyLabel(tag, className, value) {
    const node = contentText(tag, className, value), source = studySource(value);
    if (source !== String(value ?? "") || /\$|\\\(|\\\[|`|\*\*/.test(source)) {
      void window.DMateAIAnswer?.render(node, source, {typography:"inline"});
    }
    return node;
  }

  function toast(message) {
    const node = $("offlineToast");
    node.textContent = String(message || "操作未完成");
    node.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { node.hidden = true; }, 3600);
  }
  function storageError(error) {
    const messages = {
      CONFLICT:["记录已在另一页面修改，当前编辑仍保留，请重新打开后重试", "This record changed in another page; your draft is retained. Reopen it and retry"],
      KEY_MISSING:["加密密钥不可用，原数据已保留，请检查当前设备后重试", "The encryption key is unavailable; existing data is retained"],
      AUTHENTICATION_FAILED:["加密资料无法验证，原数据已保留，请勿清除网站数据", "Encrypted data could not be verified; existing data is retained"],
      KEYSTORE_UNAVAILABLE:["系统密钥服务尚未解锁或不可用，请解锁后刷新重试", "Unlock the system key store and reload to retry"],
      NATIVE_UNAVAILABLE:["请更新客户端后再使用离线加密存储，原数据已保留", "Update the client to use encrypted offline storage; existing data is retained"],
      NATIVE_TIMEOUT:["系统密钥服务暂时没有响应，请稍后刷新重试", "The system key service did not respond; reload to retry"],
      STORAGE_BLOCKED:["请关闭旧版离线页面后重试", "Close older offline pages and try again"],
      LEGACY_BLOCKED:["请关闭旧版离线页面后重试", "Close older offline pages and try again"],
      QUOTA_EXCEEDED:["设备存储空间不足，当前编辑仍保留，请释放空间后重试", "Storage is full; your draft is retained. Free some space and retry"],
      TOO_LARGE:["内容超过加密存储上限，当前内容与原数据仍保留", "This content exceeds the encrypted storage limit; current and original data are retained"],
      CLOSED:["账号状态已变化，请重新打开离线页面", "The account changed; reopen the offline workspace"]
    };
    const text = messages[error?.code];
    return text ? tr(...text) : error?.message || tr("离线工作区初始化失败", "The offline workspace could not be initialized");
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
      try { Promise.resolve(handler(event)).catch(error => toast(storageError(error))); }
      catch (error) { toast(storageError(error)); }
    });
    return node;
  }
  function studyButton(text, className, handler) {
    const node = button("", className, handler);
    node.append(studyLabel("span", "", text));
    return node;
  }
  function action(text, className, handler, icon) {
    const node = button("", className, handler);
    const mark = icon ? window.DMateOfflineIcons?.create(icon) : null;
    if (mark) node.append(mark);
    node.append(el("span", "dmate-ui-label", text));
    node.setAttribute("aria-label", text);
    node.title = text;
    return node;
  }
  const escapeHtml = value => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const workspaceOwner = window.DMateGuestSession?.getOwner() || "";
  // Account tabs keep independent workspaces; guest vaults are already tab scoped.
  const viewRecordId = workspaceOwner ? "view:" + window.name : "view";
  let workspaceActive = true;
  const workspaceCurrent = () => workspaceActive && (window.DMateGuestSession?.getOwner() || "") === workspaceOwner;
  function invalidateWorkspace(resetGuest = false) {
    if (!workspaceActive) return;
    workspaceActive = false;
    state.noteRows = []; state.noteDrafts.clear();
    state.drawingController?.destroy?.();
    const storage = state.storage; state.storage = null;
    if (resetGuest && !workspaceOwner) void storage?.destroyGuest?.().catch(() => {});
    else storage?.close();
    for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
    for (const id of ["mistakeList", "noteList", "offlineDrawingHost"]) $(id)?.replaceChildren();
    window.DMateOfflineAppearance?.apply?.({}, null);
    if (resetGuest) window.DMateGuestSession?.reset();
    sessionStorage.removeItem("dmate_offline_migration_v1");
    delete document.documentElement.dataset.offlineReady;
    window.location.reload();
  }
  function requireWorkspace() {
    if (workspaceCurrent()) return;
    invalidateWorkspace();
    throw new Error(tr("账号状态已变化，请重新打开离线页面", "The account has changed; reopen the offline workspace"));
  }
  window.addEventListener("dmate:account-state", () => { if (!workspaceCurrent()) invalidateWorkspace(); });
  window.addEventListener("dmate:guest-session-end", () => invalidateWorkspace(true));
  window.addEventListener("storage", event => {
    if (event.key === "dmate_account_logout_signal_v1" && event.newValue) invalidateWorkspace(true);
  });
  function configureRenderer() {
    window.DMateAIAnswer?.configure({
      markdownToHtml(value) {
        const formatter = window.DMateMathMarkdown;
        if (!formatter) return escapeHtml(value).replace(/\n/g, "<br>");
        return formatter.markdownToHtml(formatter.prepareAiDisplayText(value));
      },
      async renderMath(target) {
        await window.MathJax?.startup?.promise;
        await window.DMateMathMarkdown?.renderMath?.(target);
      }
    });
  }
  function rich(className, value) {
    const node = el("div", className);
    node.setAttribute("data-i18n-content", "");
    if (window.DMateAIAnswer?.render) void window.DMateAIAnswer.render(node, studySource(value), {typography:"chat"});
    else node.textContent = String(value ?? "");
    return node;
  }
  function answerDetails(title, value, className = "wrong-answer-details") {
    const details = el("details", className);
    const analysis = className === "wrong-analysis-details";
    details.append(el("summary", analysis ? "wrong-analysis-summary" : "wrong-answer-summary", tr(title)),
      rich(analysis ? "wrong-analysis-body" : "wrong-answer-inner", value));
    details.addEventListener("toggle", () => {
      if (details.open) void window.DMateAIAnswer?.render(details.lastElementChild, studySource(value), {typography:"chat"});
    });
    return details;
  }
  async function confirmDelete(owner, title, content) {
    if (!window.DMateDeleteConfirm?.request) { toast(tr("删除确认组件尚未加载，请刷新后重试")); return false; }
    return window.DMateDeleteConfirm.request(owner, {title, body:"删除后无法恢复", content, confirmText:"删除"});
  }
  async function transaction(store, _mode, action) {
    requireWorkspace();
    if (!state.storage) throw new Error(tr("离线存储尚未就绪", "Offline storage is not ready"));
    const storage = state.storage;
    const result = await action({
      get:id => storage.get(store, id), put:value => storage.put(store, value),
      delete:id => storage.remove(store, id), getAll:() => storage.all(store)
    });
    requireWorkspace();
    return result;
  }
  const put = (store, value) => transaction(store, "readwrite", os => os.put(value));
  const all = store => transaction(store, "readonly", os => os.getAll());
  const remove = (store, id) => transaction(store, "readwrite", os => os.delete(id));
  async function applyOriginalAppearance() {
    const saved = await transaction("settings", "readonly", os => os.get("appearance"));
    window.DMateOfflineAppearance?.apply(saved?.settings || {}, saved?.backgroundBlob || null);
  }

  async function loadLibrarySelections() {
    const saved = await transaction("settings", "readonly", os => os.get("library-selections"));
    for (const kind of ["concepts", "questions"]) {
      const ids = new Set(state[kind].map(item => item.id));
      state.librarySelections[kind] = new Set((Array.isArray(saved?.[kind]) ? saved[kind] : [])
        .filter(id => typeof id === "string" && ids.has(id)));
    }
  }

  function saveLibrarySelections() {
    const snapshot = {id:"library-selections", updatedAt:stamp(),
      concepts:[...state.librarySelections.concepts], questions:[...state.librarySelections.questions]};
    state.selectionQueue = state.selectionQueue.then(() => put("settings", snapshot))
      .catch(() => toast(tr("选择状态暂时无法保存", "The selection could not be saved.")));
  }

  function matchesLibrarySelection(kind, id, filter) {
    return !filter || state.librarySelections[kind].has(id) === (filter === "selected");
  }

  function libraryRow(kind, record, item) {
    const selected = state.librarySelections[kind];
    const row = el("div", "offline-library-row" + (item.classList.contains("active") ? " active" : ""));
    const hit = el("label", "offline-library-select"), check = el("input", "offline-library-checkbox");
    check.type = "checkbox"; check.checked = selected.has(record.id);
    check.dataset.selectionId = record.id; check.dataset.selectionKind = kind;
    const title = localized(record, kind).title;
    check.setAttribute("aria-label", kind === "concepts" ? tr("选择概念：" + title, "Select concept: " + title)
      : tr("选择题目：" + title, "Select exercise: " + title));
    check.addEventListener("change", () => {
      if (check.checked) selected.add(record.id); else selected.delete(record.id);
      saveLibrarySelections();
      // Keep the open detail and its revealed answer intact when the row stays.
      // A selection-only view removes the toggled row and focuses its successor.
      if (state[kind === "concepts" ? "conceptSelection" : "questionSelection"]) {
        const list = $(kind === "concepts" ? "conceptList" : "questionList"), scrollTop = list.scrollTop;
        const index = [...list.children].indexOf(row);
        if (kind === "concepts") renderConcepts(); else renderQuestions();
        list.scrollTop = scrollTop;
        const checks = list.querySelectorAll(".offline-library-checkbox");
        (checks[Math.min(index, checks.length - 1)] || $(kind === "concepts" ? "conceptSelection" : "questionSelection"))
          .focus({preventScroll:true});
      }
    });
    hit.append(check); row.append(hit, item); return row;
  }

  const stamp = () => new Date().toISOString();
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : "local-" + Date.now() + "-" + Math.random().toString(36).slice(2));

  async function sameStoredValue(left, right) {
    if (Object.is(left,right)) return true;
    if (left instanceof Blob || right instanceof Blob) {
      if (!(left instanceof Blob) || !(right instanceof Blob) || left.type !== right.type || left.size !== right.size) return false;
      const a = new Uint8Array(await left.arrayBuffer()), b = new Uint8Array(await right.arrayBuffer());
      return a.every((byte,index) => byte === b[index]);
    }
    if (!left || !right || typeof left !== "object" || typeof right !== "object" || Array.isArray(left) !== Array.isArray(right)) return false;
    const keys = Object.keys(left);
    if (keys.length !== Object.keys(right).length) return false;
    for (const key of keys) if (!Object.hasOwn(right,key) || !await sameStoredValue(left[key],right[key])) return false;
    return true;
  }

  async function importOfflineSnapshot(payload) {
    if (!payload || typeof payload !== "object" || String(payload.username || "") !== workspaceOwner)
      throw new Error(tr("资料所属账号已变化，请从在线版重新进入", "The snapshot account changed; reopen offline mode from the online page"));
    const written = [];
    const save = async (store,value) => { await put(store,value); written.push([store,value]); };
    const mistakes = new Map((await all("mistakes")).map(row => [row.id,row]));
    const mistakeMetadata = await transaction("settings","readonly",os => os.get("mistake-deletions"));
    for (const item of Array.isArray(payload.wrongQuestions) ? payload.wrongQuestions : []) {
      if (!item || typeof item.question !== "string" || !item.question.trim()) continue;
      const id = String(item.id || uid()), existing = mistakes.get(id), incomingAt = noteTime(item.updatedAt || item.createdAt);
      if (noteTime(mistakeMetadata?.deleted?.[id]) >= incomingAt && mistakeMetadata?.deleted?.[id]) continue;
      if (existing && incomingAt <= noteTime(existing.updatedAt)) continue;
      const reference = item.referenceAnswer;
      const answer = item.answer || (typeof reference === "string" ? reference
        : reference && typeof reference === "object" ? reference.text || reference.answer || JSON.stringify(reference) : "");
      const row = {...existing,id,title:String(item.category || item.question).slice(0,160),statement:item.question,
        answer:String(answer || ""),explanation:String(item.analysis || item.solution || ""),
        knowledgePoints:Array.isArray(item.knowledgePoints) ? item.knowledgePoints : [],status:item.corrected ? "resolved" : "pending",
        createdAt:existing?.createdAt || existing?.updatedAt || new Date(noteTime(item.createdAt) || incomingAt || Date.now()).toISOString(),
        updatedAt:new Date(incomingAt || Date.now()).toISOString()};
      await save("mistakes",row); mistakes.set(id,row);
    }
    const notes = new Map((await all("notes")).map(row => [row.id,row]));
    const noteMetadata = await transaction("settings","readonly",os => os.get("notebook-deletions"));
    for (const note of Array.isArray(payload.notes) ? payload.notes : []) {
      if (!note || typeof note.title !== "string" || typeof note.content !== "string") continue;
      const id = String(note.id || uid()), existing = notes.get(id), incomingAt = noteTime(note.updatedAt);
      if (noteTime(noteMetadata?.deleted?.[id]) >= incomingAt && noteMetadata?.deleted?.[id]) continue;
      if (existing && incomingAt <= noteTime(existing.updatedAt)) continue;
      const row = {...existing,id,title:note.title,content:note.content,updatedAt:new Date(incomingAt || Date.now()).toISOString()};
      await save("notes",row); notes.set(id,row);
    }
    if (typeof payload.drawings === "string" && payload.drawings) {
      const saved = await transaction("drawings","readonly",os => os.get("gallery"));
      let gallery = payload.drawings;
      const incoming = JSON.parse(gallery);
      if (![1,2].includes(incoming?.version) || !Array.isArray(incoming.pages)
          || new Set(incoming.pages.map(page => page?.id)).size !== incoming.pages.length
          || incoming.pages.some(page => !page || typeof page.id !== "string" || !page.id
            || !Array.isArray(page.document?.graphs) || !page.document.graphs.length
            || page.document.graphs.some(graph => !graph || !Array.isArray(graph.vertices) || !Array.isArray(graph.edges)))) {
        throw new Error(tr("绘图库格式无法读取，原数据已保留", "The gallery format could not be read; original data is retained"));
      }
      const pageCount = pages => pages.reduce((count,page) => count + page.document.graphs.length,0);
      if (pageCount(incoming.pages) > 50) throw Object.assign(new Error(),{code:"TOO_LARGE"});
      if (saved?.gallery) {
        const local = JSON.parse(saved.gallery);
        if (Array.isArray(local?.pages) && Array.isArray(incoming?.pages)) {
          const pages = local.pages.slice(), ids = new Set(pages.map(page => page.id));
          for (const page of incoming.pages) if (!ids.has(page.id)) {
            if (pages.length >= 50) throw Object.assign(new Error(),{code:"TOO_LARGE"});
            pages.push(page); ids.add(page.id);
          }
          if (pageCount(pages) > 50) throw Object.assign(new Error(),{code:"TOO_LARGE"});
          gallery = JSON.stringify({...local,pages});
        } else throw new Error(tr("绘图库格式无法读取，原数据已保留", "The gallery format could not be read; original data is retained"));
      }
      await save("drawings",{id:"gallery",gallery,updatedAt:stamp()});
    }
    if (payload.appearance && typeof payload.appearance.settings === "object") {
      const value = {id:"appearance",settings:payload.appearance.settings,updatedAt:stamp()};
      if (payload.appearance.backgroundBlob instanceof Blob) value.backgroundBlob = payload.appearance.backgroundBlob;
      await save("settings",value);
    }
    for (const [store,value] of written) {
      const saved = await transaction(store,"readonly",os => os.get(value.id));
      if (!await sameStoredValue(saved,value)) throw new Error(tr("加密保存校验未通过，原数据已保留", "Encrypted save verification failed; original data is retained"));
    }
    requireWorkspace();
  }

  async function migrateCurrentAccountData() {
    const legacy = sessionStorage.getItem("dmate_offline_migration_v1");
    if (legacy) {
      let payload;
      try { payload = JSON.parse(legacy); }
      catch (_) { throw new Error(tr("旧交接资料无法读取，原数据已保留", "The legacy snapshot could not be read; original data is retained")); }
      if (payload && String(payload.username || "") === workspaceOwner) {
        await importOfflineSnapshot(payload);
        if (sessionStorage.getItem("dmate_offline_migration_v1") === legacy) sessionStorage.removeItem("dmate_offline_migration_v1");
      }
    }
    const token = window.DMateOfflineHandoff?.pendingToken?.();
    if (token) {
      const payload = await window.DMateOfflineHandoff.read(token,{isCurrent:workspaceCurrent});
      requireWorkspace();
      await importOfflineSnapshot(payload);
      await window.DMateOfflineHandoff.ack(token);
    }
  }

  async function loadResources() {
    const [concepts, questions, graph, translations] = await Promise.all([
      fetch("/static/offline-content/concepts.zh-CN.json?v=34", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("概念库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/questions.zh-CN.json?v=34", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("题库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/knowledge_graph.json?v=28", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("知识图谱资源不可用"); return r.json(); }),
      fetch("/static/offline-content/translations.en.json?v=34", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("英文学习内容资源不可用"); return r.json(); })
    ]);
    state.concepts = Array.isArray(concepts.concepts) ? concepts.concepts : [];
    state.questions = Array.isArray(questions.questions) ? questions.questions : [];
    state.graph = graph;
    if (translations.schema_version !== 1 || translations.language !== "en"
        || translations.source_pack_versions?.concepts !== concepts.pack_version
        || translations.source_pack_versions?.questions !== questions.pack_version
        || state.concepts.some(item => !translations.concepts?.[item.id])
        || state.questions.some(item => !translations.questions?.[item.id])) {
      throw Error(tr("中英文学习内容版本不一致，请联网更新离线资源。", "The Chinese and English study packs do not match. Reconnect to update offline resources."));
    }
    state.translations = translations;
  }

  function setNetworkStatus() {
    const online = navigator.onLine;
    $("returnOnline").disabled = !online;
    // Entry controls keep their accessible name without hover tooltips.
    $("returnOnline").removeAttribute("title");
  }

  function syncLibraryFullView(kind) {
    const concepts = kind === "concepts";
    const record = concepts ? state.selectedConcept : state.selectedQuestion;
    const entry = $(concepts ? "conceptFullView" : "questionFullView");
    const recordId = record?.id || "";
    if (entry.dataset.recordId !== recordId) libraryScroll[kind] = 0;
    entry.dataset.recordId = recordId;
    entry.disabled = !record;
    entry.textContent = tr("完整查看", "Full view");
    entry.setAttribute("aria-label", concepts ? tr("完整查看概念详情", "View complete concept details")
      : tr("完整查看练习详情", "View complete exercise details"));
    entry.setAttribute("aria-expanded", String(libraryDetail?.kind === kind && $("libraryDetailDialog").open));
    if (libraryDetail?.kind === kind) {
      $("libraryDetailTitle").textContent = concepts ? tr("概念详情", "Concept details") : tr("练习详情", "Exercise details");
      if (!record) closeLibraryDetail(false);
    }
  }

  function closeLibraryDetail(restoreFocus = true) {
    const current = libraryDetail;
    if (!current) return;
    libraryDetail = null;
    libraryScroll[current.kind] = current.article.scrollTop;
    if ($("libraryDetailDialog").open) $("libraryDetailDialog").close();
    current.origin.replaceWith(current.article);
    current.article.scrollTop = libraryScroll[current.kind];
    const entry = $(current.kind === "concepts" ? "conceptFullView" : "questionFullView");
    entry.setAttribute("aria-expanded", "false");
    if (restoreFocus) {
      const target = current.trigger?.isConnected && current.trigger.getClientRects().length ? current.trigger : entry;
      if (target.getClientRects().length) target.focus({preventScroll:true});
    }
  }

  function openLibraryDetail(kind, trigger = null) {
    if (!libraryMobile.matches || !["concepts", "questions"].includes(kind)) return;
    const record = kind === "concepts" ? state.selectedConcept : state.selectedQuestion;
    if (!record) return;
    const dialog = $("libraryDetailDialog");
    if (libraryDetail?.kind === kind && dialog.open) return;
    closeLibraryDetail(false);
    const article = $(kind === "concepts" ? "conceptDetail" : "questionDetail");
    const entry = $(kind === "concepts" ? "conceptFullView" : "questionFullView");
    const origin = document.createComment("library detail origin");
    article.before(origin);
    libraryDetail = {kind, article, origin, trigger:trigger || entry};
    $("libraryDetailHost").append(article);
    $("libraryDetailTitle").textContent = kind === "concepts" ? tr("概念详情", "Concept details") : tr("练习详情", "Exercise details");
    dialog.showModal();
    article.scrollTop = libraryScroll[kind];
    entry.setAttribute("aria-expanded", "true");
    $("libraryDetailClose").focus({preventScroll:true});
    requestAnimationFrame(() => {
      if (libraryDetail?.article === article && dialog.open) article.scrollTop = libraryScroll[kind];
    });
  }

  function switchPanel(name) {
    if (!panelMeta[name]) return;
    closeLibraryDetail(false);
    if (name !== "graph" && state.graphController) {
      state.graphController.destroy(); state.graphController = null;
    }
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
    let rendering;
    if (name === "mistakes") rendering = renderMistakes();
    if (name === "notes") rendering = renderNotes();
    if (name === "drawing") rendering = mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
    window.dispatchEvent(new CustomEvent("dmate:offlinepanelchange", {detail:{panel:name,title:panelMeta[name][0]}}));
    return rendering;
  }

  async function renderMistakes() {
    const [saved, metadata] = await Promise.all([all("mistakes"), transaction("settings", "readonly", os => os.get("mistake-deletions"))]);
    const rows = saved.filter(row => !metadata?.deleted?.[row.id]
      || noteTime(metadata.deleted[row.id]) < noteTime(row.updatedAt))
      .sort((a,b) => noteTime(b.updatedAt) - noteTime(a.updatedAt));
    $("mistakeCount").textContent = tr(rows.length + " 道错题", rows.length + " mistakes");
    const list = $("mistakeList");
    list.classList.add("wrong-book-list");
    list.replaceChildren();
    if (!rows.length) {
      list.append(el("div", "wrong-empty offline-empty", tr("无", "None")));
      return;
    }
    for (const row of rows) {
      const card = el("article", "wrong-card");
      card.dataset.recordId = row.id;
      const top = el("div", "wrong-card-top");
      top.append(el("span", "wrong-date", new Date(noteTime(row.createdAt || row.updatedAt)).toLocaleString()));
      card.append(top, rich("wrong-question", row.statement || row.content || ""));
      const knowledgeLabels = [...new Set((row.knowledgePoints || []).map(point =>
        state.graph?.nodes?.find(node => node.id === point)?.name
        || state.concepts.find(concept => concept.id === point)?.title
        || (typeof point === "string" && /[\u3400-\u9fff]/.test(point) ? point : "")
      ).filter(Boolean))];
      if (knowledgeLabels.length) {
        const meta = el("div", "wrong-meta"), line = el("div", "wrong-meta-row");
        line.append(el("span", "wrong-meta-label", tr("整题涉及")), el("span", "wrong-meta-value", knowledgeLabels.join("、")));
        meta.append(line); card.append(meta);
      }
      card.append(answerDetails("查看答案", row.answer || tr("这条记录没有保存参考答案。", "No reference answer was saved for this record.")));
      const actions = el("div", "wrong-actions record-actions");
      const deletion = action(tr("移出错题本"), "secondary danger", async () => {
        if (await confirmDelete($("mistakesPanel"), "移出这道错题？", row.statement || row.title)) {
          await deleteOfflineRecord("mistakes", row, "mistake-deletions"); await renderMistakes();
        }
      });
      deletion.dataset.action = "delete-mistake";
      actions.append(deletion); card.append(actions); list.append(card);
    }
  }

  function noteTime(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(0, numeric) : Date.parse(value) || 0;
  }

  async function deleteOfflineRecord(store, row, metadataId) {
    requireWorkspace();
    const previous = await transaction("settings", "readonly", os => os.get(metadataId));
    const deletedAt = Math.max(Date.now(), noteTime(row.updatedAt) + 1, noteTime(previous?.deleted?.[row.id]));
    await state.storage.batch([
      {type:"put",store:"settings",value:{...previous,id:metadataId,
        deleted:{...previous?.deleted,[row.id]:deletedAt},updatedAt:stamp()}},
      {type:"delete",store,id:row.id}
    ]);
    requireWorkspace();
  }

  function setNoteSaveStatus(id, message) {
    if (!workspaceCurrent()) return;
    state.noteSaveStatus.set(id, message);
    const saved = $("noteList")?.querySelector(".dcn-saved");
    if (saved?.dataset.noteId === id) saved.textContent = message;
  }

  function queueNoteSave(row) {
    const snapshot = {...row};
    state.noteDrafts.set(row.id, snapshot);
    setNoteSaveStatus(row.id, tr("正在保存…", "Saving…"));
    state.noteSaveQueue = state.noteSaveQueue.then(async () => {
      if (!workspaceCurrent()) { invalidateWorkspace(); return false; }
      try {
        await put("notes", snapshot);
        if (!workspaceCurrent()) return false;
        if (state.noteDrafts.get(row.id) === snapshot) {
          state.noteDrafts.delete(row.id);
          setNoteSaveStatus(row.id, "");
        }
        return true;
      } catch (error) {
        if (!workspaceCurrent()) return false;
        if (state.noteDrafts.get(row.id) === snapshot) {
          setNoteSaveStatus(row.id, tr("保存失败，请保留当前页面后重试。", "Save failed; keep this page open and try again."));
          toast(storageError(error));
        }
        return false;
      }
    });
    return state.noteSaveQueue;
  }

  async function flushNoteDrafts() {
    await state.noteSaveQueue;
    if (!workspaceCurrent()) { invalidateWorkspace(); return false; }
    for (const row of [...state.noteDrafts.values()]) queueNoteSave(row);
    await state.noteSaveQueue;
    return state.noteDrafts.size === 0;
  }

  async function deleteNote(row) {
    await deleteOfflineRecord("notes", row, "notebook-deletions");
    state.noteDrafts.delete(row.id);
    state.noteSaveStatus.delete(row.id);
  }

  async function renderNotes() {
    const revision = state.notesRenderRevision = (state.notesRenderRevision || 0) + 1;
    await flushNoteDrafts();
    const [savedNotes, metadata] = await Promise.all([all("notes"), transaction("settings", "readonly", os => os.get("notebook-deletions"))]);
    if (revision !== state.notesRenderRevision) return;
    const byId = new Map(savedNotes.filter(row => !metadata?.deleted?.[row.id]
      || noteTime(metadata.deleted[row.id]) < noteTime(row.updatedAt)).map(row => [row.id, row]));
    // A failed write stays visible and retryable when changing panels. Read the
    // drafts after IndexedDB finishes so newer input also wins this merge.
    for (const [id, row] of state.noteDrafts) byId.set(id, {...row});
    const rows = [...byId.values()].sort((a,b) => noteTime(b.updatedAt) - noteTime(a.updatedAt));
    state.noteRows = rows;
    if (!rows.some(row => row.id === state.selectedNoteId)) state.selectedNoteId = rows[0]?.id || null;
    const host = $("noteList");
    host.replaceChildren();
    const sidebar = el("aside", "dcn-sidebar"), main = el("section", "dcn-main");
    sidebar.setAttribute("aria-label", tr("概念笔记列表", "Concept note list"));
    const create = button(tr("＋ 新概念", "＋ New concept"), "dcn-new", createNote);
    create.id = "addNote";
    const search = el("input", "dcn-search");
    search.type = "search"; search.placeholder = tr("搜索", "Search"); search.setAttribute("aria-label", tr("搜索", "Search")); search.value = state.noteQuery;
    const searchWrap = el("div", "dcn-search-wrap");
    const searchClear = button("", "dcn-search-clear", () => {
      search.value = ""; state.noteQuery = ""; renderList(); search.focus({preventScroll:true});
    });
    searchClear.title = tr("清空搜索", "Clear search"); searchClear.setAttribute("aria-label", searchClear.title);
    searchWrap.append(search, searchClear);
    const list = el("div", "dcn-list");
    const editor = el("section", "dcn-editor");
    const nameLabel = el("label", "", tr("概念名称", "Concept name")), name = el("textarea", "dcn-title");
    name.maxLength = 160; name.rows = 1; name.setAttribute("aria-label", tr("概念名称", "Concept name")); nameLabel.append(name);
    const bodyLabel = el("label", "", tr("概念内容", "Concept content")), body = el("textarea", "dcn-original");
    body.rows = 1; body.setAttribute("aria-label", tr("概念内容", "Concept content")); bodyLabel.append(body);
    const saved = el("span", "dcn-saved"); saved.setAttribute("role", "status");
    editor.append(nameLabel, bodyLabel, saved);
    main.append(editor);
    function renderActions() {
      const empty = state.noteRows.length === 0;
      $("notesPanel").classList.toggle("is-empty", empty);
      main.hidden = empty;
      name.disabled = body.disabled = state.noteDeletePending === state.selectedNoteId;
      for (const deletion of host.querySelectorAll(".dcn-note-delete")) deletion.disabled = Boolean(state.noteDeletePending);
    }
    function renderList() {
      list.replaceChildren();
      searchClear.hidden = !search.value;
      const query = state.noteQuery.trim().toLocaleLowerCase();
      const visible = state.noteRows.filter(row => !query || (row.title + "\n" + row.content).toLocaleLowerCase().includes(query));
      if (!visible.length) list.append(el("p", "dcn-list-empty", tr("无", "None")));
      const names = new Map();
      for (const row of state.noteRows) {
        const title = row.title.trim() || tr("未命名概念", "Untitled concept");
        names.set(title, (names.get(title) || 0) + 1);
      }
      for (const row of visible) {
        const title = row.title.trim() || tr("未命名概念", "Untitled concept");
        const item = el("div", "dcn-note" + (row.id === state.selectedNoteId ? " is-current" : ""));
        item.dataset.noteId = row.id;
        const open = button(title, "dcn-note-open", () => {
          state.selectedNoteId = row.id; renderList(); renderEditor(); renderActions();
        });
        if (row.title.trim()) open.setAttribute("data-i18n-content", "");
        open.setAttribute("aria-current", String(row.id === state.selectedNoteId));
        const deletion = button("", "dcn-note-delete", async event => {
          event.stopPropagation();
          if (state.noteDeletePending) return;
          state.noteDeletePending = row.id; renderActions();
          try {
            if (!await confirmDelete($("notesPanel"), "删除这个概念？", title)) return;
            if (!await flushNoteDrafts()) { toast("笔记尚未保存，请保留当前页面后重试。"); return; }
            await deleteNote(state.noteRows.find(note => note.id === row.id) || row); await renderNotes();
          } finally {
            state.noteDeletePending = null; renderActions();
          }
        });
        deletion.title = tr("删除", "Delete") + title;
        deletion.setAttribute("aria-label", tr("删除概念：" + title, "Delete concept: " + title) + (names.get(title) > 1 ? "（" + row.id + "）" : ""));
        item.append(open, deletion); list.append(item);
      }
    }
    function renderEditor() {
      const row = state.noteRows.find(note => note.id === state.selectedNoteId);
      editor.hidden = !row;
      name.value = row?.title || ""; body.value = row?.content || "";
      body.maxLength = Math.max(12000, row?.content.length || 0);
      saved.dataset.noteId = row?.id || "";
      saved.textContent = row ? state.noteSaveStatus.get(row.id) || "" : "";
    }
    const edit = () => {
      const row = state.noteRows.find(note => note.id === state.selectedNoteId);
      if (!row) return;
      row.title = name.value; row.content = body.value;
      row.updatedAt = new Date(Math.max(Date.now(), noteTime(row.updatedAt) + 1)).toISOString();
      queueNoteSave(row); renderList();
    };
    name.addEventListener("input", edit); body.addEventListener("input", edit);
    search.addEventListener("input", () => { state.noteQuery = search.value; renderList(); });
    sidebar.append(create, searchWrap, list); host.append(sidebar, main);
    renderList(); renderEditor(); renderActions();
    window.DMateTextareaAutosize?.refresh?.(host);
  }

  async function createNote() {
    if (!await flushNoteDrafts()) { toast("笔记尚未保存，请保留当前页面后重试。"); return; }
    const row = {id:uid(), title:"", content:"", createdAt:stamp(), updatedAt:stamp()};
    await put("notes", row); state.selectedNoteId = row.id; state.noteQuery = "";
    await renderNotes(); $("noteList").querySelector(".dcn-title")?.focus({preventScroll:true});
  }

  async function addQuestionMistake(question) {
    const rows = await all("mistakes");
    const existing = rows.find(row => row.questionId === question.id);
    const record = {
      id: existing?.id || uid(), questionId: question.id, title: question.title,
      statement: question.statement, answer: question.answer_text || (question.answer || []).join("、"),
      explanation: question.explanation, knowledgePoints: question.knowledge_points || [],
      status: "pending", createdAt:existing?.createdAt || existing?.updatedAt || stamp(), updatedAt: stamp()
    };
    await put("mistakes", record);
    toast(existing ? tr("已更新错题记录", "Mistake updated") : tr("已加入错题本", "Added to mistake book"));
    if (state.panel === "mistakes") renderMistakes();
  }

  function chapterCategories() {
    const graphCategories = (state.graph?.nodes || []).map(node => node.category).filter(Boolean);
    const categories = graphCategories.length ? graphCategories
      : [...state.concepts, ...state.questions].map(item => item.category).filter(Boolean);
    return [...new Set(categories)].sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
  }

  function fillChapterFilter(select, value) {
    const categories = chapterCategories();
    const values = ["", ...categories];
    if (select.options.length !== values.length || values.some((category, index) => select.options[index]?.value !== category)) {
      select.replaceChildren(...values.map(category => new Option(category ? tr(category) : tr("全部章节", "All topics"), category)));
    } else {
      for (const option of select.options) option.textContent = option.value ? tr(option.value) : tr("全部章节", "All topics");
    }
    select.value = values.includes(value) ? value : "";
    return select.value;
  }

  function fillQuestionFilters() {
    state.questionCategory = fillChapterFilter($("questionCategory"), state.questionCategory);
    const type = $("questionType"), types = ["", ...Object.keys(questionTypeLabels).filter(value => state.questions.some(question => question.type === value))];
    if (type.options.length !== types.length || types.some((value, index) => type.options[index]?.value !== value)) {
      type.replaceChildren(...types.map(value => new Option(value ? tr(value) : tr("全部题型", "All question types"), value)));
    } else for (const option of type.options) option.textContent = option.value ? tr(option.value) : tr("全部题型", "All question types");
    type.value = types.includes(state.questionType) ? state.questionType : "";
    state.questionType = type.value;
    state.questionSelection = fillSelectionFilter($("questionSelection"), state.questionSelection);
  }

  function fillSelectionFilter(select, value) {
    const labels = {"":tr("全部状态", "All statuses"), selected:tr("已选择", "Selected"), unselected:tr("未选择", "Unselected")};
    for (const option of select.options) option.textContent = labels[option.value];
    select.value = Object.hasOwn(labels, value) ? value : "";
    return select.value;
  }

  function openConcept(concept) {
    // A graph/related/question link may point outside the current search or
    // chapter. Move all filters and selection together before rebuilding.
    state.selectedConcept = concept;
    if (state.conceptCategory && state.conceptCategory !== concept.category) {
      state.conceptCategory = concept.category;
    }
    state.conceptQuery = "";
    $("conceptSearch").value = "";
    if (!matchesLibrarySelection("concepts", concept.id, state.conceptSelection)) {
      state.conceptSelection = ""; $("conceptSelection").value = "";
    }
    switchPanel("concepts");
    $("conceptDetail").scrollTop = 0;
    libraryScroll.concepts = 0;
    openLibraryDetail("concepts");
  }

  function openGraphModule(node) {
    state.graphCategory = node.category;
    state.graphSelectedNodeId = node.id;
    switchPanel("graph");
    state.graphController?.select(node.id, {reveal:true});
  }

  function difficultyName(value) {
    if (value === "基础") return "简单";
    if (value === "进阶" || value === "提高") return "困难";
    return value;
  }

  function openQuestion(question) {
    state.questionCategory = ""; state.questionDifficulty = ""; state.questionType = "";
    $("questionCategory").value = ""; $("questionDifficulty").value = ""; $("questionType").value = "";
    if (!matchesLibrarySelection("questions", question.id, state.questionSelection)) {
      state.questionSelection = ""; $("questionSelection").value = "";
    }
    if (!questionMatchesSearch(question, normalizedSearch($("questionSearch").value))) $("questionSearch").value = "";
    state.selectedQuestion = question;
    state.revealed = false;
    state.analysisRevealed = false;
    switchPanel("questions");
    $("questionDetail").scrollTop = 0;
    libraryScroll.questions = 0;
    openLibraryDetail("questions");
  }

  function questionGraphNodes(question) {
    const ids = new Set();
    for (const id of question.knowledge_points || []) {
      const concept = state.concepts.find(item => item.id === id);
      if (concept?.graph_node_id) ids.add(concept.graph_node_id);
    }
    for (const id of question.graph_node_ids || []) ids.add(id);
    return [...ids].map(id => (state.graph?.nodes || []).find(node => node.id === id)).filter(Boolean);
  }

  function graphModuleSection(nodes, className, linkClassName) {
    if (!nodes.length) return null;
    const section = el("section", "detail-section " + className);
    section.append(el("h3", "", tr("所属图谱模块", "Knowledge-map module")));
    const links = el("div", "prereq-list");
    for (const node of nodes) {
      const label = window.DMateKnowledgeLanguage?.label?.(node.name) ?? tr(node.name);
      const link = studyButton(label, linkClassName, () => openGraphModule(node));
      link.dataset.graphNodeId = node.id;
      link.dataset.graphCategory = node.category;
      links.append(link);
    }
    section.append(links);
    return section;
  }

  function relatedExercisesSection(questionIds, className) {
    const section = el("section", "detail-section " + className);
    section.append(el("h3", "", tr("关联练习", "Related exercises")));
    const links = el("div", "prereq-list");
    const seen = new Set(), ranks = {"简单":0, "中等":1, "困难":2};
    const exercises = (questionIds || []).map((id, index) => ({question:state.questions.find(q => q.id === id), index}))
      .filter(({question}) => {
        if (!question || seen.has(question.id)) return false;
        seen.add(question.id); return true;
      })
      .sort((left, right) => (ranks[difficultyName(left.question.difficulty)] ?? 3) - (ranks[difficultyName(right.question.difficulty)] ?? 3)
        || left.index - right.index);
    for (const {question} of exercises) {
      const level = difficultyName(question.difficulty);
      const link = studyButton([tr(level), localized(question, "questions").title].filter(Boolean).join(" "), "", () => openQuestion(question));
      link.dataset.questionId = question.id;
      link.dataset.difficulty = level;
      links.append(link);
    }
    if (!links.children.length) links.append(el("span", "", tr("暂无关联练习", "No related exercises yet")));
    section.append(links);
    return section;
  }

  function renderGraphLearningLinks(node) {
    const wrapper = el("div", "offline-graph-learning-links");
    const concept = state.concepts.find(item => item.id === node.id);
    if (concept) {
      const section = el("section", "detail-section graph-parent-concept");
      section.append(el("h3", "", tr("总概念", "Overview concept")));
      const links = el("div", "prereq-list");
      const link = studyButton(localized(concept, "concepts").title, "", () => openConcept(concept));
      link.dataset.conceptId = concept.id;
      links.append(link); section.append(links); wrapper.append(section);
    }
    const questionIds = concept?.related_questions
      || state.questions.filter(question => (question.graph_node_ids || []).includes(node.id)).map(question => question.id);
    wrapper.append(relatedExercisesSection(questionIds, "graph-related-exercises"));
    return wrapper;
  }

  function normalizedSearch(value) {
    return String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase();
  }

  function titleMatchesSearch(record, collection, query) {
    if (!query) return true;
    const translated = state.translations[collection][record.id];
    return [record.title, translated?.title].some(title => normalizedSearch(title).includes(query));
  }

  function questionMatchesSearch(question, query) {
    return titleMatchesSearch(question, "questions", query);
  }

  function renderQuestions() {
    fillQuestionFilters();
    state.questionQuery = $("questionSearch").value;
    window.DMateSearchControls?.refresh?.($("questionSearch"));
    const query = normalizedSearch(state.questionQuery);
    const filtered = state.questions.filter(q =>
      (!state.questionCategory || q.category === state.questionCategory) &&
      (!state.questionDifficulty || difficultyName(q.difficulty) === state.questionDifficulty) &&
      (!state.questionType || q.type === state.questionType) &&
      matchesLibrarySelection("questions", q.id, state.questionSelection) &&
      questionMatchesSearch(q, query)
    );
    $("questionCount").textContent = tr(filtered.length + " 道题目", filtered.length + (filtered.length === 1 ? " exercise" : " exercises"));
    const list = $("questionList");
    list.replaceChildren();
    for (const question of filtered) {
      const display = localized(question, "questions");
      const item = button("", "question-item" + (state.selectedQuestion?.id === question.id ? " active" : ""), () => selectQuestion(question));
      item.setAttribute("data-i18n-content", "");
      item.dataset.questionId = question.id;
      item.setAttribute("aria-current", String(state.selectedQuestion?.id === question.id));
      item.append(studyLabel("strong", "", display.title), el("small", "", [tr(question.category), tr(difficultyName(question.difficulty)), tr(question.type)].filter(Boolean).join(" ")));
      list.append(libraryRow("questions", question, item));
    }
    if (state.selectedQuestion && filtered.some(q => q.id === state.selectedQuestion.id)) {
      renderQuestionDetail(state.selectedQuestion);
    } else if (filtered.length) selectQuestion(filtered[0]);
    else {
      state.selectedQuestion = null;
      state.revealed = false;
      state.analysisRevealed = false;
      $("questionDetail").replaceChildren(el("div","offline-empty",tr("无", "None")));
    }
    syncLibraryFullView("questions");
  }

  function selectQuestion(question) {
    state.selectedQuestion = question;
    state.revealed = false;
    state.analysisRevealed = false;
    document.querySelectorAll(".question-item").forEach(node => {
      const selected = node.dataset.questionId === question.id;
      node.classList.toggle("active", selected); node.setAttribute("aria-current", String(selected));
      node.closest(".offline-library-row")?.classList.toggle("active", selected);
    });
    renderQuestionDetail(question);
  }

  function renderQuestionDetail(question) {
    const detail = $("questionDetail"), display = localized(question, "questions");
    detail.setAttribute("data-i18n-content", "");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", [tr(question.category), tr(difficultyName(question.difficulty)), tr(question.type)].filter(Boolean).join(" ")));
    detail.append(studyLabel("h2", "detail-title", display.title));
    const concepts = el("section", "detail-section question-concept-links question-parent-concepts");
    concepts.append(el("h3", "", tr("所属概念", "Related concepts")));
    const conceptLinks = el("div", "prereq-list");
    for (const id of new Set(question.knowledge_points || [])) {
      const concept = state.concepts.find(item => item.id === id);
      if (concept) {
        const link = studyButton(localized(concept, "concepts").title, "", () => openConcept(concept));
        link.dataset.conceptId = id; conceptLinks.append(link);
      }
    }
    if (conceptLinks.children.length) { concepts.append(conceptLinks); detail.append(concepts); }
    const graphModules = graphModuleSection(questionGraphNodes(question), "question-graph-module question-graph-modules", "question-graph-module-link");
    if (graphModules) detail.append(graphModules);
    const statement = el("div", "detail-section wrong-question-section");
    statement.append(el("h3", "", tr("题目", "Question")));
    statement.append(rich("wrong-question", display.statement));
    detail.append(statement);

    if (Array.isArray(question.options) && question.options.length) {
      const options = el("div", "detail-section");
      options.append(el("h3", "", tr("选项", "Options")));
      const list = el("div", "question-options");
      list.setAttribute("role", "list");
      for (const option of display.options) {
        const node = el("div", "question-option");
        node.setAttribute("role", "listitem");
        node.append(el("span", "question-option-key", option.key + "."), rich("question-option-text", option.text));
        list.append(node);
      }
      options.append(list);
      detail.append(options);
    }

    const disclosure = (kind, key, caption, englishCaption, body) => {
      const box = el("details", "wrong-" + kind + "-details");
      box.open = state[key];
      const summary = el("summary", "wrong-" + kind + "-summary", tr(caption, englishCaption));
      summary.addEventListener("click", event => {
        event.preventDefault();
        if (!box.isConnected || state.selectedQuestion?.id !== question.id) return;
        box.open = !box.open;
        state[key] = box.open;
      });
      box.append(summary, body);
      box.addEventListener("toggle", () => {
        if (box.isConnected && state.selectedQuestion?.id === question.id) state[key] = box.open;
      });
      detail.append(box);
    };
    const choice = ["单项选择", "多项选择"].includes(question.type);
    disclosure("answer", "revealed", "查看答案", "View answer", choice
      ? contentText("div", "wrong-answer-inner", (question.answer || []).join("、"))
      : rich("wrong-answer-inner", display.answer_text || ""));
    disclosure("analysis", "analysisRevealed", "查看解析", "View explanation",
      rich("wrong-analysis-body", display.explanation || tr("暂无解析。", "No explanation available.")));
    const actions = el("div", "question-actions");
    const add = action(tr("加入错题本", "Add to mistake book"), "secondary", () => addQuestionMistake(question), "book-open");
    add.dataset.action = "add-to-mistakes";
    actions.append(add); detail.append(actions);
    syncLibraryFullView("questions");
  }

  function fillConceptDetail(concept) {
    state.selectedConcept = concept;
    const detail = $("conceptDetail"), display = localized(concept, "concepts");
    detail.setAttribute("data-i18n-content", "");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", tr(concept.category)));
    detail.append(studyLabel("h2", "detail-title", display.title));
    detail.append(rich("concept-summary", display.summary));
    const topic = state.concepts.find(item => item.id === concept.graph_node_id);
    const children = (concept.related_concepts || []).map(id => state.concepts.find(item => item.id === id)).filter(Boolean);
    if (children.length || (topic && topic.id !== concept.id)) {
      const section = el("section", "detail-section concept-topic-links");
      section.append(el("h3", "", children.length ? tr("细分概念", "Detailed concepts") : tr("所属总概念", "Parent concept")));
      const links = el("div", "prereq-list");
      for (const item of children.length ? children : [topic]) {
        const link = studyButton(localized(item, "concepts").title, "", () => openConcept(item));
        link.dataset.conceptId = item.id;
        links.append(link);
      }
      section.append(links); detail.append(section);
    }
    const graphNode = (state.graph?.nodes || []).find(node => node.id === (concept.graph_node_id || concept.id));
    if (graphNode) {
      detail.append(graphModuleSection([graphNode], "concept-graph-module", "concept-graph-module-link"));
    }
    document.querySelectorAll(".concept-item").forEach(item => {
      const selected = item.dataset.conceptId === concept.id;
      item.classList.toggle("active", selected); item.setAttribute("aria-current", String(selected));
      item.closest(".offline-library-row")?.classList.toggle("active", selected);
    });
    const section = (title, content) => {
      const box = el("section", "detail-section");
      box.append(el("h3", "", tr(title)));
      if (Array.isArray(content)) {
        box.append(rich("concept-detail-text", content.map(item => "- " + String(item).replace(/\n/g, "\n  ")).join("\n")));
      } else box.append(rich("concept-detail-text", content || tr("暂无内容。", "No content available.")));
      detail.append(box);
    };
    section("基本定义", display.definition);
    section("理解与说明", display.explanation);
    section("数学符号", display.notation || []);
    section("常见错误", display.common_mistakes || []);
    if (concept.id !== concept.graph_node_id) {
      detail.append(relatedExercisesSection(concept.related_questions, "concept-related-exercises"));
    }
    syncLibraryFullView("concepts");
  }

  function renderConcepts() {
    state.conceptCategory = fillChapterFilter($("conceptCategory"), state.conceptCategory);
    state.conceptSelection = fillSelectionFilter($("conceptSelection"), state.conceptSelection);
    const query = normalizedSearch($("conceptSearch").value);
    state.conceptQuery = $("conceptSearch").value;
    window.DMateSearchControls?.refresh?.($("conceptSearch"));
    const rows = state.concepts.filter(c => {
      return (!state.conceptCategory || c.category === state.conceptCategory)
        && matchesLibrarySelection("concepts", c.id, state.conceptSelection)
        && titleMatchesSearch(c, "concepts", query);
    });
    $("conceptCount").textContent = tr(rows.length + " 个概念", rows.length + (rows.length === 1 ? " concept" : " concepts"));
    const list = $("conceptList"); list.replaceChildren();
    for (const concept of rows) {
      const display = localized(concept, "concepts");
      const item = button("", "concept-item" + (state.selectedConcept?.id === concept.id ? " active" : ""), () => {
        fillConceptDetail(concept);
      });
      item.dataset.conceptId = concept.id;
      item.setAttribute("data-i18n-content", "");
      item.setAttribute("aria-current", String(state.selectedConcept?.id === concept.id));
      item.append(studyLabel("strong", "", display.title), el("small", "", tr(concept.category)));
      list.append(libraryRow("concepts", concept, item));
    }
    if (state.selectedConcept && rows.some(c => c.id === state.selectedConcept.id)) fillConceptDetail(state.selectedConcept);
    else if (rows.length) fillConceptDetail(rows[0]);
    else {
      state.selectedConcept = null;
      $("conceptDetail").replaceChildren(el("div","offline-empty",tr("无", "None")));
    }
    syncLibraryFullView("concepts");
  }

  function renderGraph() {
    if (!state.graph?.nodes) return;
    const host = $("knowledgeGraphModal");
    state.graphController?.destroy(); state.graphController = null;
    if (!window.DMateOfflineGraph?.mount) {
      $("knowledgeGraphCanvas").replaceChildren(el("div", "kg-empty", "知识图谱组件尚未加载，请刷新后重试。")); return;
    }
    state.graphController = window.DMateOfflineGraph.mount(host, {
      nodes: state.graph.nodes, category: state.graphCategory || "全部", selectedId: state.graphSelectedNodeId,
      onCategoryChange(category) { state.graphCategory = category === "全部" ? "" : category; },
      onSelectionChange(node) { if (node) state.graphSelectedNodeId = node.id; },
      onStatus: toast,
      renderLearningLinks: renderGraphLearningLinks,
      onSelect(node) {
      const concept = state.concepts.find(c => c.id === node.id || c.title === node.name);
      if (concept) {
        openConcept(concept);
      } else toast("该知识点尚无独立概念条目");
      }
    });
  }

  async function mountDrawing() {
    if (state.drawingController) return;
    const host = $("offlineDrawingHost");
    if (!window.DMateDrawingWorkspace?.mount) throw new Error(tr("绘图组件尚未加载，请刷新页面后重试"));
    const storage = state.storage;
    const saved = await transaction("drawings", "readonly", os => os.get("gallery"));
    requireWorkspace();
    if (state.drawingController) return;
    state.drawingController = window.DMateDrawingWorkspace.mount(host, {
      persistent:false,sessionState:{},
      persistence:{initialGallery:saved?.gallery || null,
        save:async snapshot => {
          requireWorkspace();
          await storage.put("drawings", {id:"gallery",gallery:JSON.stringify(snapshot),updatedAt:stamp()});
          requireWorkspace();
        }},
      features:{ai:false,upload:false},
      legacyDocument:{body_text:"",graphs:[{id:"G1",name:"我的图形",directed:false,weighted:false,vertices:[],edges:[]}]},
      onChange:() => {}
    });
  }

  async function returnOnline() {
    if (!navigator.onLine) return toast(tr("当前没有网络，在线版暂时无法打开"));
    if (!await flushNoteDrafts()) return toast(tr("笔记尚未保存，请重试后再离开", "The note is not saved; retry before leaving"));
    if (state.drawingController && !await state.drawingController.flush()) return;
    await Promise.all([state.viewSaveQueue,state.appearanceQueue,state.selectionQueue]);
    window.location.assign("/");
  }

  async function saveAppearance(changes) {
    const saved = await transaction("settings", "readonly", os => os.get("appearance"));
    const patch = changes?.settings || changes || {};
    const next = {...(saved?.settings || {})};
    for (const key of ["mode","accent","fontSize","panelOpacity","bubbleOpacity","backgroundFit","blur","mask"])
      if (Object.hasOwn(patch,key)) next[key] = patch[key];
    const value = {...saved,id:"appearance",settings:next,updatedAt:stamp()};
    if (changes?.removeBackground) delete value.backgroundBlob;
    else if (changes?.backgroundBlob instanceof Blob) value.backgroundBlob = changes.backgroundBlob;
    await put("settings", value);
    window.DMateOfflineAppearance?.apply(next,value.backgroundBlob || null);
    window.dispatchEvent(new CustomEvent("offline:appearance-applied",{detail:{settings:next}}));
  }

  function bind() {
    const checkpoint = () => {
      if (!workspaceCurrent() || !state.storage) return;
      const snapshot = {};
      for (const key of ["panel", "revealed", "analysisRevealed", "graphCategory", "graphSelectedNodeId", "questionCategory", "questionDifficulty", "questionType", "questionSelection", "questionQuery", "conceptCategory", "conceptSelection", "conceptQuery", "graphQuery", "selectedNoteId", "noteQuery"]) snapshot[key] = state[key];
      snapshot.selectedQuestion = state.selectedQuestion?.id || "";
      snapshot.selectedConcept = state.selectedConcept?.id || "";
      const encoded = JSON.stringify(snapshot);
      if (encoded === state.viewSnapshot) return;
      state.viewSnapshot = encoded;
      state.viewSaveQueue = state.viewSaveQueue.then(() => put("settings",{id:viewRecordId,...snapshot}))
        .catch(error => { state.viewSnapshot = ""; if (workspaceCurrent()) toast(storageError(error)); });
    };
    for (const type of ["input", "change", "click"]) document.addEventListener(type, () => queueMicrotask(checkpoint));
    document.addEventListener("toggle", () => requestAnimationFrame(checkpoint), true);
    window.addEventListener("pagehide", checkpoint);
    window.DMateI18n?.register?.({
      "基本定义":"Definition", "理解与说明":"Explanation", "典型例题":"Worked example", "常见错误":"Common mistakes",
      "评分要点":"Marking criteria", "细分概念":"Detailed concepts", "所属图谱知识点":"Knowledge-map topic",
      "所属知识点":"Parent knowledge point", "所属概念":"Related concepts", "所属总概念":"Parent concept", "总概念":"Overview concept",
      "所属图谱模块":"Knowledge-map module", "关联练习":"Related exercises", "暂无关联练习":"No related exercises yet",
      "概念列表":"Concept list", "练习列表":"Exercise list", "概念详情":"Concept details", "练习详情":"Exercise details",
      "关联知识点":"Related knowledge", "暂无已关联条目":"No linked entries yet", "数学符号":"Mathematical notation",
      ...questionTypeLabels, "简单":"Easy", "中等":"Medium", "困难":"Hard",
      "按章节筛选":"Filter by topic", "按难度筛选":"Filter by difficulty", "全部章节":"All topics", "全部难度":"All difficulties",
      "按题型筛选":"Filter by question type", "全部题型":"All question types", "按状态筛选":"Filter by status", "全部状态":"All statuses",
      "已选择":"Selected", "未选择":"Unselected", "全部":"All",
      "完整查看":"Full view", "完整查看概念详情":"View complete concept details", "完整查看练习详情":"View complete exercise details",
      "关闭详情":"Close details",
      "题目、答案与解析":"Questions, answers and explanations", "定义、解释与例题":"Definitions, explanations and examples",
      "定义、解释与易错点":"Definitions, explanations and common mistakes",
      "查看定义、解释、公式和易错点。":"View definitions, explanations, formulas and common mistakes.",
      "查看定义、解释、公式和易错点，支持中英文切换。":"View definitions, explanations, formulas and common mistakes in Chinese or English.",
      "搜索":"Search", "搜索概念":"Search concepts", "无":"None",
      "错题本":"Mistake book", "笔记本":"Notebook", "添加错题":"Add mistake", "编辑错题":"Edit mistake",
      "题目名称":"Question name", "题目内容":"Question content", "保存到本机":"Save on this device",
      "完成订正":"Mark corrected", "编辑/笔记":"Edit / notes", "移出错题本":"Remove from mistake book",
      "待订正":"Pending correction", "已完成订正":"Corrected", "加入错题本":"Add to mistake book",
      "查看答案":"View answer", "查看解析":"View explanation", "整题涉及":"Related content"
    });
    document.querySelectorAll(".offline-nav-item").forEach(item => item.addEventListener("click", () => {
      void Promise.resolve(switchPanel(item.dataset.panel)).catch(error => toast(storageError(error)));
    }));
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("questionType").addEventListener("change", event => { state.questionType=event.target.value; renderQuestions(); });
    $("questionSelection").addEventListener("change", event => { state.questionSelection=event.target.value; renderQuestions(); });
    $("questionSearch").addEventListener("input", renderQuestions);
    $("conceptCategory").addEventListener("change", event => { state.conceptCategory=event.target.value; renderConcepts(); });
    $("conceptSelection").addEventListener("change", event => { state.conceptSelection=event.target.value; renderConcepts(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    $("questionFullView").addEventListener("click", event => openLibraryDetail("questions", event.currentTarget));
    $("conceptFullView").addEventListener("click", event => openLibraryDetail("concepts", event.currentTarget));
    $("libraryDetailClose").addEventListener("click", () => closeLibraryDetail());
    $("libraryDetailDialog").addEventListener("cancel", event => { event.preventDefault(); closeLibraryDetail(); });
    $("libraryDetailDialog").addEventListener("close", () => {
      // A related link can close and reopen this dialog in one event. Its old
      // queued close event must not move the newly opened detail back inline.
      if (!$("libraryDetailDialog").open) closeLibraryDetail();
    });
    libraryMobile.addEventListener("change", event => {
      if (event.matches || !libraryDetail) return;
      const article = libraryDetail.article;
      closeLibraryDetail(false);
      article.focus({preventScroll:true});
    });
    window.addEventListener("online", setNetworkStatus);
    window.addEventListener("offline", setNetworkStatus);
    window.addEventListener("dmate:languagechange", event => {
      if (state.panel === "questions") renderQuestions();
      if (state.panel === "concepts") renderConcepts();
      if (state.panel === "mistakes") void renderMistakes();
      if (state.panel === "notes") void renderNotes();
      if (event.detail?.persist !== false) {
        void put("settings", {id:"language",value:event.detail.language,updatedAt:Date.now()})
          .catch(() => toast(tr("语言偏好暂时无法保存", "The language preference could not be saved.")));
      }
    });
    window.addEventListener("offline:appearance-change", event => {
      state.appearanceQueue = state.appearanceQueue.then(() => saveAppearance(event.detail))
        .catch(error => { window.DMateOfflineAppearance?.fail(new Error(storageError(error))); toast(storageError(error)); });
    });
  }

  async function init() {
    try {
      setNetworkStatus();
      const token = window.DMateOfflineHandoff?.pendingToken?.();
      state.storage = await window.DMateOfflineStorage.open({owner:workspaceOwner,isCurrent:workspaceCurrent,
        preserveSharedGuestSource:Boolean(token)});
      requireWorkspace();
      await migrateCurrentAccountData();
      await applyOriginalAppearance();
      const language = await transaction("settings", "readonly", os => os.get("language"));
      if (language?.value === "en" || language?.value === "zh-CN") window.DMateI18n?.setLanguage?.(language.value, false);
      configureRenderer();
      await loadResources();
      await loadLibrarySelections();
      bind();
      window.DMateI18n?.translate?.(document.body);
      const view = await transaction("settings","readonly",os => os.get(viewRecordId));
      if (view) {
        for (const key of ["graphCategory", "graphSelectedNodeId", "questionCategory", "questionDifficulty", "questionType", "questionSelection", "questionQuery", "conceptCategory", "conceptSelection", "conceptQuery", "graphQuery", "selectedNoteId", "noteQuery"])
          if (typeof view[key] === "string") state[key] = view[key];
        state.revealed = view.revealed === true;
        state.analysisRevealed = view.analysisRevealed === true;
        state.selectedQuestion = state.questions.find(item => item.id === view.selectedQuestion) || null;
        state.selectedConcept = state.concepts.find(item => item.id === view.selectedConcept) || null;
        $("questionSearch").value = state.questionQuery;
        $("conceptSearch").value = state.conceptQuery;
      }
      await switchPanel(view?.panel || "graph");
      document.documentElement.dataset.offlineReady = "true";
      $("offlineMain").inert = false;
      for (const button of startupControls) button.disabled = false;
    } catch (error) {
      toast(storageError(error));
    }
  }
  const startupControls = [...document.querySelectorAll(".offline-nav-item")];
  for (const button of startupControls) button.disabled = true;
  $("offlineMain").inert = true;
  $("returnOnline").addEventListener("click",() => { void returnOnline().catch(error => toast(storageError(error))); });
  init();
})();
