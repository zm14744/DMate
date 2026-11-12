"use strict";

/* DMate Offline uses only same-origin APIs served on 127.0.0.1.
 * No CDN, telemetry, online fallback or external AI endpoint.
 */
const $ = (id) => document.getElementById(id);
const ui = {
  token: "", sessions: [], items: [], models: [], session: null,
  panel: "chat", active: null, image: null, editing: null,
};
let toastTimer = null;

function toast(message) {
  const node = $("toast");
  node.textContent = String(message || "操作未完成");
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

async function request(path, method = "GET", body = null) {
  const headers = { "X-DMate-Local": ui.token };
  if (body !== null) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, headers, body: body === null ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function bootstrap() {
  const response = await fetch("/api/bootstrap", { cache: "no-store" });
  if (!response.ok) throw new Error("无法读取本机数据");
  const data = await response.json();
  ui.token = data.token;
  ui.sessions = data.sessions || [];
  ui.items = data.items || [];
  ui.models = data.models || [];
  const status = $("serviceStatus");
  status.className = "status " + (data.ollama_error ? "fail" : "ok");
  status.textContent = data.ollama_error || "本机模型可用";
  const select = $("modelSelect");
  select.replaceChildren();
  if (!ui.models.length) {
    const opt = new Option("尚未安装模型", "");
    opt.disabled = true;
    select.add(opt);
    select.value = "";
  } else {
    for (const name of ui.models) select.add(new Option(name, name));
    const saved = localStorage.getItem("dmate-offline-model");
    const preferred = [saved, "qwen3:4b-thinking-2507-q4_K_M", "qwen3:4b-thinking", "qwen3:4b", "qwen3-vl:4b"].find(n => ui.models.includes(n));
    select.value = preferred || ui.models[0];
  }
  renderSessions();
  renderItems();
}

function renderSessions() {
  const list = $("sessionList");
  list.replaceChildren();
  if (!ui.sessions.length) {
    list.append(element("small", "item-empty", "还没有对话"));
    return;
  }
  for (const session of ui.sessions) {
    const row = element("div", "session-row" + (ui.session === session.id ? " active" : ""));
    const open = element("button", "session-open", session.title);
    open.type = "button";
    open.title = session.title;
    open.addEventListener("click", () => openSession(session.id));
    const remove = element("button", "remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "删除对话：" + session.title);
    remove.addEventListener("click", () => deleteSession(session.id));
    row.append(open, remove);
    list.append(row);
  }
}

async function createSession(title = "新对话") {
  const result = await request("/api/sessions", "POST", { title });
  ui.sessions.unshift({ id: result.id, title: result.title });
  ui.session = result.id;
  renderSessions();
  $("messages").replaceChildren();
  switchPanel("chat");
  $("messageInput").focus();
  return result.id;
}

async function openSession(id) {
  if (ui.active) {
    toast("请先停止正在进行的回答");
    return;
  }
  ui.session = id;
  switchPanel("chat");
  renderSessions();
  try {
    const data = await request("/api/sessions/" + encodeURIComponent(id) + "/messages");
    const messages = $("messages");
    messages.replaceChildren();
    if (!data.messages.length) showEmpty();
    for (const m of data.messages) appendMessage(m.role, m.content, false);
    typesetMath(messages);
    scrollBottom();
  } catch (err) {
    toast(err.message);
  }
}

async function deleteSession(id) {
  if (ui.active) {
    toast("请先停止当前回答");
    return;
  }
  if (!confirm("删除这段对话及所有消息？此操作不可撤销。")) return;
  try {
    await request("/api/sessions/" + encodeURIComponent(id), "DELETE");
    ui.sessions = ui.sessions.filter(s => s.id !== id);
    if (ui.session === id) {
      ui.session = null;
      $("messages").replaceChildren();
      showEmpty();
    }
    renderSessions();
  } catch (err) {
    toast(err.message);
  }
}

function showEmpty() {
  const box = element("div", "empty-state");
  box.append(element("h2", "", "有什么可以一起研究的？"),
             element("p", "", "在本机探索离散数学、线性代数、程序设计，或者上传一道题的图片。"));
  $("messages").append(box);
}

function appendMessage(role, text, toBottom = true) {
  const empty = $("messages").querySelector(".empty-state");
  if (empty) empty.remove();
  const message = element("div", "message " + (role === "user" ? "user" : "assistant"));
  message.append(element("span", "role", role === "user" ? "你" : "DMate"));
  const bubble = element("div", "bubble", text);
  message.append(bubble);
  $("messages").append(message);
  if (toBottom) scrollBottom();
  return bubble;
}

function typesetMath(target) {
  if (window.MathJax && typeof window.MathJax.typesetPromise === "function") {
    window.MathJax.typesetPromise([target]).catch(() => {});
  }
}

function scrollBottom() {
  const list = $("messages");
  list.scrollTop = list.scrollHeight;
}

function switchPanel(name) {
  ui.panel = name;
  document.querySelectorAll(".nav-button").forEach(button => {
    button.classList.toggle("active", button.dataset.panel === name);
  });
  $("chatPanel").hidden = name !== "chat";
  $("itemsPanel").hidden = name !== "note" && name !== "mistake";
  $("graphPanel").hidden = name !== "graph";
  const meta = {
    chat: ["学习对话", "本机模型运行，不调用云端 AI 服务。"],
    note: ["概念笔记", "记录知识点、证明思路与学习心得，保存在这台电脑。"],
    mistake: ["错题本", "保留题目、错误原因和重新练习的进度。"],
    graph: ["图论工具", "本地确定性计算，不依赖 AI 和网络。"],
  }[name];
  $("panelTitle").textContent = meta[0];
  $("panelSubtitle").textContent = meta[1];
  if (name === "note" || name === "mistake") {
    $("itemsDescription").textContent = name === "note"
      ? "整理知识点、证明和概念。" : "积累错题，复习后可标记为已掌握。";
    renderItems();
  }
}

function renderItems() {
  const list = $("itemList");
  list.replaceChildren();
  const items = ui.items.filter(item => item.kind === ui.panel);
  if (!items.length) {
    list.append(element("p", "item-empty", "还没有记录，点击「新建」添加第一条。"));
    return;
  }
  for (const item of items) {
    const card = element("article", "item-card");
    card.append(element("h3", "", item.title), element("p", "", item.content));
    card.append(element("div", "item-meta",
      (item.kind === "mistake" ? (item.status === "resolved" ? "已掌握 · " : "待复习 · ") : "")
      + item.updated_at.replace("T", " ").slice(0, 16) + " UTC"));
    const actions = element("div", "item-actions");
    const edit = element("button", "", "编辑");
    edit.addEventListener("click", () => editItem(item));
    const remove = element("button", "", "删除");
    remove.addEventListener("click", () => removeItem(item.id));
    actions.append(edit, remove);
    card.append(actions);
    list.append(card);
  }
}

function editItem(item = null) {
  ui.editing = item ? item.id : null;
  $("itemDialogTitle").textContent = item ? "编辑记录" : "新增记录";
  $("itemTitle").value = item?.title || "";
  $("itemContent").value = item?.content || "";
  $("itemStatus").value = item?.status || "open";
  $("itemStatusLabel").hidden = ui.panel !== "mistake";
  $("itemDialog").showModal();
  $("itemTitle").focus();
}

async function saveItem(event) {
  event.preventDefault();
  const body = {
    title: $("itemTitle").value.trim(),
    content: $("itemContent").value.trim(),
    status: $("itemStatus").value,
  };
  try {
    if (ui.editing) {
      const item = ui.items.find(i => i.id === ui.editing);
      await request("/api/items/" + ui.editing, "PATCH", body);
      Object.assign(item, body, { updated_at: new Date().toISOString() });
    } else {
      body.kind = ui.panel;
      const result = await request("/api/items", "POST", body);
      ui.items.unshift({ ...body, id: result.id, updated_at: new Date().toISOString() });
    }
    $("itemDialog").close();
    renderItems();
  } catch (err) {
    toast(err.message);
  }
}

async function removeItem(id) {
  if (!confirm("确定删除这条记录吗？")) return;
  try {
    await request("/api/items/" + id, "DELETE");
    ui.items = ui.items.filter(item => item.id !== id);
    renderItems();
  } catch (err) {
    toast(err.message);
  }
}

function renderGraph(result) {
  const output = $("graphOutput");
  output.replaceChildren();
  const type = result.directed ? "有向图" : "无向图";
  output.append(element("p", "", type + " · " + result.vertices.length + " 个顶点 · " + result.edges.length + " 条边"));
  output.append(element("p", "", "度：" + Object.entries(result.degree)
    .map(([v, d]) => v + "=" + (typeof d === "number" ? d : "出" + d.out + "/入" + d.in)).join("，")));
  output.append(element("p", "", "广度优先遍历：" + (result.bfs.join(" → ") || "空")));
  output.append(element("p", "", (result.directed ? "弱连通分量：" : "连通分量：")
    + result.components.map(g => "{" + g.join(", ") + "}").join("，")));
  if (!result.directed) output.append(element("p", "", "是否为树：" + (result.is_tree ? "是" : "否")));
  const heading = element("h3", "", "邻接矩阵（按顶点输入顺序）");
  heading.style.fontSize = "14px";
  heading.style.fontWeight = "550";
  output.append(heading);
  const widths = Math.max(3, ...result.vertices.map(v => v.length)) + 1;
  const pad = text => String(text).padStart(widths, " ");
  const header = pad("") + result.vertices.map(pad).join("");
  const rows = result.adjacency_matrix.map((line, i) =>
    pad(result.vertices[i]) + line.map(pad).join(""));
  output.append(element("pre", "", [header, ...rows].join("\n")));
}

async function analyzeGraph(event) {
  event.preventDefault();
  try {
    const result = await request("/api/graph", "POST", {
      vertices: $("graphVertices").value, edges: $("graphEdges").value,
      start: $("graphStart").value.trim(), directed: $("graphDirected").checked,
    });
    renderGraph(result);
  } catch (err) {
    toast(err.message);
  }
}

function resetImage() {
  ui.image = null;
  $("imageInput").value = "";
  $("imageChip").hidden = true;
  $("imagePreview").removeAttribute("src");
}

async function attachImage(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 6 * 1024 * 1024) {
    resetImage();
    toast("只支持最大 6 MiB 的 PNG、JPEG 或 WebP 图片");
    return;
  }
  try {
    const encoded = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("图片读取失败"));
      reader.readAsDataURL(file);
    });
    ui.image = encoded;
    const vision = ui.models.find(name => name.startsWith("qwen3-vl:"));
    if (vision && !$("modelSelect").value.includes("vl")) {
      $("modelSelect").value = vision;
      toast("已切换为本机视觉模型，以便识别图片");
    }
    $("imagePreview").src = encoded;
    $("imageName").textContent = file.name;
    $("imageChip").hidden = false;
  } catch (err) {
    resetImage();
    toast(err.message);
  }
}

