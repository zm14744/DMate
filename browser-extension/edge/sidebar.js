(() => {
  "use strict";

  const API_BASE = "https://dmate.zeabur.app";
  const STORAGE_KEY = "dmate_edge_sidepanel_messages_v1";
  const chat = document.getElementById("chat");
  const form = document.getElementById("composer");
  const prompt = document.getElementById("prompt");
  const sendButton = document.getElementById("send");
  const menu = document.getElementById("menu");
  const menuButton = document.getElementById("menuButton");
  const questionMode = () => document.querySelector('input[name="questionMode"]:checked')?.value === "yes";

  let messages = [];
  let busy = false;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }

  function formatMessage(value) {
    // A small, deliberately limited Markdown renderer. All source text is
    // escaped before formatting so model output is never interpreted as HTML.
    let source = escapeHtml(value || "");
    source = source.replace(/```([\s\S]*?)```/g, (_, code) => (
      '<pre><code>' + code.replace(/^\n|\n$/g, "") + '</code></pre>'
    ));
    source = source.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    source = source.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    source = source.replace(/^### (.+)$/gm, "<strong>$1</strong>");
    return source.split(/\n{2,}/).map((paragraph) => {
      if (paragraph.startsWith("<pre>")) return paragraph;
      return "<p>" + paragraph.replace(/\n/g, "<br>") + "</p>";
    }).join("");
  }

  function render() {
    chat.replaceChildren();
    for (const message of messages) {
      const item = document.createElement("article");
      item.className = "message " + (message.role === "user" ? "user" : "assistant");
      if (message.role === "assistant") {
        item.innerHTML = formatMessage(message.content);
      } else {
        if (message.question) {
          const badge = document.createElement("span");
          badge.textContent = "题目";
          badge.style.cssText = "display:block;color:#9ebcff;font-size:11px;margin-bottom:3px;";
          item.appendChild(badge);
        }
        const text = document.createElement("div");
        text.textContent = message.content;
        item.appendChild(text);
      }
      chat.appendChild(item);
    }
    chat.scrollTop = chat.scrollHeight;
  }

  async function save() {
    try {
      await chrome.storage.local.set({ [STORAGE_KEY]: messages.slice(-100) });
    } catch (error) {
      console.warn("DMate: unable to save local side-panel history.", error);
    }
  }

  async function restore() {
    try {
      const stored = await chrome.storage.local.get(STORAGE_KEY);
      messages = Array.isArray(stored[STORAGE_KEY]) ? stored[STORAGE_KEY] : [];
    } catch (error) {
      messages = [];
      console.warn("DMate: unable to restore local side-panel history.", error);
    }
    render();
  }

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    sendButton.setAttribute("aria-label", value ? "正在回答" : "发送");
  }

  function addError(message) {
    const error = document.createElement("div");
    error.className = "error";
    error.textContent = message;
    chat.appendChild(error);
    chat.scrollTop = chat.scrollHeight;
  }

  async function sendMessage(text) {
    if (busy || !text.trim()) return;

    const userMessage = {
      role: "user",
      content: text.trim(),
      question: questionMode()
    };
    messages.push(userMessage);
    render();
    prompt.value = "";
    prompt.style.height = "42px";
    await save();
    setBusy(true);

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "DMate 正在思考…";
    chat.appendChild(typing);
    chat.scrollTop = chat.scrollHeight;

    try {
      const response = await fetch(API_BASE + "/chat", {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({
          messages: messages.slice(-64).map(({ role, content }) => ({ role, content })),
          language: "zh-CN"
        })
      });

      let result;
      try {
        result = await response.json();
      } catch (_) {
        throw new Error("服务器返回了无法识别的响应（HTTP " + response.status + "）。");
      }
      if (!response.ok) {
        throw new Error(result.error || result.message || ("请求失败（HTTP " + response.status + "）。"));
      }
      if (typeof result.reply !== "string" || !result.reply.trim()) {
        throw new Error("DMate 没有返回有效回答，请稍后重试。");
      }

      messages.push({ role: "assistant", content: result.reply });
      await save();
    } catch (error) {
      messages.push({ role: "assistant", content: "请求失败：" + (error?.message || "连接 DMate 失败，请检查网络后重试。") });
      await save();
    } finally {
      typing.remove();
      setBusy(false);
      render();
      prompt.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(prompt.value);
  });

  prompt.addEventListener("input", () => {
    prompt.style.height = "42px";
    prompt.style.height = Math.min(prompt.scrollHeight, 150) + "px";
  });

  prompt.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  menuButton.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
  });

  document.addEventListener("click", (event) => {
    if (!menu.hidden && !menu.contains(event.target) && !menuButton.contains(event.target)) {
      menu.hidden = true;
    }
  });

  document.getElementById("newChat").addEventListener("click", async () => {
    messages = [];
    await save();
    render();
    menu.hidden = true;
    prompt.focus();
  });

  document.getElementById("settingsButton").addEventListener("click", () => {
    chrome.tabs.create({ url: API_BASE + "/" });
  });

  restore();
})();
