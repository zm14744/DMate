(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const DB_NAME = "dmate-offline-workspace";
  const DB_VERSION = 2;
  const state = {
    db: null, concepts: [], questions: [], graph: null, translations: {concepts:{},questions:{}},
    panel: "graph", selectedQuestion: null, selectedConcept: null,
    revealed: false,
    drawingController: null, backgroundUrl: "", graphCategory: "", graphSelectedNodeId: "", questionCategory: "",
    questionDifficulty: "", questionQuery: "", conceptCategory: "", conceptQuery: "", graphQuery: "", graphController: null,
    appearanceQueue: Promise.resolve()
  };
  const panelMeta = {
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
    const [concepts, questions, graph, translations] = await Promise.all([
      fetch("/static/offline-content/concepts.zh-CN.json?v=28", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("概念库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/questions.zh-CN.json?v=28", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("题库资源不可用"); return r.json(); }),
      fetch("/static/offline-content/knowledge_graph.json?v=28", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("知识图谱资源不可用"); return r.json(); }),
      fetch("/static/offline-content/translations.en.json?v=28", {cache:"no-store"}).then(r => { if(!r.ok) throw Error("英文学习内容资源不可用"); return r.json(); })
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

  function switchPanel(name) {
    if (!panelMeta[name]) return;
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
    if (name === "drawing") mountDrawing();
    if (name === "graph") renderGraph();
    if (name === "questions") renderQuestions();
    if (name === "concepts") renderConcepts();
    window.dispatchEvent(new CustomEvent("dmate:offlinepanelchange", {detail:{panel:name,title:panelMeta[name][0]}}));
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
    switchPanel("concepts");
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

  function searchText(value) {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(searchText).join(" ");
    if (typeof value === "object") return Object.values(value).map(searchText).join(" ");
    return ["string", "number", "boolean"].includes(typeof value) ? String(value) : "";
  }

  function normalizedSearch(value) {
    return String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase();
  }

  function questionMatchesSearch(question, query) {
    if (!query) return true;
    const translated = state.translations.questions[question.id] || {};
    const fields = ["id", "title", "statement", "options", "answer", "answer_text", "explanation", "grading_criteria", "category", "difficulty", "type", "knowledge_points"];
    const searchable = [fields.map(key => question[key]), fields.map(key => translated[key]),
      window.DMateKnowledgeLanguage?.labels?.[question.category],
      difficultyName(question.difficulty), window.DMateLanguageCatalog?.exact?.[difficultyName(question.difficulty)],
      questionTypeLabels[question.type], tr(question.category), tr(question.type)];
    return normalizedSearch(searchText(searchable)).includes(query);
  }

  function renderQuestions() {
    fillQuestionFilters();
    state.questionQuery = $("questionSearch").value;
    window.DMateSearchControls?.refresh?.($("questionSearch"));
    const query = normalizedSearch(state.questionQuery);
    const filtered = state.questions.filter(q =>
      (!state.questionCategory || q.category === state.questionCategory) &&
      (!state.questionDifficulty || difficultyName(q.difficulty) === state.questionDifficulty) &&
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
      list.append(item);
    }
    if (state.selectedQuestion && filtered.some(q => q.id === state.selectedQuestion.id)) {
      renderQuestionDetail(state.selectedQuestion);
    } else if (filtered.length) selectQuestion(filtered[0]);
    else {
      state.selectedQuestion = null;
      state.revealed = false;
      $("questionDetail").replaceChildren(el("div","offline-empty",tr("没有符合条件的题目。", "No matching exercises.")));
    }
  }

  function selectQuestion(question) {
    state.selectedQuestion = question;
    state.revealed = false;
    document.querySelectorAll(".question-item").forEach(node => {
      const selected = node.dataset.questionId === question.id;
      node.classList.toggle("active", selected); node.setAttribute("aria-current", String(selected));
    });
    renderQuestionDetail(question);
  }

  function renderQuestionDetail(question) {
    const detail = $("questionDetail"), display = localized(question, "questions");
    detail.setAttribute("data-i18n-content", "");
    detail.replaceChildren();
    detail.append(el("div", "detail-kicker", [tr(question.category), tr(difficultyName(question.difficulty)), tr(question.type)].filter(Boolean).join(" ")));
    detail.append(studyLabel("h2", "detail-title", display.title));
    const concepts = el("div", "prereq-list question-concept-links");
    for (const id of question.knowledge_points || []) {
      const concept = state.concepts.find(item => item.id === id);
      if (concept) {
        const link = studyButton(tr("知识点：", "Knowledge point: ") + localized(concept, "concepts").title, "", () => {
          openConcept(concept);
        });
        link.dataset.conceptId = id; concepts.append(link);
      }
    }
    if (concepts.children.length) detail.append(concepts);
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

    const actions = el("div", "question-actions wrong-actions");
    actions.append(action(state.revealed ? tr("收起参考答案", "Hide reference answer") : tr("查看参考答案", "View reference answer"), "offline-primary", () => {
      state.revealed = !state.revealed;
      renderQuestionDetail(question);
    }));
    detail.append(actions);

    if (state.revealed) {
      const answer = el("section", "answer-panel wrong-answer-details");
      answer.append(el("h3", "", tr("参考答案", "Reference answer")));
      answer.append(rich("wrong-answer-inner", display.answer_text || (question.answer || []).join("、")));
      answer.append(el("h3", "", tr("解析", "Explanation")));
      answer.append(rich("wrong-analysis-body", display.explanation || tr("暂无解析。", "No explanation available.")));
      if (question.grading_criteria) {
        answer.append(el("h3", "", tr("评分要点", "Marking criteria")), rich("wrong-feedback-body", display.grading_criteria));
      }
      detail.append(answer);
    }
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
      section.append(el("h3", "", children.length ? tr("细分概念", "Detailed concepts") : tr("所属知识点", "Parent knowledge point")));
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
      const module = el("section", "detail-section concept-graph-module");
      module.append(el("h3", "", tr("所属图谱模块", "Knowledge-map module")));
      const links = el("div", "prereq-list");
      const label = window.DMateKnowledgeLanguage?.label?.(graphNode.name) ?? tr(graphNode.name);
      const link = studyButton(label, "concept-graph-module-link", () => openGraphModule(graphNode));
      link.dataset.graphNodeId = graphNode.id;
      link.dataset.graphCategory = graphNode.category;
      links.append(link); module.append(links); detail.append(module);
    }
    document.querySelectorAll(".concept-item").forEach(item => {
      const selected = item.dataset.conceptId === concept.id;
      item.classList.toggle("active", selected); item.setAttribute("aria-current", String(selected));
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
    const related = el("section", "detail-section concept-related-exercises");
    related.append(el("h3", "", tr("关联练习", "Related exercises")));
    const prereqs = el("div", "prereq-list");
    const seen = new Set(), ranks = {"简单":0, "中等":1, "困难":2};
    const exercises = (concept.related_questions || []).map((id, index) => ({question:state.questions.find(q => q.id === id), index}))
      .filter(({question}) => {
        if (!question || seen.has(question.id)) return false;
        seen.add(question.id); return true;
      })
      .sort((left, right) => (ranks[difficultyName(left.question.difficulty)] ?? 3) - (ranks[difficultyName(right.question.difficulty)] ?? 3)
        || left.index - right.index);
    for (const {question:q} of exercises) {
        const level = difficultyName(q.difficulty);
        const link = studyButton([tr(level), localized(q, "questions").title].filter(Boolean).join(" "), "", () => {
          state.questionCategory = ""; state.questionDifficulty = "";
          $("questionCategory").value = ""; $("questionDifficulty").value = "";
          if (!questionMatchesSearch(q, normalizedSearch($("questionSearch").value))) $("questionSearch").value = "";
          state.selectedQuestion = q;
          state.revealed = false;
          switchPanel("questions");
        });
        link.dataset.questionId = q.id;
        link.dataset.difficulty = level;
        prereqs.append(link);
    }
    if (!prereqs.children.length) prereqs.append(el("span", "", tr("暂无关联练习", "No related exercises yet")));
    related.append(prereqs); detail.append(related);
  }

  function renderConcepts() {
    state.conceptCategory = fillChapterFilter($("conceptCategory"), state.conceptCategory);
    const query = $("conceptSearch").value.trim().toLocaleLowerCase();
    state.conceptQuery = $("conceptSearch").value;
    window.DMateSearchControls?.refresh?.($("conceptSearch"));
    const rows = state.concepts.filter(c => {
      const translated = state.translations.concepts[c.id] || {};
      return (!state.conceptCategory || c.category === state.conceptCategory)
        && (!query || [c.title,c.category,c.summary,c.definition,translated.title,translated.summary,translated.definition,tr(c.category)].join(" ").toLocaleLowerCase().includes(query));
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
      list.append(item);
    }
    if (state.selectedConcept && rows.some(c => c.id === state.selectedConcept.id)) fillConceptDetail(state.selectedConcept);
    else if (rows.length) fillConceptDetail(rows[0]);
    else {
      state.selectedConcept = null;
      $("conceptDetail").replaceChildren(el("div","offline-empty",tr("没有找到匹配的概念。", "No matching concepts.")));
    }
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
      onSelect(node) {
      const concept = state.concepts.find(c => c.id === node.id || c.title === node.name);
      if (concept) {
        openConcept(concept);
      } else toast("该知识点尚无独立概念条目");
      }
    });
  }

  function mountDrawing() {
    if (state.drawingController) {
      state.drawingController.fitView?.();
      return;
    }
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
        features: {ai:false, upload:false},
        legacyDocument: {body_text:"",graphs:[{id:"G1",name:"我的图形",directed:false,weighted:false,vertices:[],edges:[]}]},
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
    window.DMateI18n?.register?.({
      "基本定义":"Definition", "理解与说明":"Explanation", "典型例题":"Worked example", "常见错误":"Common mistakes",
      "评分要点":"Marking criteria", "细分概念":"Detailed concepts", "所属图谱知识点":"Knowledge-map topic",
      "所属知识点":"Parent knowledge point", "所属图谱模块":"Knowledge-map module", "关联练习":"Related exercises", "暂无关联练习":"No related exercises yet",
      "概念列表":"Concept list", "练习列表":"Exercise list", "概念详情":"Concept details", "练习详情":"Exercise details",
      "关联知识点":"Related knowledge", "暂无已关联条目":"No linked entries yet", "数学符号":"Mathematical notation",
      ...questionTypeLabels, "简单":"Easy", "中等":"Medium", "困难":"Hard",
      "按章节筛选":"Filter by topic", "按难度筛选":"Filter by difficulty", "全部章节":"All topics", "全部难度":"All difficulties",
      "题目、答案与解析":"Questions, answers and explanations", "定义、解释与例题":"Definitions, explanations and examples",
      "定义、解释与易错点":"Definitions, explanations and common mistakes",
      "查看定义、解释、公式和易错点。":"View definitions, explanations, formulas and common mistakes.",
      "查看定义、解释、公式和易错点，支持中英文切换。":"View definitions, explanations, formulas and common mistakes in Chinese or English.",
      "搜索":"Search", "搜索概念":"Search concepts", "没有符合条件的题目。":"No matching exercises.", "没有找到匹配的概念。":"No matching concepts."
    });
    document.querySelectorAll(".offline-nav-item").forEach(item => item.addEventListener("click", () => switchPanel(item.dataset.panel)));
    $("questionCategory").addEventListener("change", event => { state.questionCategory=event.target.value; renderQuestions(); });
    $("questionDifficulty").addEventListener("change", event => { state.questionDifficulty=event.target.value; renderQuestions(); });
    $("questionSearch").addEventListener("input", renderQuestions);
    $("conceptCategory").addEventListener("change", event => { state.conceptCategory=event.target.value; renderConcepts(); });
    $("conceptSearch").addEventListener("input", renderConcepts);
    $("returnOnline").addEventListener("click", returnOnline);
    window.addEventListener("online", setNetworkStatus);
    window.addEventListener("offline", setNetworkStatus);
    window.addEventListener("dmate:languagechange", event => {
      if (state.panel === "questions") renderQuestions();
      if (state.panel === "concepts") renderConcepts();
      if (event.detail?.persist !== false) {
        void put("settings", {id:"language",value:event.detail.language,updatedAt:Date.now()})
          .catch(() => toast(tr("语言偏好暂时无法保存", "The language preference could not be saved.")));
      }
    });
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
      const language = await transaction("settings", "readonly", os => os.get("language"));
      if (language?.value === "en" || language?.value === "zh-CN") window.DMateI18n?.setLanguage?.(language.value, false);
      configureRenderer();
      await migrateCurrentAccountData();
      await loadResources();
      bind();
      window.DMateI18n?.translate?.(document.body);
      await switchPanel("graph");
      document.documentElement.dataset.offlineReady = "true";
    } catch (error) {
      toast(error?.message || "离线工作区初始化失败");
    }
  }
  init();
})();