function setSending(sending) {
  $("sendButton").hidden = sending;
  $("stopButton").hidden = !sending;
  $("messageInput").disabled = sending;
  $("modelSelect").disabled = sending;
}

async function sendChat(event) {
  event.preventDefault();
  if (ui.active) return;
  const message = $("messageInput").value.trim();
  const model = $("modelSelect").value;
  if (!message) return;
  if (!model) return toast("请先安装并启动本地模型，例如：ollama pull qwen3:4b");
  let bubble = null;
  let streamCompleted = false;
  const controller = new AbortController();
  ui.active = controller;
  setSending(true);
  try {
    if (!ui.session) await createSession(message.slice(0, 35));
    const image = ui.image;
    appendMessage("user", message + (image ? "\n[已附带图片]" : ""));
    bubble = appendMessage("assistant", "");
    $("messageInput").value = "";
    resetImage();
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-DMate-Local": ui.token },
      body: JSON.stringify({ session_id: ui.session, message, model, image }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.error || "本地模型无法完成请求");
    }
    if (!response.body) throw new Error("当前环境不支持流式输出");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const parseLine = line => {
      if (!line.trim()) return;
      const packet = JSON.parse(line);
      if (packet.type === "delta") {
        bubble.textContent += packet.text || "";
        scrollBottom();
      } else if (packet.type === "done") {
        streamCompleted = true;
      } else if (packet.type === "error") {
        throw new Error(packet.message || "模型推理中断");
      }
    };
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        parseLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (done) {
        if (buffer.trim()) parseLine(buffer);
        break;
      }
    }
    if (!streamCompleted) throw new Error("连接中断，未获得完整回答");
    typesetMath(bubble);
  } catch (err) {
    if (bubble && !bubble.textContent.trim()) bubble.textContent = "未生成完整回答。";
    toast(controller.signal.aborted ? "已停止生成" : err.message);
  } finally {
    ui.active = null;
    setSending(false);
    $("messageInput").focus();
  }
}

