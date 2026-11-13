(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DB_NAME = "dmate-offline-workspace";
  const DB_VERSION = 2;
  const state = {
    db: null, concepts: [], questions: [], graph: null,
    panel: "drawing", selectedQuestion: null, selectedConcept: null,
    selectedOption: [], revealed: false,
    drawingController: null, backgroundUrl: "", graphCategory: "", questionCategory: "",
    questionDifficulty: "", conceptQuery: "", graphQuery: "", graphController: null,
    questionResponses: new Map(), appearanceQueue: Promise.resolve()
  };
  const panelMeta = {
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
  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        for (const store of ["practice", "settings"]) {
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
  const put = (store, value) => transaction(store, "readwrite", os => os.put(value));
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
    toast("已导入当前账号的绘图到本机离线区");
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
    if (name === "drawing") mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
    window.dispatchEvent(new CustomEvent("dmate:offlinepanelchange", {detail:{panel:name,title:panelMeta[name][0]}}));
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
    const concepts = el("div", "prereq-list question-concept-links");
    for (const id of question.knowledge_points || []) {
      const concept = state.concepts.find(item => item.id === id);
      if (concept) {
        const link = button("知识点：" + concept.title, "", () => {
          $("conceptSearch").value = "";
          switchPanel("concepts"); fillConceptDetail(concept);
        });
        link.dataset.conceptId = id; concepts.append(link);
      }
    }
    if (concepts.children.length) detail.append(concepts);
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
    const topic = state.concepts.find(item => item.id === concept.graph_node_id);
    const children = (concept.related_concepts || []).map(id => state.concepts.find(item => item.id === id)).filter(Boolean);
    if (children.length || (topic && topic.id !== concept.id)) {
      const section = el("section", "detail-section concept-topic-links");
      section.append(el("h3", "", children.length ? "细分概念" : "所属图谱知识点"));
      const links = el("div", "prereq-list");
      for (const item of children.length ? children : [topic]) {
        const link = button(item.title, "", () => fillConceptDetail(item));
        link.dataset.conceptId = item.id;
        links.append(link);
      }
      section.append(links); detail.append(section);
    }
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
      if (q) {
        const link = button("练习：" + q.title, "", () => {
          state.questionCategory = ""; state.questionDifficulty = "";
          $("questionCategory").value = ""; $("questionDifficulty").value = "";
          switchPanel("questions"); selectQuestion(q);
        });
        link.dataset.questionId = id; prereqs.append(link);
      }
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
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    $("graphSearch").addEventListener("input", renderGraph);
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
      await applyOriginalAppearance();
      configureRenderer();
      await migrateCurrentAccountData();
      await loadResources();
      bind();
      await switchPanel("drawing");
      document.documentElement.dataset.offlineReady = "true";
    } catch (error) {
      toast(error?.message || "离线工作区初始化失败");
    }
  }
  init();
})();
