(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DB_NAME = "dmate-offline-workspace";
  const DB_VERSION = 1;
  const state = {
    db: null, concepts: [], questions: [], graph: null,
    panel: "mistakes", selectedQuestion: null, selectedConcept: null,
    selectedOption: [], revealed: false, recordKind: "note", editingId: null,
    drawingController: null, graphCategory: "", questionCategory: "",
    questionDifficulty: "", conceptQuery: "", graphQuery: ""
  };
  const panelMeta = {
    mistakes: ["错题本", "在本机查看、整理和复习已保存的错题。"],
    notes: ["概念笔记", "把自己的理解、推导和学习记录保存在本机。"],
    drawing: ["独立绘图", "使用 DMate 图形编辑器，在本机创建和保存数学图形。"],
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
    node.addEventListener("click", handler);
    return node;
  }
  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        for (const store of ["mistakes", "notes", "practice"]) {
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
  const stamp = () => new Date().toISOString();
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : "local-" + Date.now() + "-" + Math.random().toString(36).slice(2));

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
    document.querySelectorAll(".offline-nav-item").forEach(item => item.classList.toggle("active", item.dataset.panel === name));
    for (const key of Object.keys(panelMeta)) {
      const node = $(key + "Panel");
      if (node) node.hidden = key !== name;
    }
    $("panelTitle").textContent = panelMeta[name][0];
    $("panelDescription").textContent = panelMeta[name][1];
    if (name === "mistakes") renderMistakes();
    if (name === "notes") renderNotes();
    if (name === "drawing") mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
  }

  async function renderMistakes() {
    const rows = (await all("mistakes")).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt));
    $("mistakeCount").textContent = rows.length + " 道错题";
    const list = $("mistakeList");
    list.replaceChildren();
    if (!rows.length) {
      const empty = el("div", "offline-empty");
      empty.append(el("h2", "", "还没有错题"), el("p", "", "可以从题库中把做错的题目加入错题本，也可以手动添加。"));
      list.append(empty);
      return;
    }
    for (const row of rows) {
      const card = el("article", "offline-record");
      card.append(el("h3", "", row.title), el("p", "", row.statement || row.content || ""));
      const meta = el("div", "record-meta");
      meta.append(el("span", "", (row.status === "resolved" ? "已掌握" : "待复习") + " · " + new Date(row.updatedAt).toLocaleString()));
      const actions = el("div", "record-actions");
      if (row.status !== "resolved") actions.append(button("标记已掌握", "", async () => {
        await put("mistakes", {...row, status:"resolved", updatedAt:stamp()}); renderMistakes();
      }));
      actions.append(button("查看答案", "", () => showMistakeAnswer(row)));
      actions.append(button("删除", "danger", async () => {
        if (confirm("确定删除这道错题吗？")) { await remove("mistakes", row.id); renderMistakes(); }
      }));
      meta.append(actions); card.append(meta); list.append(card);
    }
  }

  function showMistakeAnswer(row) {
    const detail = el("div", "offline-record");
    detail.append(el("h3", "", "参考答案"), el("p", "", row.answer || "这条记录没有保存参考答案。"));
    if (row.explanation) detail.append(el("h3", "", "解析"), el("p", "", row.explanation));
    const old = $("mistakeList").querySelector(".mistake-answer-view");
    old?.remove();
    detail.classList.add("mistake-answer-view");
    $("mistakeList").prepend(detail);
  }

  async function renderNotes() {
    const rows = (await all("notes")).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt));
    $("noteCount").textContent = rows.length + " 条笔记";
    const list = $("noteList");
    list.replaceChildren();
    if (!rows.length) {
      const empty = el("div", "offline-empty");
      empty.append(el("h2", "", "还没有笔记"), el("p", "", "把自己的理解、推导过程和易错点记录下来。"));
      list.append(empty); return;
    }
    for (const row of rows) {
      const card = el("article", "offline-card");
      card.append(el("h3", "", row.title), el("p", "", row.content));
      card.append(el("div", "card-meta", "本机保存 · " + new Date(row.updatedAt).toLocaleString()));
      const actions = el("div", "record-actions");
      actions.style.marginTop = "13px";
      actions.append(button("编辑", "", () => openRecord("notes", row)));
      actions.append(button("删除", "danger", async () => {
        if (confirm("确定删除这条笔记吗？")) { await remove("notes", row.id); renderNotes(); }
      }));
      card.append(actions); list.append(card);
    }
  }

  function openRecord(kind, row = null) {
    state.recordKind = kind;
    state.editingId = row?.id || null;
    $("recordDialogTitle").textContent = row ? (kind === "notes" ? "编辑笔记" : "编辑错题") : (kind === "notes" ? "新建笔记" : "添加错题");
    $("recordTitle").value = row?.title || "";
    $("recordContent").value = row?.content || row?.statement || "";
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
    document.querySelectorAll(".question-item").forEach(node => node.classList.toggle("active", node.querySelector("strong")?.textContent === question.title));
    renderQuestionDetail(question);
  }

  function renderQuestionDetail(question) {
    const detail = $("questionDetail");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", question.category + " / " + question.difficulty + " / " + question.type));
    detail.append(el("h2", "detail-title", question.title));
    const statement = el("div", "detail-section");
    statement.append(el("h3", "", "题目"));
    statement.append(el("p", "", question.statement));
    detail.append(statement);

    if (Array.isArray(question.options) && question.options.length) {
      const options = el("div", "detail-section");
      options.append(el("h3", "", question.type === "多项选择" ? "选择所有正确选项" : "选择一个答案"));
      for (const option of question.options) {
        const node = button(option.key + ". " + option.text,
          "question-option" + (state.selectedOption.includes(option.key) ? " selected" : ""),
          () => {
            if (question.type === "多项选择") {
              state.selectedOption = state.selectedOption.includes(option.key)
                ? state.selectedOption.filter(x => x !== option.key) : [...state.selectedOption, option.key];
            } else state.selectedOption = [option.key];
            renderQuestionDetail(question);
          });
        options.append(node);
      }
      detail.append(options);
    } else {
      const response = el("div", "detail-section");
      response.append(el("h3", "", "你的作答"));
      const textarea = el("textarea", "");
      textarea.id = "questionResponse";
      textarea.placeholder = question.type === "证明" ? "在这里写出完整证明过程…" : "在这里填写你的答案…";
      response.append(textarea); detail.append(response);
    }

    const actions = el("div", "question-actions");
    actions.append(button("记录本次练习", "offline-quiet-button", async () => {
      const response = $("questionResponse")?.value || "";
      await put("practice", {id:uid(), questionId:question.id, response, selected:state.selectedOption, createdAt:stamp()});
      toast("练习记录已保存在本机");
    }));
    actions.append(button("查看参考答案", "offline-primary", () => {
      state.revealed = !state.revealed;
      renderQuestionDetail(question);
    }));
    actions.append(button("加入错题本", "offline-quiet-button", () => addQuestionMistake(question)));
    detail.append(actions);

    if (state.revealed) {
      const answer = el("section", "answer-panel");
      answer.append(el("h3", "", "参考答案"));
      answer.append(el("p", "", question.answer_text || (question.answer || []).join("、")));
      answer.append(el("h3", "", "解析"));
      answer.append(el("p", "", question.explanation || "暂无解析。"));
      if (question.grading_criteria) {
        answer.append(el("h3", "", "评分要点"), el("p", "", question.grading_criteria));
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
    detail.append(el("p", "concept-summary", concept.summary));
    const section = (title, content) => {
      const box = el("section", "detail-section");
      box.append(el("h3", "", title));
      if (Array.isArray(content)) {
        const ul = el("ul", "");
        for (const item of content) ul.append(el("li", "", item));
        box.append(ul);
      } else box.append(el("p", "", content || "暂无内容。"));
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
        switchPanel("questions"); state.questionCategory = ""; $("questionCategory").value = ""; selectQuestion(q);
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
        document.querySelectorAll(".concept-item").forEach(n => n.classList.toggle("active", n.querySelector("strong")?.textContent === concept.title));
      });
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
    const host = $("graphNodes"); host.replaceChildren();
    for (const node of nodes) {
      const card = button("", "offline-card", () => {
        const concept = state.concepts.find(c => c.id === node.id);
        if (concept) { switchPanel("concepts"); fillConceptDetail(concept); }
        else toast("该知识点尚无独立概念条目");
      });
      card.append(el("h3", "", node.name), el("p", "", node.category));
      const names = (node.prerequisites || []).map(id => state.graph.nodes.find(x => x.name === id)?.name || id);
      card.append(el("div", "card-meta", names.length ? "建议前置：" + names.join("、") : "基础知识点"));
      host.append(card);
    }
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

  function bind() {
    document.querySelectorAll(".offline-nav-item").forEach(item => item.addEventListener("click", () => switchPanel(item.dataset.panel)));
    $("addMistake").addEventListener("click", () => openRecord("mistakes"));
    $("addNote").addEventListener("click", () => openRecord("notes"));
    $("recordForm").addEventListener("submit", saveRecord);
    $("cancelRecord").addEventListener("click", () => $("recordDialog").close());
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    $("graphSearch").addEventListener("input", renderGraph);
    $("exportLocalData").addEventListener("click", () => exportData().catch(error => toast(error.message)));
    $("returnOnline").addEventListener("click", returnOnline);
    window.addEventListener("online", setNetworkStatus);
    window.addEventListener("offline", setNetworkStatus);
  }

  async function init() {
    try {
      setNetworkStatus();
      state.db = await openDb();
      await loadResources();
      bind();
      renderMistakes();
      $("saveState").textContent = "本地保存已启用";
      switchPanel("mistakes");
    } catch (error) {
      $("saveState").textContent = "初始化失败";
      toast(error?.message || "离线工作区初始化失败");
    }
  }
  init();
})();