async function exportBackup() {
  try {
    const response = await fetch("/api/export", {
      headers: { "X-DMate-Local": ui.token }, cache: "no-store",
    });
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = "dmate-offline-backup.json";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toast(err.message); }
}

async function importBackup(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (ui.active) return toast("请先停止当前回答");
  if (file.size > 8 * 1024 * 1024) return toast("备份文件不能超过 8 MiB");
  if (!confirm("导入将覆盖这台电脑中全部离线对话、笔记和错题。确定继续？")) return;
  try {
    const backup = JSON.parse(await file.text());
    await request("/api/import", "POST", { confirm_replace: true, backup });
    ui.session = null;
    $("messages").replaceChildren();
    showEmpty();
    await bootstrap();
    toast("数据导入完成");
  } catch (err) { toast(err.message); }
}

function bindEvents() {
  document.querySelectorAll(".nav-button").forEach(button => {
    button.addEventListener("click", () => switchPanel(button.dataset.panel));
  });
  $("newSession").addEventListener("click", () => createSession().catch(err => toast(err.message)));
  $("chatForm").addEventListener("submit", sendChat);
  $("stopButton").addEventListener("click", () => ui.active?.abort());
  $("messageInput").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("chatForm").requestSubmit();
    }
  });
  $("modelSelect").addEventListener("change", event =>
    localStorage.setItem("dmate-offline-model", event.target.value));
  $("refreshModels").addEventListener("click", () => bootstrap().catch(err => toast(err.message)));
  $("imageInput").addEventListener("change", attachImage);
  $("clearImage").addEventListener("click", resetImage);
  $("addItem").addEventListener("click", () => editItem());
  $("cancelItem").addEventListener("click", () => $("itemDialog").close());
  $("itemForm").addEventListener("submit", saveItem);
  $("graphForm").addEventListener("submit", analyzeGraph);
  $("exportBackup").addEventListener("click", exportBackup);
  $("importBackup").addEventListener("click", () => $("importFile").click());
  $("importFile").addEventListener("change", importBackup);
}

bindEvents();
showEmpty();
bootstrap().then(() => {
  if (ui.sessions.length) openSession(ui.sessions[0].id);
}).catch(err => toast(err.message));
