marked.setOptions({
    gfm: true,
    breaks: true
});

const STORAGE_KEY = "discrete_math_ai_sessions_v1";
const LEARNING_STORAGE_KEY = "discrete_math_ai_learning_v1";
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_WRONG_QUESTIONS = 80;
const FALLBACK_API_CONTEXT_MESSAGES = 12;

const CLOUD_SYNC_META_KEY = "discrete_math_ai_cloud_sync_v1";
const CLOUD_BACKUP_KEY = "discrete_math_ai_cloud_backup_v1";
const CLOUD_SYNC_DEBOUNCE_MS = 900;
let accountState = {
    configured: null,
    authenticated: false,
    username: "",
    revision: 0,
    syncing: false,
    status: ""
};
let cloudSyncTimer = 0;
let cloudApplyingSnapshot = false;



// =========================================================
// 外观系统（仅视觉状态，不读写学习/会话数据）
// =========================================================
const APPEARANCE_STORAGE_KEY = "discrete_math_ai_appearance_v1";
const APPEARANCE_DB_NAME = "discrete_math_ai_appearance_assets_v1";
const APPEARANCE_DB_STORE = "assets";
const APPEARANCE_BACKGROUND_KEY = "global_background";
const APPEARANCE_MAX_SOURCE_BYTES = 15 * 1024 * 1024;
const APPEARANCE_MAX_IMAGE_SIDE = 1920;

const APPEARANCE_DEFAULTS = Object.freeze({
    mode: "dark",
    accent: "blue",
    fontSize: "standard",
    backgroundFit: "cover",
    mask: 35,
    blur: 0,
    panelOpacity: 100,
    bubbleOpacity: 100
});

const APPEARANCE_ACCENTS = Object.freeze({
    blue: {
        main: "#3b82f6",
        rgb: "59,130,246",
        deep: "#2563eb",
        deeper: "#1d4ed8",
        soft: "#60a5fa",
        pale: "#93c5fd"
    },
    purple: {
        main: "#8b5cf6",
        rgb: "139,92,246",
        deep: "#7c3aed",
        deeper: "#6d28d9",
        soft: "#a78bfa",
        pale: "#c4b5fd"
    },
    teal: {
        main: "#14b8a6",
        rgb: "20,184,166",
        deep: "#0d9488",
        deeper: "#0f766e",
        soft: "#5eead4",
        pale: "#99f6e4"
    }
});

let appearanceSettings = { ...APPEARANCE_DEFAULTS };
let appearanceBackgroundObjectUrl = "";
let appearanceHasBackground = false;
let appearanceSystemMedia = null;

function clampAppearanceNumber(value, min, max, fallback) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return fallback;
    }

    return Math.min(max, Math.max(min, number));
}

function normalizeAppearanceSettings(value) {
    const source = value && typeof value === "object"
        ? value
        : {};

    return {
        mode: ["system", "light", "dark"].includes(source.mode)
            ? source.mode
            : APPEARANCE_DEFAULTS.mode,
        accent: Object.prototype.hasOwnProperty.call(
            APPEARANCE_ACCENTS,
            source.accent
        )
            ? source.accent
            : APPEARANCE_DEFAULTS.accent,
        fontSize: ["small", "standard", "large"].includes(source.fontSize)
            ? source.fontSize
            : APPEARANCE_DEFAULTS.fontSize,
        backgroundFit: ["cover", "contain"].includes(source.backgroundFit)
            ? source.backgroundFit
            : APPEARANCE_DEFAULTS.backgroundFit,
        mask: clampAppearanceNumber(
            source.mask,
            0,
            70,
            APPEARANCE_DEFAULTS.mask
        ),
        blur: clampAppearanceNumber(
            source.blur,
            0,
            12,
            APPEARANCE_DEFAULTS.blur
        ),
        panelOpacity: clampAppearanceNumber(
            source.panelOpacity,
            75,
            100,
            APPEARANCE_DEFAULTS.panelOpacity
        ),
        bubbleOpacity: clampAppearanceNumber(
            source.bubbleOpacity,
            60,
            100,
            APPEARANCE_DEFAULTS.bubbleOpacity
        )
    };
}

function loadAppearanceSettings() {
    try {
        const raw = localStorage.getItem(APPEARANCE_STORAGE_KEY);

        if (!raw) {
            return { ...APPEARANCE_DEFAULTS };
        }

        return normalizeAppearanceSettings(JSON.parse(raw));
    } catch (_error) {
        return { ...APPEARANCE_DEFAULTS };
    }
}

function saveAppearanceSettings() {
    try {
        localStorage.setItem(
            APPEARANCE_STORAGE_KEY,
            JSON.stringify(appearanceSettings)
        );
    } catch (_error) {
        // 外观保存失败不应影响学习系统本身。
    }
    scheduleCloudSync();
}

function resolveAppearanceTheme() {
    if (appearanceSettings.mode === "light") {
        return "light";
    }

    if (appearanceSettings.mode === "dark") {
        return "dark";
    }

    try {
        return window.matchMedia("(prefers-color-scheme: light)").matches
            ? "light"
            : "dark";
    } catch (_error) {
        return "dark";
    }
}

function fontScaleForAppearance(size) {
    if (size === "small") return 0.92;
    if (size === "large") return 1.08;
    return 1;
}

function applyAppearanceSettings(options = {}) {
    const root = document.documentElement;
    const body = document.body;

    if (!root || !body) return;

    appearanceSettings = normalizeAppearanceSettings(appearanceSettings);

    const accent = APPEARANCE_ACCENTS[appearanceSettings.accent]
        || APPEARANCE_ACCENTS.blue;
    const theme = resolveAppearanceTheme();

    body.dataset.appearanceTheme = theme;
    root.dataset.appearanceTheme = theme;

    // 用户明确选择浅色时用 only light，阻止部分安卓浏览器再次强制染成深色。
    const browserColorScheme = theme === "light" ? "only light" : "dark";
    root.style.colorScheme = browserColorScheme;
    body.style.colorScheme = browserColorScheme;
    document.querySelector('meta[name="color-scheme"]')
        ?.setAttribute(
            "content",
            theme === "light" ? "only light" : "dark"
        );
    document.querySelector('meta[name="supported-color-schemes"]')
        ?.setAttribute(
            "content",
            theme === "light" ? "light" : "dark"
        );
    root.style.setProperty("--accent", accent.main);
    root.style.setProperty("--accent-rgb", accent.rgb);
    root.style.setProperty("--accent-deep", accent.deep);
    root.style.setProperty("--accent-deeper", accent.deeper);
    root.style.setProperty("--accent-soft", accent.soft);
    root.style.setProperty("--accent-pale", accent.pale);
    root.style.setProperty(
        "--accent-bg",
        `rgba(${accent.rgb},.22)`
    );
    const panelAlpha = appearanceSettings.panelOpacity / 100;

    root.style.setProperty(
        "--panel-alpha",
        String(panelAlpha)
    );
    // 全屏壁纸模式下的三层透明度。显式算成数字写入 CSS，
    // 避免依赖浏览器对 calc() 乘法的支持。
    root.style.setProperty(
        "--workspace-alpha",
        String(Math.max(0.08, Math.min(0.18, panelAlpha * 0.14)))
    );
    root.style.setProperty(
        "--shell-alpha",
        String(Math.max(0.30, Math.min(0.48, panelAlpha * 0.44)))
    );
    root.style.setProperty(
        "--composer-alpha",
        String(Math.max(0.38, Math.min(0.58, panelAlpha * 0.52)))
    );
    root.style.setProperty(
        "--bubble-alpha",
        String(appearanceSettings.bubbleOpacity / 100)
    );
    root.style.setProperty(
        "--font-scale",
        String(fontScaleForAppearance(appearanceSettings.fontSize))
    );
    root.style.setProperty(
        "--background-mask-alpha",
        String(appearanceSettings.mask / 100)
    );
    root.style.setProperty(
        "--background-blur",
        `${appearanceSettings.blur}px`
    );
    root.style.setProperty(
        "--background-size",
        appearanceSettings.backgroundFit
    );

    if (options.save !== false) {
        saveAppearanceSettings();
    }

    syncAppearanceControls();

    const graphModal = document.getElementById("knowledgeGraphModal");
    if (
        graphModal
        && !graphModal.classList.contains("hidden")
        && typeof renderKnowledgeGraph === "function"
    ) {
        renderKnowledgeGraph();
    }
}

function syncAppearanceControls() {
    document.querySelectorAll("[data-appearance-mode]").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.appearanceMode === appearanceSettings.mode
        );
    });

    document.querySelectorAll("[data-appearance-accent]").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.appearanceAccent === appearanceSettings.accent
        );
    });

    document.querySelectorAll("[data-appearance-font]").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.appearanceFont === appearanceSettings.fontSize
        );
    });

    document.querySelectorAll("[data-appearance-fit]").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.appearanceFit === appearanceSettings.backgroundFit
        );
    });

    const pairs = [
        ["appearanceMaskRange", "appearanceMaskValue", appearanceSettings.mask, "%"],
        ["appearanceBlurRange", "appearanceBlurValue", appearanceSettings.blur, "px"],
        ["appearancePanelRange", "appearancePanelValue", appearanceSettings.panelOpacity, "%"],
        ["appearanceBubbleRange", "appearanceBubbleValue", appearanceSettings.bubbleOpacity, "%"]
    ];

    for (const [rangeId, valueId, value, suffix] of pairs) {
        const range = document.getElementById(rangeId);
        const output = document.getElementById(valueId);

        if (range) range.value = String(value);
        if (output) output.textContent = `${value}${suffix}`;
    }

    updateAppearanceBackgroundUi();
}

function openAppearance() {
    syncAppearanceControls();
    document.getElementById("appearanceModal")?.classList.remove("hidden");
}

function closeAppearance() {
    document.getElementById("appearanceModal")?.classList.add("hidden");
}

function openAppearanceDatabase() {
    return new Promise((resolve, reject) => {
        if (!("indexedDB" in window)) {
            reject(new Error("IndexedDB unavailable"));
            return;
        }

        const request = indexedDB.open(APPEARANCE_DB_NAME, 1);

        request.onupgradeneeded = () => {
            const db = request.result;

            if (!db.objectStoreNames.contains(APPEARANCE_DB_STORE)) {
                db.createObjectStore(APPEARANCE_DB_STORE);
            }
        };

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("IndexedDB open failed"));
    });
}

async function readAppearanceBackgroundBlob() {
    const db = await openAppearanceDatabase();

    try {
        return await new Promise((resolve, reject) => {
            const tx = db.transaction(APPEARANCE_DB_STORE, "readonly");
            const store = tx.objectStore(APPEARANCE_DB_STORE);
            const request = store.get(APPEARANCE_BACKGROUND_KEY);

            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error || new Error("Background read failed"));
        });
    } finally {
        db.close();
    }
}

async function writeAppearanceBackgroundBlob(blob) {
    const db = await openAppearanceDatabase();

    try {
        await new Promise((resolve, reject) => {
            const tx = db.transaction(APPEARANCE_DB_STORE, "readwrite");
            tx.objectStore(APPEARANCE_DB_STORE).put(
                blob,
                APPEARANCE_BACKGROUND_KEY
            );
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error || new Error("Background save failed"));
            tx.onabort = () => reject(tx.error || new Error("Background save aborted"));
        });
    } finally {
        db.close();
    }
}

async function deleteAppearanceBackgroundBlob() {
    const db = await openAppearanceDatabase();

    try {
        await new Promise((resolve, reject) => {
            const tx = db.transaction(APPEARANCE_DB_STORE, "readwrite");
            tx.objectStore(APPEARANCE_DB_STORE).delete(
                APPEARANCE_BACKGROUND_KEY
            );
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error || new Error("Background delete failed"));
            tx.onabort = () => reject(tx.error || new Error("Background delete aborted"));
        });
    } finally {
        db.close();
    }
}

function clearAppearanceBackgroundVisual() {
    if (appearanceBackgroundObjectUrl) {
        URL.revokeObjectURL(appearanceBackgroundObjectUrl);
        appearanceBackgroundObjectUrl = "";
    }

    appearanceHasBackground = false;
    document.body?.classList.remove("has-custom-background");

    const layer = document.getElementById("appearanceBackgroundLayer");
    if (layer) layer.style.backgroundImage = "none";

    updateAppearanceBackgroundUi();
}

function setAppearanceBackgroundVisual(blob) {
    clearAppearanceBackgroundVisual();

    if (!(blob instanceof Blob)) {
        return;
    }

    appearanceBackgroundObjectUrl = URL.createObjectURL(blob);
    appearanceHasBackground = true;

    const layer = document.getElementById("appearanceBackgroundLayer");
    if (layer) {
        layer.style.backgroundImage = `url("${appearanceBackgroundObjectUrl}")`;
    }

    document.body?.classList.add("has-custom-background");
    updateAppearanceBackgroundUi();
}

function updateAppearanceBackgroundUi() {
    const preview = document.getElementById("appearanceBackgroundPreview");
    const remove = document.getElementById("appearanceBackgroundRemove");

    if (preview) {
        if (appearanceHasBackground && appearanceBackgroundObjectUrl) {
            preview.textContent = "";
            preview.style.backgroundImage = `url("${appearanceBackgroundObjectUrl}")`;
            preview.dataset.hasBackground = "true";
            preview.tabIndex = 0;
            preview.setAttribute("role", "button");
            preview.setAttribute("aria-label", "查看当前背景大图");
        } else {
            preview.textContent = "无背景";
            preview.style.backgroundImage = "none";
            preview.dataset.hasBackground = "false";
            preview.removeAttribute("tabindex");
            preview.removeAttribute("role");
            preview.removeAttribute("aria-label");
        }
    }

    if (remove) {
        remove.disabled = !appearanceHasBackground;
    }
}


function openAppearanceBackgroundViewer() {
    if (!appearanceHasBackground || !appearanceBackgroundObjectUrl) return;

    const modal = document.getElementById("appearanceBackgroundViewer");
    const image = document.getElementById("appearanceBackgroundViewerImage");
    if (!modal || !image) return;

    image.src = appearanceBackgroundObjectUrl;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
}

function closeAppearanceBackgroundViewer() {
    const modal = document.getElementById("appearanceBackgroundViewer");
    const image = document.getElementById("appearanceBackgroundViewerImage");
    if (image) image.removeAttribute("src");
    if (modal) {
        modal.classList.add("hidden");
        modal.setAttribute("aria-hidden", "true");
    }
}

async function loadAppearanceBackground() {
    try {
        const blob = await readAppearanceBackgroundBlob();

        if (blob instanceof Blob) {
            setAppearanceBackgroundVisual(blob);
        } else {
            clearAppearanceBackgroundVisual();
        }
    } catch (_error) {
        clearAppearanceBackgroundVisual();
    }
}

function loadImageElementFromBlob(blob) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(blob);
        const image = new Image();

        image.onload = () => {
            URL.revokeObjectURL(url);
            resolve(image);
        };

        image.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error("Image decode failed"));
        };

        image.src = url;
    });
}

async function prepareAppearanceBackgroundBlob(file) {
    const supported = ["image/jpeg", "image/png", "image/webp"];

    if (!(file instanceof Blob) || !supported.includes(file.type)) {
        throw new Error("Unsupported image type");
    }

    if (file.size > APPEARANCE_MAX_SOURCE_BYTES) {
        throw new Error("Image too large");
    }

    const image = await loadImageElementFromBlob(file);
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;

    if (!width || !height) {
        throw new Error("Invalid image size");
    }

    const ratio = Math.min(
        1,
        APPEARANCE_MAX_IMAGE_SIDE / Math.max(width, height)
    );
    const targetWidth = Math.max(1, Math.round(width * ratio));
    const targetHeight = Math.max(1, Math.round(height * ratio));

    const canvas = document.createElement("canvas");
    canvas.width = targetWidth;
    canvas.height = targetHeight;

    const context = canvas.getContext("2d", { alpha: true });
    if (!context) {
        throw new Error("Canvas unavailable");
    }

    context.drawImage(image, 0, 0, targetWidth, targetHeight);

    const converted = await new Promise(resolve => {
        canvas.toBlob(
            blob => resolve(blob),
            "image/webp",
            0.88
        );
    });

    return converted instanceof Blob && converted.size > 0
        ? converted
        : file;
}

async function handleAppearanceBackgroundSelected(event) {
    const input = event?.target;
    const file = input?.files?.[0] || null;

    if (input) {
        input.value = "";
    }

    if (!file) return;

    try {
        const blob = await prepareAppearanceBackgroundBlob(file);
        await writeAppearanceBackgroundBlob(blob);
        setAppearanceBackgroundVisual(blob);
    } catch (_error) {
        window.alert("背景图片处理失败，请换一张 JPG、PNG 或 WebP 图片。");
    }
}

async function removeAppearanceBackground() {
    closeAppearanceBackgroundViewer();

    try {
        await deleteAppearanceBackgroundBlob();
    } catch (_error) {
        // 即使持久化删除失败，也先移除当前视觉背景，不影响主功能。
    }

    clearAppearanceBackgroundVisual();
}

async function resetAppearance() {
    closeAppearanceBackgroundViewer();
    appearanceSettings = { ...APPEARANCE_DEFAULTS };
    saveAppearanceSettings();

    try {
        await deleteAppearanceBackgroundBlob();
    } catch (_error) {
        // 无需阻断恢复默认。
    }

    clearAppearanceBackgroundVisual();
    applyAppearanceSettings({ save: false });
}

function setupAppearanceSystemThemeListener() {
    try {
        appearanceSystemMedia = window.matchMedia("(prefers-color-scheme: light)");
        const onChange = () => {
            if (appearanceSettings.mode === "system") {
                applyAppearanceSettings({ save: false });
            }
        };

        if (typeof appearanceSystemMedia.addEventListener === "function") {
            appearanceSystemMedia.addEventListener("change", onChange);
        } else if (typeof appearanceSystemMedia.addListener === "function") {
            appearanceSystemMedia.addListener(onChange);
        }
    } catch (_error) {
        // 不支持系统主题监听时维持当前解析结果即可。
    }
}

function bindAppearanceControls() {
    const appearanceBtn = document.getElementById("appearanceBtn");
    const appearanceClose = document.getElementById("appearanceClose");
    const appearanceDone = document.getElementById("appearanceDone");
    const appearanceReset = document.getElementById("appearanceReset");
    const appearanceModal = document.getElementById("appearanceModal");
    const upload = document.getElementById("appearanceBackgroundUpload");
    const remove = document.getElementById("appearanceBackgroundRemove");
    const input = document.getElementById("appearanceBackgroundInput");
    const preview = document.getElementById("appearanceBackgroundPreview");
    const viewer = document.getElementById("appearanceBackgroundViewer");
    const viewerClose = document.getElementById("appearanceBackgroundViewerClose");

    appearanceBtn?.addEventListener("click", openAppearance);
    appearanceClose?.addEventListener("click", closeAppearance);
    appearanceDone?.addEventListener("click", closeAppearance);
    appearanceReset?.addEventListener("click", resetAppearance);

    appearanceModal?.addEventListener("click", event => {
        if (event.target === appearanceModal) {
            closeAppearance();
        }
    });

    upload?.addEventListener("click", () => input?.click());
    remove?.addEventListener("click", removeAppearanceBackground);
    input?.addEventListener("change", handleAppearanceBackgroundSelected);

    preview?.addEventListener("click", openAppearanceBackgroundViewer);
    preview?.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openAppearanceBackgroundViewer();
        }
    });
    viewerClose?.addEventListener("click", closeAppearanceBackgroundViewer);
    viewer?.addEventListener("click", event => {
        if (event.target === viewer) closeAppearanceBackgroundViewer();
    });

    document.querySelectorAll("[data-appearance-mode]").forEach(button => {
        button.addEventListener("click", () => {
            appearanceSettings.mode = button.dataset.appearanceMode;
            applyAppearanceSettings();
        });
    });

    document.querySelectorAll("[data-appearance-accent]").forEach(button => {
        button.addEventListener("click", () => {
            appearanceSettings.accent = button.dataset.appearanceAccent;
            applyAppearanceSettings();
        });
    });

    document.querySelectorAll("[data-appearance-font]").forEach(button => {
        button.addEventListener("click", () => {
            appearanceSettings.fontSize = button.dataset.appearanceFont;
            applyAppearanceSettings();
        });
    });

    document.querySelectorAll("[data-appearance-fit]").forEach(button => {
        button.addEventListener("click", () => {
            appearanceSettings.backgroundFit = button.dataset.appearanceFit;
            applyAppearanceSettings();
        });
    });

    const sliders = [
        ["appearanceMaskRange", "mask"],
        ["appearanceBlurRange", "blur"],
        ["appearancePanelRange", "panelOpacity"],
        ["appearanceBubbleRange", "bubbleOpacity"]
    ];

    for (const [id, key] of sliders) {
        document.getElementById(id)?.addEventListener("input", event => {
            appearanceSettings[key] = Number(event.target.value);
            applyAppearanceSettings();
        });
    }
}

function initAppearanceSystem() {
    appearanceSettings = loadAppearanceSettings();
    applyAppearanceSettings({ save: false });
    bindAppearanceControls();
    setupAppearanceSystemThemeListener();
    loadAppearanceBackground();
}


let wrongBookFilter = "all";
let wrongBookSearch = "";
let wrongBookSort = "recent";
let currentWrongEditId = null;

let pendingWrongQuestionSelection = null;
let pendingWrongSafeItems = [];
let pendingWrongSafeIndex = 0;

const wrongAnswerLoadingIds = new Set();
const wrongAnswerQueue = [];
let wrongAnswerQueueBusy = false;

const wrongAnalysisExpandedIds = new Set();
const wrongAnalysisLoadingIds = new Set();

let knowledgeGraphData = null;
let knowledgeGraphFilter = "";
let knowledgeGraphViewMode = "focus";
let knowledgeGraphScope = "current";
let knowledgeGraphSelectedNodeId = "";
let knowledgeGraphHistoryMessageIndex = null;
let knowledgeGraphSideMode = "detail";
let knowledgeGraphLoading = false;

let sessions = [];
let currentId = null;
let learningState = createEmptyLearningState();


// =========================================================
// 账号 + 云同步（用户名 / 密码）
// =========================================================
function readCloudSyncMeta() {
    try {
        const parsed = JSON.parse(localStorage.getItem(CLOUD_SYNC_META_KEY) || "null");
        if (!parsed || typeof parsed !== "object") return {};
        return parsed;
    } catch (_error) {
        return {};
    }
}

function writeCloudSyncMeta(patch = {}) {
    const next = {
        ...readCloudSyncMeta(),
        ...patch
    };
    try {
        localStorage.setItem(CLOUD_SYNC_META_KEY, JSON.stringify(next));
    } catch (_error) {
        // 同步元信息失败不影响本地使用。
    }
    return next;
}

function clearCloudSyncMeta() {
    try {
        localStorage.removeItem(CLOUD_SYNC_META_KEY);
    } catch (_error) {}
}

function collectCloudSnapshot() {
    return {
        schemaVersion: 1,
        sessions: {
            sessions,
            currentId
        },
        learning: learningState,
        appearance: appearanceSettings
    };
}

function snapshotHasUserData(snapshot) {
    if (!snapshot || typeof snapshot !== "object") return false;
    const sessionList = Array.isArray(snapshot.sessions?.sessions)
        ? snapshot.sessions.sessions
        : [];
    if (sessionList.some(item => Array.isArray(item?.messages) && item.messages.length)) {
        return true;
    }
    const learning = snapshot.learning;
    if (Array.isArray(learning?.events) && learning.events.length) return true;
    if (Array.isArray(learning?.wrongQuestions) && learning.wrongQuestions.length) return true;
    return false;
}

function backupLocalSnapshot(reason = "切换云端数据") {
    const snapshot = collectCloudSnapshot();
    if (!snapshotHasUserData(snapshot)) return;
    try {
        localStorage.setItem(
            CLOUD_BACKUP_KEY,
            JSON.stringify({
                reason,
                createdAt: Date.now(),
                data: snapshot
            })
        );
    } catch (_error) {
        // 空间不足时只是不创建备份，不影响登录。
    }
}

function applyCloudSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== "object") return false;
    cloudApplyingSnapshot = true;

    try {
        const sessionData = snapshot.sessions;
        if (sessionData && typeof sessionData === "object" && Array.isArray(sessionData.sessions)) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                sessions: sessionData.sessions,
                currentId: sessionData.currentId ?? null
            }));
            loadState();
        }

        if (snapshot.learning && typeof snapshot.learning === "object") {
            localStorage.setItem(LEARNING_STORAGE_KEY, JSON.stringify(snapshot.learning));
            loadLearningState();
        }

        if (snapshot.appearance && typeof snapshot.appearance === "object") {
            appearanceSettings = normalizeAppearanceSettings(snapshot.appearance);
            localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(appearanceSettings));
            applyAppearanceSettings({ save:false });
        }

        renderAll();
        refreshInputAvailability();
        return true;
    } catch (error) {
        console.warn("应用云端数据失败：", error);
        return false;
    } finally {
        cloudApplyingSnapshot = false;
    }
}

function accountSyncText() {
    if (!accountState.authenticated) return "";
    if (accountState.syncing) return "同步中…";
    const meta = readCloudSyncMeta();
    if (meta.username === accountState.username && meta.dirty) {
        return "等待同步";
    }
    return accountState.status || "已同步";
}

function renderAccountUi() {
    const entry = document.getElementById("accountBtn");
    const label = document.getElementById("accountEntryLabel");
    const guest = document.getElementById("accountGuestView");
    const user = document.getElementById("accountUserView");
    const username = document.getElementById("accountCurrentUsername");
    const syncState = document.getElementById("accountSyncState");
    const login = document.getElementById("accountLogin");
    const register = document.getElementById("accountRegister");
    const logout = document.getElementById("accountLogout");
    const deleteOpen = document.getElementById("accountDeleteOpen");
    const deleteConfirm = document.getElementById("accountDeleteConfirm");
    const deleteCancel = document.getElementById("accountDeleteCancel");

    entry?.classList.toggle("is-authenticated", accountState.authenticated);
    entry?.classList.toggle("is-syncing", accountState.syncing);

    if (label) {
        label.textContent = accountState.authenticated
            ? accountState.username
            : "登录 / 注册";
    }

    guest?.classList.toggle("hidden", accountState.authenticated);
    user?.classList.toggle("hidden", !accountState.authenticated);

    if (!accountState.authenticated) {
        setAccountDeletePanel(false);
    }

    if (username) username.textContent = accountState.username;
    if (syncState) syncState.textContent = accountSyncText();

    const unavailable = accountState.configured === false;
    if (login) login.disabled = unavailable || accountState.syncing;
    if (register) register.disabled = unavailable || accountState.syncing;
    if (logout) logout.disabled = accountState.syncing;
    if (deleteOpen) deleteOpen.disabled = accountState.syncing;
    if (deleteConfirm) deleteConfirm.disabled = accountState.syncing;
    if (deleteCancel) deleteCancel.disabled = accountState.syncing;

    if (unavailable) {
        setAccountMessage("服务器还没有配置账号数据库。", true);
    }
}

function setAccountMessage(message = "", isError = false) {
    const box = document.getElementById("accountMessage");
    if (!box) return;
    box.textContent = String(message || "");
    box.classList.toggle("error", Boolean(isError));
}

function openAccountModal() {
    closeMobileShellDrawers();
    const modal = document.getElementById("accountModal");
    if (!modal) return;

    if (!accountState.authenticated) {
        setAccountDeletePanel(false);
    }

    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    renderAccountUi();
}

function setAccountDeleteMessage(message = "", isError = false) {
    const box = document.getElementById("accountDeleteMessage");
    if (!box) return;
    box.textContent = String(message || "");
    box.classList.toggle("error", Boolean(isError));
}

function setAccountDeletePanel(open) {
    const panel = document.getElementById("accountDeletePanel");
    const password = document.getElementById("accountDeletePassword");
    panel?.classList.toggle("hidden", !open);
    if (!open) {
        if (password) password.value = "";
        setAccountDeleteMessage("");
    } else {
        window.setTimeout(() => password?.focus(), 40);
    }
}

function closeAccountModal() {
    const modal = document.getElementById("accountModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    const password = document.getElementById("accountPassword");
    if (password) password.value = "";
    setAccountDeletePanel(false);
    setAccountMessage("");
}

async function accountFetch(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        ...options,
        headers: {
            ...(options.body ? { "Content-Type":"application/json" } : {}),
            ...(options.headers || {})
        }
    });

    let data = {};
    try {
        data = await response.json();
    } catch (_error) {}

    if (!response.ok && response.status !== 409) {
        const error = new Error(data?.error || `请求失败（${response.status}）`);
        error.status = response.status;
        error.data = data;
        throw error;
    }

    return { response, data };
}

function scheduleCloudSync() {
    if (cloudApplyingSnapshot) return;

    const meta = readCloudSyncMeta();
    if (meta.username) {
        writeCloudSyncMeta({ dirty:true });
    }

    if (!accountState.authenticated) return;

    if (cloudSyncTimer) {
        clearTimeout(cloudSyncTimer);
    }
    cloudSyncTimer = window.setTimeout(() => {
        cloudSyncTimer = 0;
        pushCloudSnapshot(false);
    }, CLOUD_SYNC_DEBOUNCE_MS);
    renderAccountUi();
}

async function pushCloudSnapshot(force = false) {
    if (!accountState.authenticated || accountState.syncing) return false;

    const meta = readCloudSyncMeta();
    const baseRevision = Number.isFinite(Number(meta.revision))
        ? Number(meta.revision)
        : Number(accountState.revision || 0);

    accountState.syncing = true;
    accountState.status = "同步中…";
    renderAccountUi();

    try {
        const { response, data } = await accountFetch("/sync", {
            method:"PUT",
            body:JSON.stringify({
                baseRevision,
                force:Boolean(force),
                data:collectCloudSnapshot()
            })
        });

        if (response.status === 409 && data?.conflict) {
            accountState.syncing = false;
            const overwrite = window.confirm(
                "云端数据已在其他设备更新。\n\n确定：用本设备数据覆盖云端\n取消：使用云端最新数据"
            );

            if (overwrite) {
                accountState.revision = Number(data.revision || 0);
                writeCloudSyncMeta({
                    username:accountState.username,
                    revision:accountState.revision,
                    dirty:true
                });
                return await pushCloudSnapshot(true);
            }

            backupLocalSnapshot("同步冲突前的本机数据");
            applyCloudSnapshot(data.data || {});
            accountState.revision = Number(data.revision || 0);
            accountState.status = "已同步";
            writeCloudSyncMeta({
                username:accountState.username,
                revision:accountState.revision,
                dirty:false
            });
            renderAccountUi();
            showCopyToast("已加载云端最新数据");
            return true;
        }

        accountState.revision = Number(data.revision || 0);
        accountState.status = "已同步";
        writeCloudSyncMeta({
            username:accountState.username,
            revision:accountState.revision,
            dirty:false
        });
        return true;
    } catch (error) {
        console.warn("云同步失败：", error);
        accountState.status = "离线，稍后自动同步";
        writeCloudSyncMeta({
            username:accountState.username,
            revision:baseRevision,
            dirty:true
        });
        return false;
    } finally {
        accountState.syncing = false;
        renderAccountUi();
    }
}

async function resolveInitialCloudSync(isNewAccount = false) {
    if (!accountState.authenticated) return;

    try {
        const { data } = await accountFetch("/sync");
        const cloudRevision = Number(data.revision || 0);
        accountState.revision = cloudRevision;

        if (isNewAccount || cloudRevision === 0) {
            writeCloudSyncMeta({
                username:accountState.username,
                revision:cloudRevision,
                dirty:true
            });
            await pushCloudSnapshot(true);
            return;
        }

        const meta = readCloudSyncMeta();
        const sameAccount = meta.username === accountState.username;
        const localDirty = sameAccount && Boolean(meta.dirty);
        const localRevision = sameAccount ? Number(meta.revision || 0) : -1;

        if (!sameAccount) {
            backupLocalSnapshot("登录后切换到云端数据");
            applyCloudSnapshot(data.data || {});
        } else if (localDirty && localRevision === cloudRevision) {
            await pushCloudSnapshot(false);
            return;
        } else if (localDirty && localRevision !== cloudRevision) {
            const overwrite = window.confirm(
                "本设备和云端都有未合并的更新。\n\n确定：保留本设备并覆盖云端\n取消：使用云端数据"
            );
            if (overwrite) {
                accountState.revision = cloudRevision;
                writeCloudSyncMeta({ revision:cloudRevision, dirty:true });
                await pushCloudSnapshot(true);
                return;
            }
            backupLocalSnapshot("登录同步冲突前的本机数据");
            applyCloudSnapshot(data.data || {});
        } else if (cloudRevision > localRevision) {
            applyCloudSnapshot(data.data || {});
        }

        writeCloudSyncMeta({
            username:accountState.username,
            revision:cloudRevision,
            dirty:false
        });
        accountState.status = "已同步";
        renderAccountUi();
    } catch (error) {
        console.warn("初始化云同步失败：", error);
        accountState.status = "离线，稍后自动同步";
        renderAccountUi();
    }
}

async function submitAccountAuth(mode) {
    if (accountState.syncing) return;

    const usernameInput = document.getElementById("accountUsername");
    const passwordInput = document.getElementById("accountPassword");
    const username = usernameInput?.value?.trim() || "";
    const password = passwordInput?.value || "";

    if (!username || !password) {
        setAccountMessage("请输入用户名和密码。", true);
        return;
    }

    accountState.syncing = true;
    renderAccountUi();
    setAccountMessage(mode === "register" ? "正在注册…" : "正在登录…");

    try {
        const { data } = await accountFetch(
            mode === "register" ? "/auth/register" : "/auth/login",
            {
                method:"POST",
                body:JSON.stringify({ username, password })
            }
        );

        accountState.configured = data.configured !== false;
        accountState.authenticated = true;
        accountState.username = String(data.user?.username || username);
        accountState.revision = Number(data.revision || 0);
        accountState.status = "同步中…";
        writeCloudSyncMeta({
            username:accountState.username,
            revision:accountState.revision,
            dirty:mode === "register"
        });

        if (passwordInput) passwordInput.value = "";
        setAccountMessage("");
        setAccountDeletePanel(false);
        accountState.syncing = false;

        // 注册成功即已经由后端建立 Session，不需要再登录一次。
        // 这里立即切到“已登录”视图，再在后台完成首次云同步。
        renderAccountUi();
        if (mode === "register") {
            showCopyToast("注册成功，已登录");
        } else {
            showCopyToast("登录成功");
        }

        await resolveInitialCloudSync(mode === "register");
    } catch (error) {
        accountState.syncing = false;
        setAccountMessage(error?.message || "操作失败，请稍后再试。", true);
        renderAccountUi();
    }
}

async function logoutAccount() {
    if (accountState.syncing) return;

    const meta = readCloudSyncMeta();
    if (meta.username === accountState.username && meta.dirty) {
        const synced = await pushCloudSnapshot(false);
        if (!synced && !window.confirm(
            "本设备还有尚未同步到云端的数据。\n\n仍然退出登录吗？本地数据会保留。"
        )) {
            return;
        }
    }

    accountState.syncing = true;
    accountState.status = "正在退出…";
    renderAccountUi();

    try {
        await accountFetch("/auth/logout", {
            method:"POST",
            body:JSON.stringify({})
        });
    } catch (error) {
        accountState.syncing = false;
        accountState.status = "退出失败";
        setAccountMessage(error?.message || "退出登录失败，请检查网络后重试。", true);
        renderAccountUi();
        return;
    }

    accountState.authenticated = false;
    accountState.username = "";
    accountState.revision = 0;
    accountState.status = "";
    accountState.syncing = false;
    clearCloudSyncMeta();
    if (cloudSyncTimer) {
        clearTimeout(cloudSyncTimer);
        cloudSyncTimer = 0;
    }
    renderAccountUi();
    closeAccountModal();
    showCopyToast("已退出登录");
}

async function deleteAccount() {
    if (!accountState.authenticated || accountState.syncing) return;

    const passwordInput = document.getElementById("accountDeletePassword");
    const password = passwordInput?.value || "";
    if (!password) {
        setAccountDeleteMessage("请输入当前密码。", true);
        passwordInput?.focus();
        return;
    }

    const confirmed = window.confirm(
        "确定永久注销这个账号吗？\n\n账号和云端同步数据都会被删除，此操作无法撤销。\n本设备当前的本地学习数据会保留。"
    );
    if (!confirmed) return;

    accountState.syncing = true;
    accountState.status = "正在注销…";
    setAccountDeleteMessage("正在注销账号…");
    renderAccountUi();

    try {
        await accountFetch("/auth/delete-account", {
            method:"POST",
            body:JSON.stringify({ password })
        });
    } catch (error) {
        accountState.syncing = false;
        accountState.status = "";
        setAccountDeleteMessage(error?.message || "注销账号失败，请稍后再试。", true);
        renderAccountUi();
        return;
    }

    accountState.authenticated = false;
    accountState.username = "";
    accountState.revision = 0;
    accountState.status = "";
    accountState.syncing = false;
    clearCloudSyncMeta();
    if (cloudSyncTimer) {
        clearTimeout(cloudSyncTimer);
        cloudSyncTimer = 0;
    }
    setAccountDeletePanel(false);
    renderAccountUi();
    closeAccountModal();
    showCopyToast("账号已注销，本机数据已保留");
}

async function initAccountSystem() {
    const accountBtn = document.getElementById("accountBtn");
    const accountClose = document.getElementById("accountClose");
    const accountModal = document.getElementById("accountModal");
    const accountLogin = document.getElementById("accountLogin");
    const accountRegister = document.getElementById("accountRegister");
    const accountLogout = document.getElementById("accountLogout");
    const accountDeleteOpen = document.getElementById("accountDeleteOpen");
    const accountDeleteCancel = document.getElementById("accountDeleteCancel");
    const accountDeleteConfirm = document.getElementById("accountDeleteConfirm");
    const accountDeletePassword = document.getElementById("accountDeletePassword");
    const password = document.getElementById("accountPassword");

    accountBtn?.addEventListener("click", openAccountModal);
    accountClose?.addEventListener("click", closeAccountModal);
    accountLogin?.addEventListener("click", () => submitAccountAuth("login"));
    accountRegister?.addEventListener("click", () => submitAccountAuth("register"));
    accountLogout?.addEventListener("click", logoutAccount);
    accountDeleteOpen?.addEventListener("click", () => setAccountDeletePanel(true));
    accountDeleteCancel?.addEventListener("click", () => setAccountDeletePanel(false));
    accountDeleteConfirm?.addEventListener("click", deleteAccount);
    accountDeletePassword?.addEventListener("keydown", event => {
        if (event.key === "Enter") deleteAccount();
    });
    accountModal?.addEventListener("click", event => {
        if (event.target === accountModal) closeAccountModal();
    });
    password?.addEventListener("keydown", event => {
        if (event.key === "Enter") submitAccountAuth("login");
    });

    window.addEventListener("online", () => {
        const meta = readCloudSyncMeta();
        if (accountState.authenticated && meta.dirty) {
            pushCloudSnapshot(false);
        }
    }, { passive:true });

    renderAccountUi();

    try {
        const { data } = await accountFetch("/auth/me");
        accountState.configured = data.configured !== false;
        accountState.authenticated = Boolean(data.authenticated);
        accountState.username = accountState.authenticated
            ? String(data.user?.username || "")
            : "";
        renderAccountUi();

        if (accountState.authenticated) {
            await resolveInitialCloudSync(false);
        }
    } catch (error) {
        console.warn("读取账号状态失败：", error);
        if (error?.status === 503) {
            accountState.configured = false;
        }
        renderAccountUi();
    }
}


let typingTimer = null;
let typingFullText = "";
let typingDiv = null;
let typingSessionId = null;
let typingMeta = null;

let typingAutoFollow = true;
let typingScrollLockedByUser = false;
let lastTypingAutoScrollAt = 0;
let preserveChatScrollOnce = null;
let forceChatBottomOnce = false;
let lastRenderedChatSessionId = null;

const TYPING_RENDER_INTERVAL = 30;
const TYPING_CHARS_PER_TICK = 3;
const LONG_RESPONSE_DIRECT_RENDER_CHARS = 2200;

const busySessionIds = new Set();
const pendingAiStartSessionIds = new Set();


// -----------------------------
// 基础状态
// -----------------------------
function getCurrent() {
    return sessions.find(s => s.id === currentId) || null;
}

function makeSessionId() {
    let id = Date.now();

    while (sessions.some(s => s.id === id)) {
        id += 1;
    }

    return id;
}

function enableInput(enable) {
    const input = document.getElementById("text");
    const sendBtn = document.getElementById("sendBtn");
    const imageBtn = document.getElementById("imageBtn");

    if (input) input.disabled = !enable;
    if (sendBtn) sendBtn.disabled = !enable;
    if (imageBtn) imageBtn.disabled = !enable;
}

function sessionBusyKey(sessionId) {
    return String(sessionId ?? "");
}

function isSessionBusy(sessionId = currentId) {
    if (sessionId === null || sessionId === undefined) {
        return false;
    }

    return busySessionIds.has(
        sessionBusyKey(sessionId)
    );
}

function isSessionPendingAiStart(sessionId = currentId) {
    if (sessionId === null || sessionId === undefined) {
        return false;
    }

    return pendingAiStartSessionIds.has(
        sessionBusyKey(sessionId)
    );
}

function isCurrentSessionTyping() {
    return Boolean(
        typingTimer
        && String(typingSessionId) === String(currentId)
    );
}

function refreshInputAvailability() {
    const pendingStart = isSessionPendingAiStart(currentId);
    const typingNow = isCurrentSessionTyping();
    const waitingReply = isSessionBusy(currentId) || pendingStart;
    const hardBlocked = waitingReply || typingNow;

    const input = document.getElementById("text");
    const sendBtn = document.getElementById("sendBtn");
    const imageBtn = document.getElementById("imageBtn");
    const ocrCancelBtn = document.getElementById("ocrCancelBtn");
    const inputLockHint = document.getElementById("inputLockHint");
    const inputWrap = input?.closest?.(".input-wrap") || null;

    let statusText = "";
    let placeholder = "";
    let busyMode = "";

    if (ocrReviewInProgress) {
        statusText = "图片识别中，主输入框已锁定。";
        placeholder = "图片识别中…";
        busyMode = "ocr";
    } else if (typingNow) {
        statusText = "AI 正在回答，当前输入框已锁定。";
        placeholder = "AI 正在回答…";
        busyMode = "answering";
    } else if (waitingReply) {
        statusText = "AI 正在思考，当前输入框已锁定。";
        placeholder = "AI 正在思考…";
        busyMode = "thinking";
    }

    if (input) {
        input.disabled = hardBlocked || ocrReviewInProgress;
        input.placeholder = placeholder;
    }
    if (sendBtn) {
        sendBtn.disabled = hardBlocked || ocrReviewInProgress;
        sendBtn.textContent = busyMode === "thinking"
            ? "思考中…"
            : (busyMode === "answering" ? "回答中…" : "发送");
    }
    if (imageBtn) imageBtn.disabled = hardBlocked || ocrReviewInProgress;

    if (inputWrap) {
        inputWrap.classList.toggle(
            "ai-input-busy",
            busyMode === "thinking" || busyMode === "answering"
        );
        inputWrap.dataset.busyMode = busyMode;
    }

    if (inputLockHint) {
        inputLockHint.textContent = statusText;
        inputLockHint.classList.toggle("hidden", !statusText);
    }

    if (ocrCancelBtn) {
        ocrCancelBtn.hidden = !ocrRequestInFlight;
        ocrCancelBtn.disabled = !ocrRequestInFlight;
    }
}

function setSessionBusy(sessionId, busy) {
    const key = sessionBusyKey(sessionId);

    if (!key) return;

    if (busy) {
        busySessionIds.add(key);
    } else {
        busySessionIds.delete(key);
    }

    refreshInputAvailability();
}


function normalizeTeaching(value) {
    if (!value || typeof value !== "object") {
        return null;
    }

    const asText = input => (
        typeof input === "string" ? input.trim() : ""
    );

    const asTextList = input => (
        Array.isArray(input)
            ? input
                .filter(item => typeof item === "string" && item.trim())
                .map(item => item.trim())
                .slice(0, 4)
            : []
    );

    return {
        category: asText(value.category) || "待识别",
        related_categories: asTextList(value.related_categories),
        knowledge_points: asTextList(value.knowledge_points),
        focus_points: asTextList(value.focus_points).slice(0, 2),
        prerequisite_points: asTextList(value.prerequisite_points),
        knowledge_path: asTextList(value.knowledge_path),
        question_type: asText(value.question_type) || "综合题",
        difficulty: ["简单", "中等", "困难"].includes(asText(value.difficulty))
            ? asText(value.difficulty)
            : "",
        mode: asText(value.mode) || "hint",
        mode_label: asText(value.mode_label) || "提示引导",
        confidence: asText(value.confidence) || "低",
        input_source: asText(value.input_source) || "文本输入"
    };
}


function normalizeRetestSession(value) {
    if (!value || typeof value !== "object") {
        return null;
    }

    const stage = [
        "generating",
        "awaiting_answer",
        "checking",
        "finished"
    ].includes(value.stage)
        ? value.stage
        : "finished";

    return {
        wrongQuestionId: typeof value.wrongQuestionId === "string"
            ? value.wrongQuestionId
            : "",
        stage,
        targetPoints: Array.isArray(value.targetPoints)
            ? value.targetPoints
                .filter(item => typeof item === "string" && item.trim())
                .map(item => item.trim())
                .slice(0, 2)
            : [],
        referenceQuestion: typeof value.referenceQuestion === "string"
            ? value.referenceQuestion.trim().slice(0, 3000)
            : "",
        generatedQuestion: typeof value.generatedQuestion === "string"
            ? value.generatedQuestion.trim().slice(0, 3000)
            : "",
        generatedAnswer: typeof value.generatedAnswer === "string"
            ? value.generatedAnswer.trim().slice(0, 1200)
            : "",
        startedAt: Number.isFinite(value.startedAt)
            ? value.startedAt
            : Date.now(),
        result: ["correct", "wrong", "unknown"].includes(value.result)
            ? value.result
            : ""
    };
}


function createEmptyLearningState() {
    return {
        version: 8,
        knowledge: {},
        events: [],
        wrongQuestions: []
    };
}

function normalizeLearningQuestion(value) {
    if (!value || typeof value !== "object") {
        return null;
    }

    const text = typeof value.text === "string"
        ? value.text.trim()
        : "";

    if (!text) {
        return null;
    }

    const knowledgePoints = Array.isArray(value.knowledgePoints)
        ? value.knowledgePoints
            .filter(item => typeof item === "string" && item.trim())
            .map(item => item.trim())
            .slice(0, 4)
        : [];

    const focusPoints = Array.isArray(value.focusPoints)
        ? value.focusPoints
            .filter(item => typeof item === "string" && item.trim())
            .map(item => item.trim())
            .slice(0, 2)
        : [];

    return {
        text: text.slice(0, 3000),
        knowledgePoints,
        focusPoints,
        category: typeof value.category === "string"
            ? value.category.trim()
            : "",
        difficulty: ["简单", "中等", "困难"].includes(value.difficulty)
            ? value.difficulty
            : "",
        source: value.source === "ocr"
            ? "ocr"
            : (
                value.source === "ai"
                    ? "ai"
                    : "text"
            ),
        referenceAnswer: typeof value.referenceAnswer === "string"
            ? value.referenceAnswer.trim().slice(0, 1200)
            : "",
        sessionId: (
            typeof value.sessionId === "number"
            || typeof value.sessionId === "string"
        )
            ? value.sessionId
            : null,
        updatedAt: Number.isFinite(value.updatedAt)
            ? value.updatedAt
            : Date.now()
    };
}

function normalizeLearningState(value) {
    const state = createEmptyLearningState();

    if (!value || typeof value !== "object") {
        return state;
    }

    // v4 起学习统计改为“事件账本”。
    // v3 及更早只有总数，没有来源会话，无法在删除对话时准确回滚。
    // 因此升级时保留错题本，但旧的学习计数不继续继承。
    if (
        Number(value.version) >= 4
        && Array.isArray(value.events)
    ) {
        state.events = value.events
            .filter(event => event && typeof event === "object")
            .map(event => ({
                id: typeof event.id === "string" && event.id
                    ? event.id
                    : `learn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                sessionId: (
                    typeof event.sessionId === "number"
                    || typeof event.sessionId === "string"
                )
                    ? event.sessionId
                    : null,
                type: [
                    "seen",
                    "correct",
                    "wrong",
                    "support",
                    "reviewed"
                ].includes(event.type)
                    ? event.type
                    : "",
                points: Array.isArray(event.points)
                    ? [
                        ...new Set(
                            event.points
                                .filter(point => typeof point === "string" && point.trim())
                                .map(point => point.trim())
                        )
                    ].slice(0, 4)
                    : [],
                createdAt: Number.isFinite(event.createdAt)
                    ? event.createdAt
                    : Date.now()
            }))
            .filter(event => event.type && event.points.length)
            .slice(-1000);
    }

    if (Array.isArray(value.wrongQuestions)) {
        const normalizedWrong = value.wrongQuestions
            .filter(item => item && typeof item === "object")
            .map(item => {
                const question = typeof item.question === "string"
                    ? sanitizeStoredWrongQuestionText(
                        item.question
                    )
                    : "";

                if (!question) return null;

                return {
                    id: typeof item.id === "string" && item.id
                        ? item.id
                        : `wrong-${Date.now()}-${Math.random()}`,
                    question: question.slice(0, 3000),
                    knowledgePoints: Array.isArray(item.knowledgePoints)
                        ? item.knowledgePoints
                            .filter(point => typeof point === "string" && point.trim())
                            .map(point => point.trim())
                            .slice(0, 4)
                        : [],
                    focusPoints: Array.isArray(item.focusPoints)
                        ? item.focusPoints
                            .filter(point => typeof point === "string" && point.trim())
                            .map(point => point.trim())
                            .slice(0, 2)
                        : [],
                    category: typeof item.category === "string"
                        ? item.category.trim()
                        : "",
                    difficulty: ["简单", "中等", "困难"].includes(item.difficulty)
                        ? item.difficulty
                        : "",
                    feedback: typeof item.feedback === "string"
                        ? item.feedback.trim().slice(0, 1000)
                        : "",
                    referenceAnswer: typeof item.referenceAnswer === "string"
                        ? item.referenceAnswer.trim().slice(0, 1200)
                        : "",
                    answer: typeof item.answer === "string"
                        ? item.answer.trim().slice(0, 3000)
                        : "",
                    analysis: typeof item.analysis === "string"
                        ? item.analysis.trim().slice(0, 8000)
                        : (
                            typeof item.solution === "string"
                                ? item.solution.trim().slice(0, 8000)
                                : ""
                        ),
                    answerUpdatedAt: Number.isFinite(item.answerUpdatedAt)
                        ? item.answerUpdatedAt
                        : null,
                    analysisUpdatedAt: Number.isFinite(item.analysisUpdatedAt)
                        ? item.analysisUpdatedAt
                        : (
                            Number.isFinite(item.solutionUpdatedAt)
                                ? item.solutionUpdatedAt
                                : null
                        ),
                    note: typeof item.note === "string"
                        ? item.note.trim().slice(0, 1500)
                        : "",
                    source: item.source === "auto" ? "auto" : "manual",
                    corrected: Boolean(item.corrected),
                    mistakeCount: item.source === "auto"
                        ? Math.max(1, Number(item.mistakeCount) || 1)
                        : Math.max(0, Number(item.mistakeCount) || 0),
                    sessionId: (
                        typeof item.sessionId === "number"
                        || typeof item.sessionId === "string"
                    )
                        ? item.sessionId
                        : null,
                    createdAt: Number.isFinite(item.createdAt)
                        ? item.createdAt
                        : Date.now(),
                    updatedAt: Number.isFinite(item.updatedAt)
                        ? item.updatedAt
                        : Date.now(),
                    lastWrongAt: Number.isFinite(item.lastWrongAt)
                        ? item.lastWrongAt
                        : (
                            Number.isFinite(item.updatedAt)
                                ? item.updatedAt
                                : Date.now()
                        ),
                    correctedAt: Number.isFinite(item.correctedAt)
                        ? item.correctedAt
                        : null,
                    retestCount: Math.max(0, Number(item.retestCount) || 0),
                    retestPassCount: Math.max(0, Number(item.retestPassCount) || 0),
                    retestFailCount: Math.max(0, Number(item.retestFailCount) || 0),
                    retestPassed: Boolean(item.retestPassed),
                    retestPassedAt: Number.isFinite(item.retestPassedAt)
                        ? item.retestPassedAt
                        : null,
                    lastRetestAt: Number.isFinite(item.lastRetestAt)
                        ? item.lastRetestAt
                        : null,
                    lastRetestQuestion: typeof item.lastRetestQuestion === "string"
                        ? item.lastRetestQuestion.trim().slice(0, 3000)
                        : "",
                    lastRetestFeedback: typeof item.lastRetestFeedback === "string"
                        ? item.lastRetestFeedback.trim().slice(0, 1000)
                        : "",
                    lastRetestResult: ["correct", "wrong", "unknown"].includes(
                        item.lastRetestResult
                    )
                        ? item.lastRetestResult
                        : "",
                    lastRetestSessionId: (
                        typeof item.lastRetestSessionId === "number"
                        || typeof item.lastRetestSessionId === "string"
                    )
                        ? item.lastRetestSessionId
                        : null
                };
            })
            .filter(Boolean);

        // 错题本本身允许出现重复题目：每次记录都作为独立学习记录保留。
        // PDF 导出时会按题目内容单独去重，不影响这里的原始记录。
        state.wrongQuestions = normalizedWrong
            .filter(
                item => !isClearlyNonQuestionWrongBookText(
                    item.question
                )
            )
            .sort((a, b) => a.updatedAt - b.updatedAt)
            .slice(-MAX_WRONG_QUESTIONS);
    }

    state.knowledge = buildKnowledgeFromEvents(
        state.events
    );

    return state;
}

function loadLearningState() {
    try {
        const raw = localStorage.getItem(LEARNING_STORAGE_KEY);

        if (!raw) {
            learningState = createEmptyLearningState();
            return;
        }

        learningState = normalizeLearningState(
            JSON.parse(raw)
        );
    } catch (error) {
        console.warn("学习记录读取失败：", error);
        learningState = createEmptyLearningState();
    }
}

function saveLearningState() {
    try {
        localStorage.setItem(
            LEARNING_STORAGE_KEY,
            JSON.stringify(learningState)
        );
    } catch (error) {
        console.warn("学习记录保存失败：", error);
    }
    scheduleCloudSync();
}

function emptyKnowledgeRecord() {
    return {
        seen: 0,
        correct: 0,
        wrong: 0,
        support: 0,
        reviewed: 0,
        updatedAt: 0
    };
}

function buildKnowledgeFromEvents(events) {
    const knowledge = {};

    for (const event of Array.isArray(events) ? events : []) {
        if (
            !event
            || !Array.isArray(event.points)
            || !event.type
        ) {
            continue;
        }

        for (const rawPoint of event.points) {
            const point = String(rawPoint || "").trim();
            if (!point) continue;

            if (!knowledge[point]) {
                knowledge[point] = emptyKnowledgeRecord();
            }

            const record = knowledge[point];

            if (event.type === "seen") record.seen += 1;
            if (event.type === "correct") record.correct += 1;
            if (event.type === "wrong") record.wrong += 1;
            if (event.type === "support") record.support += 1;
            if (event.type === "reviewed") record.reviewed += 1;

            record.updatedAt = Math.max(
                record.updatedAt,
                Number(event.createdAt) || 0
            );
        }
    }

    return knowledge;
}

function rebuildKnowledge() {
    learningState.knowledge = buildKnowledgeFromEvents(
        learningState.events
    );
}

function updateKnowledge(points, eventType, sessionId = null) {
    const uniquePoints = [
        ...new Set(
            (Array.isArray(points) ? points : [])
                .filter(point => typeof point === "string" && point.trim())
                .map(point => point.trim())
        )
    ].slice(0, 4);

    if (
        !uniquePoints.length
        || ![
            "seen",
            "correct",
            "wrong",
            "support",
            "reviewed"
        ].includes(eventType)
    ) {
        return;
    }

    const now = Date.now();

    learningState.events.push({
        id: `learn-${now}-${Math.random().toString(36).slice(2, 8)}`,
        sessionId: (
            typeof sessionId === "number"
            || typeof sessionId === "string"
        )
            ? sessionId
            : null,
        type: eventType,
        points: uniquePoints,
        createdAt: now
    });

    if (learningState.events.length > 1000) {
        learningState.events = learningState.events.slice(-1000);
    }

    rebuildKnowledge();
    saveLearningState();
}

function removeLearningEventsForSession(sessionId) {
    if (
        sessionId === null
        || sessionId === undefined
    ) {
        return;
    }

    const before = learningState.events.length;

    learningState.events = learningState.events.filter(
        event => String(event.sessionId) !== String(sessionId)
    );

    if (learningState.events.length !== before) {
        rebuildKnowledge();
        saveLearningState();
    }
}

function knowledgeStatus(record) {
    if (!record || typeof record !== "object") {
        return "暂无记录";
    }

    const correct = Number(record.correct) || 0;
    const wrong = Number(record.wrong) || 0;
    const seen = Number(record.seen) || 0;
    const reviewed = Number(record.reviewed) || 0;

    if (!correct && !wrong && !seen && !reviewed) {
        return "暂无记录";
    }

    if (wrong > 0) {
        return "有错误记录";
    }

    if (correct > 0) {
        return "已有正确记录";
    }

    if (reviewed > 0) {
        return "完成过订正";
    }

    return "有学习记录";
}


function getLatestUserMessage(session) {
    if (!session || !Array.isArray(session.messages)) {
        return null;
    }

    for (let index = session.messages.length - 1; index >= 0; index -= 1) {
        const message = session.messages[index];

        if (
            message
            && message.role === "user"
            && typeof message.text === "string"
            && message.text.trim()
        ) {
            return message;
        }
    }

    return null;
}

function normalizeQuestionReferenceText(text) {
    return String(text || "")
        .trim()
        .replace(/\s+/g, "");
}

function hasExplicitExerciseGenerationCue(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 140) {
        return false;
    }

    // 明确拒绝出题。
    if (
        /(?:不想(?:让你)?|不要|别|不用|无需|禁止|先别|暂时别|以后别|别再|不要再)(?:给我|帮我)?(?:再)?(?:出|生成|来|给|整|弄|安排|准备|考我|刷).{0,10}(?:题目|题|练习)?/.test(value)
    ) {
        return false;
    }

    // 出题功能/代码/识别等元讨论，不属于生成命令。
    if (
        /(?:讨论|解释|分析|研究|功能|bug|代码|逻辑|识别|接口|模式|机制).{0,14}(?:出题|生成题|题目生成|生成练习)|(?:出题|生成题|题目生成|生成练习).{0,14}(?:功能|bug|代码|逻辑|识别|接口|模式|机制)/i.test(value)
    ) {
        return false;
    }

    // “刚才太难了，再来个简单的”是明确的新动作。
    if (
        /(?:^|[，,。；;！!？?])(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:换|来|出|给|整|弄)(?:个|道|一道|一个)?(?:简单|基础|入门|容易|轻松|中等|适中|普通|一般|困难|高难|难|挑战|复杂)(?:难度)?(?:点|一点|一些|点儿|的)?(?:题|练习)?(?:吧)?$/.test(value)
    ) {
        return true;
    }

    // 单纯评价上一道生成题，不生成新题。
    if (
        /(?:刚才|之前|上次|前面|你刚).{0,14}(?:出(?:的)?|生成(?:的)?|给(?:我)?(?:的)?).{0,8}(?:题目|题|练习)/.test(value)
        || /^(?:为什么|怎么|如何).{0,40}(?:出(?:的)?|生成(?:的)?|给(?:我)?).{0,10}(?:题目|题|练习)/.test(value)
    ) {
        return false;
    }

    if (/^(?:请|麻烦)?(?:来)?考我(?:一下|下|几道?|一题|一道)?(?:吧)?$/.test(value)) {
        return true;
    }

    if (/^(?:请|麻烦)?(?:陪我|让我|我想|想)?刷(?:几|一|两|二|\d+)?道?(?:题)?(?:吧)?$/.test(value)) {
        return true;
    }

    if (
        /^(?:请|麻烦)?(?:给我|帮我)?(?:随机|随便|再|重新)?(?:来|出|整|弄)?(?:一个|一道|一题)(?:题)?(?:吧)?$/.test(value)
    ) {
        return true;
    }

    if (
        /^(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:换|来|出|给|整|弄)(?:个|道|一道|一个)?(?:简单|基础|入门|容易|轻松|中等|适中|普通|一般|困难|高难|难|挑战|复杂)(?:难度)?(?:点|一点|一些|点儿|的)?(?:题|练习)?(?:吧)?$/.test(value)
    ) {
        return true;
    }

    if (
        /^(?:我)?(?:想|想要|要)?(?:练|刷|考)(?:一下|点|些|几道?)?(?:谓词逻辑|命题逻辑|逻辑|数论|计数|组合|递推|图论|图|集合|关系|函数|代数|群|树|欧拉|哈密顿)(?:题|练习)?(?:吧)?$/.test(value)
    ) {
        return true;
    }

    if (
        /(?:请|麻烦|能否|能不能|可以|可不可以|帮我|给我|让我|我要|我想要|我想|想要|想|再|重新|随机|随便|继续|现在)?(?:给我|帮我)?(?:再|重新|随机|随便|继续)?(?:来|出(?!的)|生成(?!的)|安排|准备|整|弄|抽).{0,12}(?:题目|题|练习)/.test(value)
    ) {
        return true;
    }

    if (/(?:给我|帮我).{0,10}(?:一道|一题|一个题|几道题|几题|题目|练习)/.test(value)) {
        return true;
    }

    if (/(?:想|要|想要|可以|能不能|帮我|让我).{0,10}(?:做|练|刷|考).{0,16}(?:题目|题|练习)/.test(value)) {
        return true;
    }

    return /^(?:请|麻烦)?(?:给我|帮我)?(?:下一道题|下一题|下一个题|再来一道|再来一题|再来一个|换一道题|换一个题|换一道|换一题)(?:吧|。|！|!)?$/.test(value);
}



function parseQuestionReferenceNumber(raw) {
    const value = String(raw || "").trim();

    if (!value) return null;

    if (/^\d{1,3}$/.test(value)) {
        const number = Number(value);
        return Number.isInteger(number) && number >= 1
            ? number
            : null;
    }

    const normalized = value.replace(/两/g, "二");
    const digits = {
        零: 0,
        一: 1,
        二: 2,
        三: 3,
        四: 4,
        五: 5,
        六: 6,
        七: 7,
        八: 8,
        九: 9
    };

    if (Object.prototype.hasOwnProperty.call(digits, normalized)) {
        return digits[normalized] || null;
    }

    // 会话里的题目数量通常不会很大，这里稳定支持 1~99 的中文序号：
    // 十、十一、二十、二十三……
    if (/^[一二三四五六七八九]?十[一二三四五六七八九]?$/.test(normalized)) {
        const [left, right = ""] = normalized.split("十");
        const tens = left ? digits[left] : 1;
        const ones = right ? digits[right] : 0;
        const number = tens * 10 + ones;
        return number >= 1 ? number : null;
    }

    return null;
}

function questionOrdinalReference(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 90) {
        return null;
    }

    // “倒数第二题”必须走倒序题号逻辑；不能误抽成“第二题”。
    if (/倒数第[零一二三四五六七八九十两\d]{1,4}/.test(value)) {
        return null;
    }

    // 注意：这里故意不把“第2小题”当成会话历史第2题。
    // “第2小题 / 第2问”应继续留在当前大题内部，由模型回答当前题的小问。
    const match = value.match(
        /第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?/
    );

    if (!match) return null;

    return parseQuestionReferenceNumber(match[1]);
}

function questionReverseOrdinalReference(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 90) {
        return null;
    }

    const match = value.match(
        /倒数第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?/
    );

    if (!match) return null;

    return parseQuestionReferenceNumber(match[1]);
}

function questionBoundaryReference(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 90) {
        return "";
    }

    if (
        /(?:最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?/.test(value)
    ) {
        return "first";
    }

    if (
        /(?:最后|最末|最晚|最新)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?/.test(value)
    ) {
        return "last";
    }

    if (
        /(?:当前|现在|目前|正在讲|刚才|刚刚)(?:的)?(?:这|那|一)?(?:道|个)?(?:大|练习)?题(?:目)?/.test(value)
        || /^(?:这|那|本)(?:一)?(?:道|个)?(?:大)?题(?:目)?(?:呢|吗|啊|呀|吧|不(?:太|怎么)?会|不会|怎么做|如何做|再讲一下|讲一下|继续|提示一下)?$/.test(value)
    ) {
        return "current";
    }

    return "";
}

function parseRelativeQuestionOffset(value) {
    const text = normalizeQuestionReferenceText(value);
    if (!text) return null;

    // “最后一道题”里包含字面子串“后一道题”，必须先排除边界指代。
    if (
        /(?:最后|最末|最晚|最新|最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?/.test(text)
    ) {
        return null;
    }

    if (/(?:上上|前前)(?:一)?(?:道|个)?(?:大|练习)?题/.test(text)) {
        return -2;
    }

    if (/(?:下下|后后)(?:一)?(?:道|个)?(?:大|练习)?题/.test(text)) {
        return 2;
    }

    if (/(?:再|又)(?:往|向)?(?:上|前)(?:一)?(?:道|个)?(?:大|练习)?题/.test(text)) {
        return -2;
    }

    if (/(?:再|又)(?:往|向)?(?:下|后)(?:一)?(?:道|个)?(?:大|练习)?题/.test(text)) {
        return 2;
    }

    let match = text.match(
        /(?:往|向)(?:前|上)([零一二三四五六七八九十两\d]{1,4})(?:道|个)?(?:大|练习)?题/
    );
    if (match) {
        const steps = parseQuestionReferenceNumber(match[1]);
        return steps ? -steps : null;
    }

    match = text.match(
        /(?:往|向)(?:后|下)([零一二三四五六七八九十两\d]{1,4})(?:道|个)?(?:大|练习)?题/
    );
    if (match) {
        const steps = parseQuestionReferenceNumber(match[1]);
        return steps || null;
    }

    if (
        /(?:上一道(?:大|练习)?题|上一(?:大|练习)?题|上一个(?:大|练习)?题|前一道(?:大|练习)?题|前一(?:大|练习)?题|前一个(?:大|练习)?题|前面(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题|刚才上一道(?:大|练习)?题|刚才上一(?:大|练习)?题)/.test(text)
    ) {
        return -1;
    }

    if (
        /(?:下一道(?:大|练习)?题|下一(?:大|练习)?题|下一个(?:大|练习)?题|后一道(?:大|练习)?题|后一(?:大|练习)?题|后一个(?:大|练习)?题|后面(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题)/.test(text)
    ) {
        return 1;
    }

    return null;
}

function relativeQuestionReference(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 110) {
        return null;
    }

    // 当前大题内部的“第2小题 / 第2问”及其前后小问，不参与会话题目导航。
    if (/第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?小题|第[零一二三四五六七八九十两\d]{1,4}问/.test(value)) {
        return null;
    }

    const normalOrdinalPattern = /第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?/;
    const reverseOrdinalPattern = /倒数第([零一二三四五六七八九十两\d]{1,4})(?:个|道)?(?:大|练习|例|习)?题(?:目)?/;

    const reverseMatch = value.match(reverseOrdinalPattern);
    if (reverseMatch) {
        const anchorReverseOrdinal = parseQuestionReferenceNumber(
            reverseMatch[1]
        );
        const suffix = value.slice(
            (reverseMatch.index || 0) + reverseMatch[0].length
        );
        const offset = parseRelativeQuestionOffset(suffix);

        if (anchorReverseOrdinal && offset) {
            return {
                offset,
                anchorOrdinal: null,
                anchorReverseOrdinal,
                anchorBoundary: ""
            };
        }
    }

    const normalMatch = value.match(normalOrdinalPattern);
    if (normalMatch && !value.includes("倒数第")) {
        const anchorOrdinal = parseQuestionReferenceNumber(
            normalMatch[1]
        );
        const suffix = value.slice(
            (normalMatch.index || 0) + normalMatch[0].length
        );
        const offset = parseRelativeQuestionOffset(suffix);

        if (anchorOrdinal && offset) {
            return {
                offset,
                anchorOrdinal,
                anchorReverseOrdinal: null,
                anchorBoundary: ""
            };
        }
    }

    const boundaryAnchors = [
        ["first", /(?:最开始|最早|开头|起初)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?/],
        ["last", /(?:最后|最末|最晚|最新)(?:的)?(?:那|这|一)?(?:道|个)?(?:大|练习)?题(?:目)?/],
        ["current", /(?:当前|现在|目前|正在讲|刚才|刚刚)(?:的)?(?:这|那|一)?(?:道|个)?(?:大|练习)?题(?:目)?/]
    ];

    for (const [anchorBoundary, pattern] of boundaryAnchors) {
        const match = value.match(pattern);
        if (!match) continue;

        const suffix = value.slice(
            (match.index || 0) + match[0].length
        );
        const offset = parseRelativeQuestionOffset(suffix);

        if (offset) {
            return {
                offset,
                anchorOrdinal: null,
                anchorReverseOrdinal: null,
                anchorBoundary
            };
        }
    }

    const offset = parseRelativeQuestionOffset(value);
    if (!offset) return null;

    return {
        offset,
        anchorOrdinal: null,
        anchorReverseOrdinal: null,
        anchorBoundary: ""
    };
}

function isPreviousQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 100) {
        return false;
    }

    // “给我一道和上一题类似的题”是出题请求，不是切换当前题。
    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    const reference = relativeQuestionReference(value);
    return Boolean(reference && reference.offset < 0);
}

function isNextQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 100) {
        return false;
    }

    // “给我下一道题 / 出下一题”应继续走出题逻辑。
    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    const reference = relativeQuestionReference(value);
    return Boolean(reference && reference.offset > 0);
}

function isOrdinalQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);

    const ordinal = questionOrdinalReference(value);
    if (!ordinal || value.length > 90) return false;

    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    // “第2题：已知……”这种完整题干不是导航命令。
    const freshProblemAfterReference = /第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?(?:大|练习|例|习)?题(?:目)?[：:]?(?:已知|设|给定|若|求|证明|计算|判断|写出|列出)/.test(
        value
    );

    if (freshProblemAfterReference) {
        return false;
    }

    // “第2题的下一题”属于相对导航，由 relativeQuestionReference 处理。
    if (relativeQuestionReference(value)) {
        return false;
    }

    if (
        /(?:还记得|回到|返回|切到|跳到|再讲|讲一下|解释|提示|不(?:太|怎么)?会|不会|有点不会|做不来|没思路|没头绪|卡住|不懂|没懂|还是不会|继续|完整解析|答案|怎么做|如何做|看一下)/.test(
            value
        )
    ) {
        return true;
    }

    return /^第[零一二三四五六七八九十两\d]{1,4}(?:个|道)?(?:大|练习|例|习)?题(?:目)?(?:呢|吗|啊|呀|吧)?$/.test(
        value
    );
}

function isReverseOrdinalQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);
    const ordinal = questionReverseOrdinalReference(value);

    if (!ordinal || value.length > 90) {
        return false;
    }

    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    return true;
}

function isBoundaryQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!questionBoundaryReference(value)) {
        return false;
    }

    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    return true;
}

function namedQuestionTopicReference(text) {
    const value = normalizeQuestionReferenceText(text);

    if (!value || value.length > 100) {
        return "";
    }

    // 优先保留更精确的课程模块名称，避免“谓词逻辑那道题”被降成笼统的“逻辑”。
    const preciseTopics = [
        ["谓词逻辑", /谓词逻辑|谓词|量词|个体域|辖域|前束范式/],
        ["命题逻辑", /命题逻辑|命题|真值表|逻辑联结词|主析取|主合取|范式/],
        ["证明与归纳", /证明与归纳|数学归纳|强归纳|反证法|反证|直接证明/],
        ["初等数论", /初等数论|数论|整除|素数|质数|同余|最大公(?:约|因)数|欧几里得/],
        ["计数与组合", /计数与组合|组合|排列|鸽巢|容斥|计数/],
        ["递推关系", /递推关系|递推|递归|生成函数/],
        ["图论", /图论|图.{0,12}同构|同构.{0,12}图|邻接矩阵|欧拉(?:图|通路|回路)|哈密顿|最短路|生成树|顶点|边/],
        ["代数结构", /代数结构|群|子群|半群|幺半群|同态|同构|环|域|格|布尔代数/],
        ["函数", /函数|映射|单射|满射|双射|逆函数|复合函数/],
        ["集合与关系", /集合与关系/],
        ["关系", /二元关系|关系|偏序|等价关系|关系闭包|哈斯图|自反|对称|传递/],
        ["集合", /集合|子集|幂集|交集|并集|补集/]
    ];

    const hasReferenceCue = /(?:那|这)(?:一)?(?:道|个)?(?:大|练习)?题|(?:刚才|之前|前面|上面)(?:的)?[^，。！？!?]{0,24}题|[^，。！？!?]{1,24}(?:的)?那(?:一)?(?:道|个)?(?:大|练习)?题/.test(
        value
    );

    if (hasReferenceCue) {
        const matched = preciseTopics.find(([, pattern]) => pattern.test(value));
        if (matched) {
            return matched[0];
        }
    }

    const match = value.match(
        /(?:还记得|回到|返回|切到|跳到|刚才|之前|前面|上面)?(?:关于)?(.{1,24}?)(?:的)?(?:那|这)(?:一)?(?:道|个)?(?:大|练习)?题(?:目)?(?:呢|吗|吧|啊|呀|再讲一下|讲一下|不(?:太|怎么)?会|不会|有点不会|做不来|没思路|不懂|没懂|还是不会|怎么做|如何做)?$/
    );

    if (!match) return "";

    return String(match[1] || "")
        .replace(/^(?:关于|刚才|之前|前面|上面)/, "")
        .replace(/(?:相关|方面)$/, "")
        .trim();
}

function isNamedQuestionFollowUp(text) {
    const value = normalizeQuestionReferenceText(text);

    if (hasExplicitExerciseGenerationCue(value)) {
        return false;
    }

    return Boolean(namedQuestionTopicReference(value));
}

function isQuestionNavigationFollowUp(text) {
    return (
        isPreviousQuestionFollowUp(text)
        || isNextQuestionFollowUp(text)
        || isOrdinalQuestionFollowUp(text)
        || isReverseOrdinalQuestionFollowUp(text)
        || isBoundaryQuestionFollowUp(text)
        || isNamedQuestionFollowUp(text)
    );
}

function isShortLearningFollowUp(text) {
    const value = String(text || "")
        .trim()
        .replace(/\s+/g, "");

    if (!value) return true;

    if (isQuestionNavigationFollowUp(value)) {
        return true;
    }

    const exactCommands = [
        "继续",
        "再提示一下",
        "再给个提示",
        "给我提示",
        "完整解析",
        "给我完整解析",
        "直接给答案",
        "告诉我答案",
        "为什么",
        "然后呢",
        "下一步呢",
        "再讲一下",
        "再解释一下",
        "换个写法",
        "换一种写法",
        "列一下",
        "写一下",
        "展开一下",
        "用大括号列一下",
        "用大括号写一下",
        "用矩阵写一下",
        "这个怎么看",
        "这个怎么写",
        "这一步怎么写"
    ];

    if (exactCommands.includes(value)) {
        return true;
    }

    // 这类短句通常是在追问“怎么表示/怎么改写”，不是一道新题。
    const followUpPatterns = [
        /用.+(?:列|写|表示|展开)一下$/,
        /(?:再|重新).+(?:讲|写|列|解释|说明)一下$/,
        /(?:换|改).+(?:写法|表示|形式)$/,
        /^(?:这个|这里|这一步|上面|刚才).{0,12}(?:怎么|为什么|什么意思|看不懂|不明白|不(?:太|怎么)?会|不会|没思路|卡住)/,
        /(?:怎么写|怎么表示|怎么列|什么意思|看不懂|不明白|不(?:太|怎么)?会|不会|没思路|没头绪|卡住)$/
    ];

    if (
        value.length <= 30
        && followUpPatterns.some(pattern => pattern.test(value))
    ) {
        return true;
    }

    return value.length <= 6;
}

function extractOcrPrintedQuestionText(text) {
    const value = String(text || "").trim();
    if (!value) return "";

    const markers = [
        "【题目文字】",
        "【题干与公式识别】"
    ];
    const marker = markers.find(item => value.includes(item));
    if (!marker) return "";

    const start = value.indexOf(marker) + marker.length;
    const endMarkers = [
        "【图形信息】",
        "【图形结构识别】",
        "【我的要求】"
    ];
    const ends = endMarkers
        .map(item => value.indexOf(item, start))
        .filter(index => index >= 0);
    const end = ends.length ? Math.min(...ends) : value.length;

    return cutQuestionAfterMetaSections(
        value.slice(start, end)
    ).trim();
}

function extractOcrUserRequest(text) {
    const value = String(text || "");
    if (!value) return "";

    const apiMatch = value.match(
        /【本轮唯一需要执行的用户请求】\s*([\s\S]*?)\s*【本轮请求结束】/
    );
    if (apiMatch) {
        return String(apiMatch[1] || "").trim();
    }

    const marker = "【我的要求】";
    const start = value.indexOf(marker);
    return start >= 0
        ? value.slice(start + marker.length).trim()
        : "";
}

function looksLikeFormalPureImageRequest(text) {
    const value = String(text || "").replace(/\s+/g, "").trim();
    if (!value) return false;

    // 观察型临时询问只回答，不登记为题目。
    if (
        /(?:这里|这个|图里|图中|里面|这张图).{0,10}(?:有)?(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)/.test(value)
        || /(?:多少|几个|几条)(?:个)?(?:点|顶点|节点|边|线)/.test(value)
        || /^(?:这|这个|这里|图里|图中|里面).{0,12}(?:是什么|什么意思|怎么看|怎么读)$/.test(value)
    ) {
        return false;
    }

    if (
        /^(?:请|麻烦|帮我|帮忙)?(?:看一下|看看|帮我看下)?(?:判断(?:一下)?|判定|证明|求证|求解|计算|算(?:一下)?|求(?:一下|出)?|写出|写一下|列出|列一下|找出|找一下|给出|构造|画出|画一下|作出|确定|说明)/.test(value)
    ) {
        return true;
    }

    return Boolean(
        /(?:是否|是不是).{0,12}(?:同构|连通|欧拉图|哈密顿图|树|平面图|二分图)/.test(value)
        || /(?:同不同构|同构吗|是否同构|是否连通|欧拉(?:通路|回路|图)|哈密顿(?:通路|回路|图)|最短(?:路|路径)|最小生成树|生成树|邻接矩阵|关联矩阵|度数序列|割点|割边|桥|着色|色数)/.test(value)
    );
}



function isRecordableOcrQuestionMessage(message) {
    if (
        !message
        || message.source !== "ocr"
        || typeof message.text !== "string"
    ) {
        return false;
    }

    const printed = extractOcrPrintedQuestionText(message.text);
    if (printed) {
        return Boolean(
            looksLikeChatQuestionText(printed)
            || countTopLevelQuestionParts(printed) >= 1
            || /^(?:图中|图\s*[A-Za-z0-9_]*|在图.+中).*(?:求|判断|证明|计算|写出|列出|多少|几个|是否)/.test(printed)
        );
    }

    // OCR 没有题干时，只有“纯图 + 明确解题要求”才登记成题。
    // “这里有几个点”之类临时观察问题不登记。
    return looksLikeFormalPureImageRequest(
        extractOcrUserRequest(message.text)
    );
}


function looksLikeActualLearningProblem(message) {
    if (
        !message
        || typeof message.text !== "string"
    ) {
        return false;
    }

    if (message.source === "ocr") {
        return isRecordableOcrQuestionMessage(message);
    }

    // 出题命令只是控制动作，不是学生提交的一道题。
    if (isExerciseRequestText(message.text)) {
        return false;
    }

    const text = message.text.trim();
    if (!text || isShortLearningFollowUp(text)) {
        return false;
    }

    const compact = text.replace(/\s+/g, "");

    // 明显的题目结构或题干用语。
    const problemSignals = [
        "【题目文字】",
        "【图形信息】",
        "[图片识题]",
        "已知",
        "设",
        "求",
        "求解",
        "证明",
        "判断",
        "计算",
        "写出",
        "列出",
        "回答下列问题",
        "选择题",
        "证明题",
        "计算题"
    ];

    if (
        problemSignals.some(signal => compact.includes(signal))
    ) {
        return true;
    }

    if (/[（(]\s*[1-9]\s*[)）]/.test(text)) {
        return true;
    }

    // 一般完整题目会比“换个写法/再提示一下”长很多。
    if (text.length >= 80) {
        return true;
    }

    return false;
}

function buildLearningQuestionFromSession(session, teaching, excludeLatest = false) {
    if (!session || !Array.isArray(session.messages)) {
        return null;
    }

    const end = excludeLatest
        ? session.messages.length - 2
        : session.messages.length - 1;

    for (let index = end; index >= 0; index -= 1) {
        const message = session.messages[index];

        if (
            !message
            || message.role !== "user"
            || typeof message.text !== "string"
        ) {
            continue;
        }

        const text = message.text.trim();
        if (!text) continue;

        if (message.isRetestPrompt || message.isRetestAnswer) {
            continue;
        }

        if (!looksLikeActualLearningProblem(message)) {
            continue;
        }

        const questionText = extractQuestionOnlyFromMessage(message).trim();
        if (!questionText) continue;

        return {
            text: questionText.slice(0, 3000),
            knowledgePoints: Array.isArray(teaching?.knowledge_points)
                ? teaching.knowledge_points.slice(0, 4)
                : [],
            focusPoints: Array.isArray(teaching?.focus_points)
                ? teaching.focus_points.slice(0, 2)
                : [],
            category: typeof teaching?.category === "string"
                ? teaching.category
                : "",
            difficulty: ["简单", "中等", "困难"].includes(teaching?.difficulty)
                ? teaching.difficulty
                : "",
            source: message.source === "ocr" ? "ocr" : "text",
            sessionId: session.id,
            updatedAt: Date.now()
        };
    }

    return null;
}

function stripQuestionDecorations(text) {
    let value = String(text || "");

    value = value
        .replace(
            /^\s*(?:\*\*|__)\s*【(?:题目|练习题|题目文字)】\s*(?:\*\*|__)\s*/m,
            ""
        )
        .replace(/^\s*【(?:题目|练习题|题目文字)】\s*/m, "")
        .replace(
            /^\s*(?:#{1,4}\s*)?(?:题目|练习题)\s*[:：]?\s*$/m,
            ""
        );

    // 删除标题切割后残留的单独 Markdown 装饰行。
    value = value
        .replace(
            /^(?:\s*(?:\*\*|__|[-—_=]{3,})\s*\n)+/,
            ""
        )
        .replace(
            /(?:\n\s*(?:\*\*|__|[-—_=]{3,})\s*)+$/,
            ""
        );

    return value.trim();
}

function cutQuestionAfterMetaSections(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    const stopPatterns = [
        /(?:^|\n)\s*(?:-{3,}\s*\n\s*)?(?:\*\*|__)?(?:提示|思考提示|思路提示|解题提示|小提示|关键提示|方法提示|解题思路|思路)\s*[:：]?(?:\*\*|__)?/im,
        /(?:^|\n)\s*(?:#{1,6}\s*)?(?:参考答案|答案|解析|解答|详细解析|解题过程|过程)\s*[:：]?/im,
        /(?:^|\n)\s*答\s*[:：]/im,
        /(?:^|\n)\s*(?:你先|请先|先尝试|可以先|做完后|卡住了|如果卡住|有结果后|把答案发给我|告诉我你的进度).{0,220}$/im
    ];

    let end = value.length;

    for (const pattern of stopPatterns) {
        const match = pattern.exec(value);

        if (
            match
            && typeof match.index === "number"
        ) {
            end = Math.min(end, match.index);
        }
    }

    return value
        .slice(0, end)
        .replace(/\n\s*[-—_=]{3,}\s*$/g, "")
        .trim();
}

function removeConversationalQuestionPrefix(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    // 明确题目标题后的内容优先。
    const explicitPatterns = [
        // 先吃掉完整 **【题目】**，否则只匹配中间标题会留下孤立 **。
        /(?:^|\n)\s*(?:\*\*|__)\s*【(?:题目|练习题)】\s*(?:\*\*|__)\s*/m,
        /【(?:题目|练习题)】/,
        /(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)/m,
        /(?:^|\n)\s*(?:\*\*|__)\s*(?:题目|练习题)[:：]?\s*(?:\*\*|__)\s*/m,
        /(?:^|\n)\s*(?:题目|练习题)\s*[:：]\s*/m,
        /(?:^|\n)\s*(?:题目|练习题)\s*(?:\n|$)/m
    ];

    let best = null;

    for (const pattern of explicitPatterns) {
        const match = pattern.exec(value);

        if (
            match
            && (
                !best
                || match.index < best.index
            )
        ) {
            best = match;
        }
    }

    if (best) {
        return value
            .slice(best.index + best[0].length)
            .trim();
    }

    // AI 常见开场白：真正题干通常从“设/已知/给定/下列/在……中”开始。
    const startPatterns = [
        /(?:^|\n)\s*(?=设)/m,
        /(?:^|\n)\s*(?=已知)/m,
        /(?:^|\n)\s*(?=给定)/m,
        /(?:^|\n)\s*(?=下列)/m,
        /(?:^|\n)\s*(?=在.{0,50}(?:图|集合|关系|系统|空间|序列|网络|情形)中)/m,
        /(?:^|\n)\s*(?=求(?:解|证|出|下列|$))/m,
        /(?:^|\n)\s*(?=证明)/m,
        /(?:^|\n)\s*(?=计算)/m,
        /(?:^|\n)\s*(?=判断)/m
    ];

    let start = -1;

    for (const pattern of startPatterns) {
        const match = pattern.exec(value);

        if (
            match
            && (
                start < 0
                || match.index < start
            )
        ) {
            start = match.index;
        }
    }

    if (start > 0) {
        const prefix = value.slice(0, start).trim();

        // 只在前缀明显是聊天套话时切掉，避免误删题干前言。
        if (
            /(?:好的|没问题|可以|这次|给你|我来|我们来|先来|出一道|练习一下|下面是)/.test(prefix)
            && prefix.length <= 160
        ) {
            value = value.slice(start).trim();
        }
    }

    return value;
}

function extractOcrQuestionPayload(text) {
    const value = String(text || "").trim();

    if (!value) return "";

    const questionMarker = "【题目文字】";
    const graphMarker = "【图形信息】";
    const requestMarker = "【我的要求】";

    if (!value.includes(questionMarker)) {
        return cutQuestionAfterMetaSections(value);
    }

    const qStart = value.indexOf(questionMarker) + questionMarker.length;
    const gStart = value.indexOf(graphMarker);
    const rStart = value.indexOf(requestMarker);
    const qEndCandidates = [gStart, rStart].filter(index => index >= 0);
    const qEnd = qEndCandidates.length
        ? Math.min(...qEndCandidates)
        : value.length;

    let question = value.slice(
        qStart,
        qEnd
    ).trim();

    question = cutQuestionAfterMetaSections(question);

    if (gStart >= 0) {
        const graphEnd = (rStart >= 0 && rStart > gStart)
            ? rStart
            : value.length;
        const graphInfo = value
            .slice(gStart + graphMarker.length, graphEnd)
            .trim();

        // 图形结构是题目必要条件，不属于“无关聊天内容”；
        // “我的要求”是本轮操作指令，不能混进题干或错题本。
        if (graphInfo) {
            question = `${question}\n\n【图形信息】\n${graphInfo}`.trim();
        }
    }

    return question;
}

function countTopLevelQuestionParts(text) {
    const value = String(text || "");

    const parenthesized = (
        value.match(
            /(?:^|\n)\s*[（(]\s*\d{1,2}\s*[)）]\s*\S+/gm
        ) || []
    ).length;

    const numbered = (
        value.match(
            /(?:^|\n)\s*\d{1,2}\s*[、.．]\s*\S+/gm
        ) || []
    ).length;

    return Math.max(parenthesized, numbered);
}

function looksLikeQuestionPayload(text) {
    const value = String(text || "").trim();

    if (!value) return false;

    if (/【(?:题目|练习题|题目文字)】/.test(value)) {
        return true;
    }

    if (/[？?]/.test(value)) {
        return true;
    }

    if (countTopLevelQuestionParts(value) >= 1) {
        return true;
    }

    const compact = value
        .replace(/^[#>*\s]+/, "")
        .trim();

    const starts = [
        "设",
        "已知",
        "给定",
        "求",
        "证明",
        "计算",
        "判断",
        "写出",
        "列出",
        "选择",
        "填空",
        "解答",
        "下列",
        "若",
        "问",
        "什么是",
        "为什么",
        "为何",
        "如何",
        "怎样"
    ];

    if (
        starts.some(item => compact.startsWith(item))
        && compact.length >= 4
    ) {
        return true;
    }

    if (
        /(?:多少|是否|哪个|哪些|为何|为什么|如何|怎样|求出|求证|求值|求解)/.test(compact)
        && compact.length >= 6
    ) {
        return true;
    }

    return false;
}

function isConversationControlOnly(text) {
    const value = String(text || "")
        .trim()
        .replace(/\s+/g, "");

    if (!value) return true;

    if (isQuestionNavigationFollowUp(value)) {
        return true;
    }

    const exact = [
        "不会做",
        "不会",
        "不知道",
        "继续",
        "下一步",
        "下一步呢",
        "然后呢",
        "好的",
        "好",
        "谢谢",
        "懂了",
        "再提示一下",
        "给我提示",
        "完整解析",
        "给我完整解析",
        "直接给答案",
        "告诉我答案",
        "出一道题",
        "给我出一道题",
        "再来一道"
    ];

    if (exact.includes(value)) {
        return true;
    }

    return Boolean(
        value.length <= 36
        && (
            isExerciseRequestText(value)
            || /^(?:帮我|给我|请|再)?(?:讲一下|解释一下|继续讲|看一下|检查一下|提示一下)/.test(value)
        )
    );
}

function extractAiQuestionPayload(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    value = removeConversationalQuestionPrefix(value);
    value = cutQuestionAfterMetaSections(value);
    value = stripQuestionDecorations(value);

    return value.trim();
}

function extractQuestionReviewPayload(text) {
    const source = String(text || "").trim();

    if (!source) return "";

    const marker = "【题目回顾】";
    const markerIndex = source.indexOf(marker);

    if (markerIndex < 0) {
        return source;
    }

    let value = source
        .slice(markerIndex + marker.length)
        .trim();

    // “题目回顾”之后的分步讲解绝不能进入错题本。
    // 只保留回顾里的原始题干，遇到第一步/开始讲解就截断。
    const stopPatterns = [
        /(?:^|\n)\s*(?:[-—_=]{3,}\s*\n\s*)?(?:#{1,6}\s*)?第\s*(?:[一二三四五六七八九十]+|\d+)\s*步\s*[:：]?/m,
        /(?:^|\n)\s*(?:[-—_=]{3,}\s*\n\s*)?(?:#{1,6}\s*)?(?:开始讲解|下面开始讲解|解题过程|详细讲解)\s*[:：]?/m
    ];

    let end = value.length;

    for (const pattern of stopPatterns) {
        const match = pattern.exec(value);
        if (match && match.index < end) {
            end = match.index;
        }
    }

    return value
        .slice(0, end)
        .replace(/(?:\n\s*[-—_=]{3,}\s*)+$/, "")
        .trim();
}

function sanitizeStoredWrongQuestionText(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    if (value.includes("【题目回顾】")) {
        value = extractQuestionReviewPayload(value);
    }

    if (value.includes("【题目文字】")) {
        value = extractOcrQuestionPayload(value);
    } else {
        value = removeConversationalQuestionPrefix(value);
        value = cutQuestionAfterMetaSections(value);
        value = stripQuestionDecorations(value);

        // 第二遍是刻意的：标题/Markdown 装饰被去掉后，
        // 原先被遮住的“思路提示/答案/解析”标题也必须继续截掉。
        value = cutQuestionAfterMetaSections(value);
        value = stripQuestionDecorations(value);
    }

    // 旧版可能把一整段纯讲解存进错题本；明确无题干时直接丢弃。
    if (
        isClearlyNonQuestionWrongBookText(value)
        && !looksLikeQuestionPayload(value)
    ) {
        return "";
    }

    return value.slice(0, 3000).trim();
}

function extractQuestionOnlyFromMessage(message) {
    if (
        !message
        || typeof message.text !== "string"
    ) {
        return "";
    }

    if (message.role === "user") {
        if (message.source === "ocr") {
            return extractOcrQuestionPayload(
                message.text
            );
        }

        return cutQuestionAfterMetaSections(
            message.text
        );
    }

    if (message.role === "ai") {
        const generated = String(
            message.generatedQuestion || ""
        ).trim();

        if (generated) {
            return sanitizeStoredWrongQuestionText(
                generated
            );
        }

        return extractAiQuestionPayload(
            message.text
        );
    }

    return "";
}

function hasExplicitQuestionHeading(text) {
    const value = String(text || "");

    return Boolean(
        /【(?:题目|练习题)】/.test(value)
        || /(?:^|\n)\s*(?:题目|练习题)\s*[:：]?\s*(?:\n|$)/m.test(value)
        || /(?:^|\n)\s*#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)/m.test(value)
        || /(?:^|\n)\s*\*\*(?:题目|练习题)[:：]?\*\*/m.test(value)
    );
}

function looksLikeStandaloneAiQuestion(text) {
    const value = String(text || "").trim();

    if (
        !value
        || isClearlyNonQuestionWrongBookText(value)
    ) {
        return false;
    }

    const question = sanitizeStoredWrongQuestionText(
        extractAiQuestionPayload(value)
    );

    if (!question) {
        return false;
    }

    if (hasExplicitQuestionHeading(value)) {
        return looksLikeQuestionPayload(question);
    }

    // 没有“题目”标题时：
    // 多小问综合题可以认；单题则必须从明确题干开头起步。
    if (countTopLevelQuestionParts(question) >= 2) {
        return looksLikeQuestionPayload(question);
    }

    const compact = question
        .replace(/^[#>*\s]+/, "")
        .trim();

    return Boolean(
        /^(?:设|已知|给定|下列|求|证明|计算|判断|写出|列出|选择|填空)/.test(compact)
        && looksLikeQuestionPayload(question)
    );
}


function shouldOfferWrongBookAction(
    message,
    session = null,
    messageIndex = -1
) {
    if (
        !message
        || message.isError
        || message.isNotice
        || typeof message.text !== "string"
        || !message.text.trim()
    ) {
        return false;
    }

    if (message.role === "user") {
        if (message.isRetestAnswer) {
            return false;
        }

        // “出一道题 / 随便来一道 / 给我个困难题”等是命令，
        // 永远不能出现“记为错题”。
        if (isExerciseRequestText(message.text)) {
            return false;
        }

        if (message.source === "ocr") {
            return isRecordableOcrQuestionMessage(message);
        }

        if (isConversationControlOnly(message.text)) {
            return false;
        }

        const extracted = sanitizeStoredWrongQuestionText(
            extractQuestionOnlyFromMessage(message)
        );

        if (!extracted) {
            return false;
        }

        // 用户消息必须本身像一道完整学习题，不能因为“提到了集合/图论”
        // 就出现“记为错题”。例如“刚刚那道集合题还是不会”属于追问。
        return Boolean(
            looksLikeChatQuestionText(extracted)
            || looksLikeFormalStudyQuestionForHistory(
                extracted,
                message
            )
        );
    }

    if (message.role === "ai") {
        // 新版本 AI 出题使用强元数据。只要后端已经登记 generatedQuestion，
        // 就无条件允许加入错题本，不再让题型启发式有机会把真题挡掉。
        const trustedGenerated = sanitizeStoredWrongQuestionText(
            message.generatedQuestion || ""
        );

        if (trustedGenerated) {
            // generatedQuestion 本身就是强元数据。只要题干已经登记，
            // 就必须允许加入错题本；不再依赖 generatedExercise 布尔位。
            return true;
        }

        // 兼容旧记录：只有上一条用户明确要求出题时，才从 AI 回复恢复题干。
        const generated = recoverGeneratedQuestionFromAssistant(
            session,
            messageIndex,
            message
        );

        return Boolean(
            generated
            && looksLikeQuestionPayload(generated)
        );
    }

    return false;
}


function splitQuestionBankText(text) {
    const source = String(text || "").trim();

    if (!source) return [];

    const lines = source.split(/\r?\n/);
    const blocks = [];
    let current = null;

    const pushCurrent = () => {
        if (!current) return;

        const raw = current.lines
            .join("\n")
            .trim();

        if (!raw) {
            current = null;
            return;
        }

        const answerMatch = raw.match(
            /(?:^|\n)\s*答\s*[:：]\s*([^\n]*)/m
        );

        const referenceAnswer = answerMatch
            ? answerMatch[1].trim()
            : "";

        const question = raw
            .replace(
                /(?:^|\n)\s*答\s*[:：]\s*[^\n]*/m,
                ""
            )
            .trim();

        blocks.push({
            number: current.number,
            question,
            referenceAnswer
        });

        current = null;
    };

    for (const line of lines) {
        const match = line.match(
            /^\s*(\d{1,2})\s*[、.．]\s*(.*)$/
        );

        if (match) {
            pushCurrent();

            current = {
                number: match[1],
                lines: [
                    `${match[1]}、${match[2]}`
                ]
            };

            continue;
        }

        if (current) {
            current.lines.push(line);
        }
    }

    pushCurrent();

    if (blocks.length < 2) {
        return [];
    }

    const answerCount = blocks.filter(
        item => item.referenceAnswer
    ).length;

    const bankSignal = /题库答案|题库|选择或填空|练习答案|习题答案/.test(
        source
    );

    // 避免把“一个大题里的 1/2 两个小问”错误拆开：
    // 只有多个独立答案，或明显是题库且至少 3 题时才判为题组。
    const isQuestionBank = (
        answerCount >= 2
        || (
            bankSignal
            && blocks.length >= 3
        )
    );

    if (!isQuestionBank) {
        return [];
    }

    return blocks
        .filter(item => item.question)
        .slice(0, 30);
}

function isExerciseRequestText(text) {
    const value = normalizeQuestionReferenceText(text);

    if (
        !value
        || value.length > 140
        || /^(?:不要|别|不用|无需).{0,18}(?:出|生成|来|给).{0,8}(?:题目|题|练习)/.test(value)
    ) {
        return false;
    }

    return Boolean(
        hasExplicitExerciseGenerationCue(value)
        || /^(?:再来一个|再来一道|再来一题|再来个|再来一个题|换一道|换一题|换一道题|换一个题|换个题|换一个|下一题|下一道题|下一道|下一个题)$/.test(value)
    );
}

function exerciseTopicReference(text) {
    const value = String(text || "");
    const topics = [
        ["谓词逻辑", /谓词逻辑|谓词|量词|个体域|辖域|前束范式/],
        ["命题逻辑", /命题逻辑|命题|真值表|逻辑联结词|主析取|主合取|范式/],
        ["证明与归纳", /证明与归纳|数学归纳|强归纳|反证法|反证|直接证明/],
        ["初等数论", /初等数论|数论|整除|素数|质数|同余|最大公(?:约|因)数|欧几里得|RSA/],
        ["计数与组合", /计数与组合|组合|排列|鸽巢|容斥|计数/],
        ["递推关系", /递推关系|递推|递归|生成函数/],
        ["图论", /图论|图.{0,12}同构|同构.{0,12}图|邻接矩阵|欧拉(?:图|通路|回路)|哈密顿|最短路|生成树|顶点|边/],
        ["代数结构", /代数结构|半群|幺半群|子群|同态|同构|布尔代数|环|域|格/],
        ["函数", /函数|映射|单射|满射|双射|逆函数|复合函数/],
        ["关系", /二元关系|偏序|等价关系|关系闭包|哈斯图|自反|反自反|对称|反对称|传递/],
        ["集合", /集合|子集|幂集|交集|并集|补集/]
    ];
    return topics.find(([, pattern]) => pattern.test(value))?.[0] || "";
}

function hasExplicitExerciseReferenceCue(text) {
    const value = normalizeQuestionReferenceText(text);

    return Boolean(
        /(?:和|与|根据|基于|参考|按照|照着|仿照).{0,24}(?:第[零一二三四五六七八九十两\d]+题|倒数第|上一|下一|前一|后一|最后|最开始|最早)/.test(value)
        || /(?:第[零一二三四五六七八九十两\d]+题|倒数第[零一二三四五六七八九十两\d]+题|上一道题|上一题|下一道题|下一题|最后一道题|最后一题).{0,10}(?:的)?(?:同知识点|同类|同类型|类似|相似|复测)/.test(value)
    );
}

function isNextExerciseContinuationRequest(text) {
    const value = normalizeQuestionReferenceText(text);

    return /^(?:请|麻烦)?(?:给我|帮我)?(?:出|生成|来)?(?:下一道题|下一题|下一个题)$/.test(
        value
    );
}

function isContextualExerciseRequest(text) {
    if (!isExerciseRequestText(text)) return false;

    const value = normalizeQuestionReferenceText(text);

    const structural = structuralQuestionReference(value);

    if (structural && hasExplicitExerciseReferenceCue(value)) {
        return true;
    }

    if (namedQuestionTopicReference(value)) {
        return true;
    }

    const deicticQuestion = /(?:这|那)(?:一)?(?:道|个)?(?:大)?题(?:目)?|(?:刚才|之前|前面|上面)(?:的)?(?:这|那|一)?(?:道|个)?(?:大)?题(?:目)?/.test(
        value
    );

    if (deicticQuestion) {
        return true;
    }

    // 用户已经明确给出新主题/知识点时，直接按新主题出题，
    // 不因为“同知识点”这几个字就强行寻找旧题。
    if (exerciseTopicReference(value)) {
        return false;
    }

    if (/(?:同(?:样|一)?|相同)(?:的)?知识点|同类|同类型|类似|相似/.test(value)) {
        return true;
    }

    // “来个难的 / 再换个基础的 / 考我一下”没有点名新主题时，
    // 默认延续当前题目的知识点；“随机/随便”则保持真正随机。
    if (
        !/(?:随机|随便)/.test(value)
        && (
            /^(?:请|麻烦)?(?:给我|帮我)?(?:再|重新)?(?:换|来|出|给|整|弄)(?:个|道|一道|一个)?(?:简单|基础|入门|容易|轻松|中等|适中|普通|一般|困难|高难|难|挑战|复杂)(?:难度)?(?:点|一点|一些|点儿|的)?(?:题|练习)?(?:吧)?$/.test(value)
            || /^(?:请|麻烦)?(?:来)?考我(?:一下|下|几道?|一题|一道)?(?:吧)?$/.test(value)
        )
    ) {
        return true;
    }

    // “给我下一道题 / 出下一题 / 下一题”都属于继续当前练习序列；
    // 若是裸“下一题”且历史里确实存在后一道题，send() 会优先导航，不会走出题。
    if (
        isNextExerciseContinuationRequest(value)
        || /^(?:下一道)$/.test(value)
    ) {
        return true;
    }

    return /^(?:再来一个|再来一道|再来一题|再来个|再来一个题|换一道|换一题|换一道题|换一个题|换个题|换一个)$/.test(value);
}

function resolveExerciseReference(session, text) {
    if (!isContextualExerciseRequest(text)) return null;

    const value = normalizeQuestionReferenceText(text);
    const structural = structuralQuestionReference(value);

    if (structural && hasExplicitExerciseReferenceCue(value)) {
        return resolveStructuralQuestionCandidate(
            session,
            value
        );
    }

    const named = resolveNamedQuestionCandidate(session, value);
    if (named) {
        return named;
    }

    // “给我下一道题 / 出下一题 / 裸下一题”都以当前题作为继续练习的参照；
    // “下一题不太会/讲下一题”则属于导航，不会进入这个分支。
    if (
        isNextExerciseContinuationRequest(value)
        || /^(?:下一道)$/.test(value)
    ) {
        return activeQuestionCandidateFromHistory(session)
            || currentQuestionCandidateFromLearningState(session);
    }

    return activeQuestionCandidateFromHistory(session)
        || currentQuestionCandidateFromLearningState(session);
}

function extractAiGeneratedExerciseText(reply) {
    let text = String(reply || "").trim();

    if (!text) return "";

    const headingPatterns = [
        /【题目】/,
        /【练习题】/,
        /(?:^|\n)#{1,4}\s*(?:题目|练习题)\s*(?:\n|$)/m,
        /(?:^|\n)\*\*(?:题目|练习题)[:：]?\*\*\s*/m,
        /(?:^|\n)\s*(?:题目|练习题)\s*[:：]?\s*(?:\n|$)/m
    ];

    let bestIndex = -1;
    let bestLength = 0;

    for (const pattern of headingPatterns) {
        const match = pattern.exec(text);

        if (
            match
            && (
                bestIndex < 0
                || match.index < bestIndex
            )
        ) {
            bestIndex = match.index;
            bestLength = match[0].length;
        }
    }

    if (bestIndex >= 0) {
        text = text.slice(
            bestIndex + bestLength
        ).trim();
    }

    // 练习题回答通常在题目后附“提示”。错题本只保存题目正文。
    const hintMatch = text.match(
        /\n\s*(?:---+\s*\n\s*)?(?:\*\*)?(?:提示|思考提示|解题提示|小提示)[:：]?(?:\*\*)?/i
    );

    if (hintMatch && typeof hintMatch.index === "number") {
        text = text.slice(0, hintMatch.index).trim();
    }

    return text.slice(0, 3000);
}

function completeQuestionTextFromChatMessage(
    message,
    session = null,
    messageIndex = -1
) {
    if (
        !message
        || message.isError
        || message.isNotice
        || typeof message.text !== "string"
        || !message.text.trim()
    ) {
        return "";
    }

    // 纯指令、短追问、寒暄都不是“完整题目”。
    if (
        isExerciseRequestText(message.text)
        || isConversationControlOnly(message.text)
        || isShortLearningFollowUp(message.text)
    ) {
        return "";
    }

    let question = "";

    if (message.role === "ai") {
        // AI 消息严格收口：
        // 1) 后端登记的 generatedQuestion / 由“上一条明确出题请求”恢复出的题；
        // 2) 消息本身明确带【题目】/题目标题，并且提取后确实像完整题。
        // 普通讲解、寒暄、提到“当前题目/度序列”等都不能出现复制按钮。
        question = recoverGeneratedQuestionFromAssistant(
            session,
            messageIndex,
            message
        );

        if (!question && hasExplicitQuestionHeading(message.text)) {
            question = sanitizeStoredWrongQuestionText(
                extractAiQuestionPayload(message.text)
            );
        }

        if (!question) return "";

        return looksLikeQuestionPayload(question)
            ? question
            : "";
    }

    // 用户自己输入、粘贴或 OCR 得到的完整题目都允许复制。
    question = sanitizeStoredWrongQuestionText(
        extractQuestionOnlyFromMessage(message)
    );
    if (!question) return "";

    if (message.source === "ocr") {
        return isRecordableOcrQuestionMessage(message)
            ? question
            : "";
    }

    const complete = Boolean(
        looksLikeChatQuestionText(question)
        || looksLikeFormalStudyQuestionForHistory(question, message)
        || (
            hasExplicitQuestionHeading(message.text)
            && looksLikeQuestionPayload(question)
        )
    );

    return complete ? question : "";
}

function copyChatQuestionOnly(message, session, messageIndex) {
    const question = completeQuestionTextFromChatMessage(
        message,
        session,
        messageIndex
    );

    if (!question) return;

    const payload = {
        text: question,
        html: `<div class="ai-content">${markdownToHtml(
            prepareAiDisplayText(question)
        )}</div>`
    };

    writeRichClipboard(payload).then(ok => {
        if (ok) showCopyToast("题目已复制");
    });
}

function shouldShowChatCopyButton(message, session, messageIndex) {
    return Boolean(
        completeQuestionTextFromChatMessage(
            message,
            session,
            messageIndex
        )
    );
}

function recoverGeneratedQuestionFromAssistant(
    session,
    messageIndex,
    message
) {
    if (
        !message
        || message.role !== "ai"
        || typeof message.text !== "string"
    ) {
        return "";
    }

    let generated = sanitizeStoredWrongQuestionText(
        message.generatedQuestion || ""
    );

    if (generated) {
        return generated;
    }

    const previous = previousUserMessageBefore(
        session,
        messageIndex
    );

    if (
        !previous
        || !isExerciseRequestText(previous.text)
    ) {
        return "";
    }

    generated = sanitizeStoredWrongQuestionText(
        extractAiGeneratedExerciseText(message.text)
    );

    if (
        !generated
        || !looksLikeQuestionPayload(generated)
    ) {
        return "";
    }

    // 兼容旧记录 / 后端没有返回 generated_question 的情况。
    // 只在上一条用户消息明确要求“出题”时恢复，避免把普通讲解误判成题目。
    message.generatedExercise = true;
    message.generatedQuestion = generated;

    return generated;
}

function openWrongQuestionPicker(questionInfo, choices) {
    const modal = document.getElementById(
        "wrongQuestionPickerModal"
    );
    const list = document.getElementById(
        "wrongQuestionPickerList"
    );

    if (!modal || !list || !choices.length) {
        return false;
    }

    pendingWrongQuestionSelection = {
        questionInfo,
        choices
    };

    list.innerHTML = "";

    choices.forEach((choice, index) => {
        const label = document.createElement("label");
        label.className = "wrong-picker-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = String(index);

        const content = document.createElement("div");
        content.className = "wrong-picker-content";

        const title = document.createElement("div");
        title.className = "wrong-picker-title";
        title.textContent = `第 ${choice.number} 题`;

        const preview = document.createElement("div");
        preview.className = "wrong-picker-preview";
        preview.textContent = choice.question
            .replace(/\s+/g, " ")
            .slice(0, 180);

        content.appendChild(title);
        content.appendChild(preview);

        if (choice.referenceAnswer) {
            const answer = document.createElement("div");
            answer.className = "wrong-picker-answer";
            answer.textContent = `题库参考答案：${choice.referenceAnswer}`;
            content.appendChild(answer);
        }

        label.appendChild(checkbox);
        label.appendChild(content);
        list.appendChild(label);
    });

    modal.classList.remove("hidden");
    return true;
}

function closeWrongQuestionPicker() {
    const modal = document.getElementById(
        "wrongQuestionPickerModal"
    );

    if (modal) {
        modal.classList.add("hidden");
    }

    pendingWrongQuestionSelection = null;
}

function normalizeWrongSafeItem(questionInfo) {
    if (!questionInfo || typeof questionInfo !== "object") {
        return null;
    }

    const cleaned = sanitizeStoredWrongQuestionText(
        questionInfo.text
    ).trim();

    if (!cleaned) {
        return null;
    }

    return {
        ...questionInfo,
        text: cleaned
    };
}

function openWrongSafePreview(items) {
    const modal = document.getElementById(
        "wrongSafeModal"
    );

    if (!modal) {
        return false;
    }

    const sourceItems = Array.isArray(items)
        ? items
        : [items];

    pendingWrongSafeItems = sourceItems
        .map(normalizeWrongSafeItem)
        .filter(Boolean);

    pendingWrongSafeIndex = 0;

    if (!pendingWrongSafeItems.length) {
        window.alert(
            "没有提取到可保存的题目内容。"
        );
        return false;
    }

    modal.classList.remove("hidden");
    renderWrongSafePreview();
    return true;
}

function renderWrongSafePreview() {
    const modal = document.getElementById(
        "wrongSafeModal"
    );
    const textarea = document.getElementById(
        "wrongSafeQuestion"
    );
    const progress = document.getElementById(
        "wrongSafeProgress"
    );
    const source = document.getElementById(
        "wrongSafeSource"
    );
    const confirm = document.getElementById(
        "wrongSafeConfirm"
    );

    if (
        !modal
        || !textarea
        || !pendingWrongSafeItems.length
    ) {
        return;
    }

    const item = pendingWrongSafeItems[
        pendingWrongSafeIndex
    ];

    textarea.value = item.text;

    if (progress) {
        progress.textContent = (
            pendingWrongSafeItems.length > 1
                ? `第 ${pendingWrongSafeIndex + 1} / ${pendingWrongSafeItems.length} 道`
                : "请确认下面就是要保存的题目"
        );
    }

    if (source) {
        const sourceLabel = (
            item.source === "ai"
                ? "AI 生成题"
                : (
                    item.source === "ocr"
                        ? "图片识题"
                        : "聊天题目"
                )
        );

        source.textContent = (
            `来源：${sourceLabel}。只有编辑框中的内容会进入错题本。`
        );
    }

    if (confirm) {
        confirm.textContent = (
            pendingWrongSafeIndex
            < pendingWrongSafeItems.length - 1
                ? "确认并查看下一道"
                : "确认加入错题本"
        );
    }

    setTimeout(() => {
        textarea.focus();
        textarea.setSelectionRange(
            0,
            0
        );
    }, 0);
}

function closeWrongSafePreview() {
    const modal = document.getElementById(
        "wrongSafeModal"
    );

    if (modal) {
        modal.classList.add("hidden");
    }

    pendingWrongSafeItems = [];
    pendingWrongSafeIndex = 0;
}

function confirmWrongSafePreview() {
    const textarea = document.getElementById(
        "wrongSafeQuestion"
    );

    if (
        !textarea
        || !pendingWrongSafeItems.length
    ) {
        return;
    }

    const text = textarea.value.trim();

    if (!text) {
        window.alert(
            "题目不能为空。请保留题目正文，或者取消本次加入。"
        );
        return;
    }

    const item = pendingWrongSafeItems[
        pendingWrongSafeIndex
    ];

    addQuestionInfoToWrongBook({
        ...item,
        text,
        safeConfirmed: true
    });

    pendingWrongSafeIndex += 1;

    if (
        pendingWrongSafeIndex
        < pendingWrongSafeItems.length
    ) {
        renderWrongSafePreview();
        return;
    }

    const total = pendingWrongSafeItems.length;

    closeWrongSafePreview();

    const button = document.getElementById(
        "markWrongBtn"
    );

    if (button) {
        const previous = button.textContent;
        button.textContent = total > 1
            ? `已记录 ${total} 道`
            : "已记录";

        setTimeout(() => {
            button.textContent = previous;
            renderLearningSummary();
        }, 1000);
    }
}


function addQuestionInfoToWrongBook(questionInfo) {
    const result = addWrongQuestion(
        questionInfo,
        "这道题已加入错题本。",
        "manual"
    );

    saveState();
    renderLearningSummary();
    renderWrongBook();

    return result;
}

function confirmWrongQuestionPicker() {
    const pending = pendingWrongQuestionSelection;

    if (!pending) return;

    const checked = [
        ...document.querySelectorAll(
            "#wrongQuestionPickerList input[type='checkbox']:checked"
        )
    ];

    if (!checked.length) {
        window.alert("请至少选择一道题。");
        return;
    }

    const items = [];

    for (const checkbox of checked) {
        const index = Number(checkbox.value);
        const choice = pending.choices[index];

        if (!choice) continue;

        items.push({
            ...pending.questionInfo,
            text: choice.question,
            referenceAnswer: choice.referenceAnswer || ""
        });
    }

    closeWrongQuestionPicker();

    if (items.length) {
        openWrongSafePreview(items);
    }
}



function inferAnswerAssessment(reply) {
    let text = String(reply || "").replace(/\s+/g, " ").trim();

    if (!text) return "unknown";

    const strongPositive = [
        "完全正确",
        "这次作答正确",
        "作答正确",
        "答案正确",
        "结果正确",
        "计算正确",
        "没有错误",
        "没有问题",
        "没错",
        "是对的"
    ];

    const hasPositive = strongPositive.some(
        phrase => text.includes(phrase)
    );

    for (const phrase of strongPositive) {
        text = text.split(phrase).join("");
    }

    const negative = [
        "不正确",
        "这次作答有错误",
        "作答有错误",
        "答案有误",
        "结果有误",
        "存在错误",
        "这里错了",
        "这一步错",
        "算错",
        "写错",
        "错误在",
        "最早出错",
        "不成立",
        "需要修改",
        "需要纠正",
        "有一个错误",
        "有一处错误"
    ];

    if (negative.some(phrase => text.includes(phrase))) {
        return "wrong";
    }

    return hasPositive ? "correct" : "unknown";
}

function compactFeedback(text) {
    return String(text || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 1000);
}

function wrongQuestionFingerprint(question) {
    return String(question || "")
        .toLowerCase()
        .replace(/[【】\[\]（）()，,。.!！?？:：;；"'“”‘’`]/g, "")
        .replace(/\s+/g, "")
        .slice(0, 1600);
}

function wrongBookLearningPoints(entryOrQuestion) {
    const focus = Array.isArray(entryOrQuestion?.focusPoints)
        ? entryOrQuestion.focusPoints.filter(Boolean)
        : [];

    if (focus.length) {
        return focus.slice(0, 2);
    }

    return Array.isArray(entryOrQuestion?.knowledgePoints)
        ? entryOrQuestion.knowledgePoints.filter(Boolean).slice(0, 4)
        : [];
}

function addWrongQuestion(questionInfo, feedback, source = "auto") {
    const safeConfirmed = Boolean(
        source === "manual"
        && questionInfo
        && questionInfo.safeConfirmed
    );

    const info = normalizeLearningQuestion(questionInfo);
    if (!info) return { entry: null, countAsMistake: false };

    info.text = safeConfirmed
        ? String(questionInfo.text || "").trim().slice(0, 3000)
        : sanitizeStoredWrongQuestionText(
            info.text
        ).slice(0, 3000);

    if (
        source === "auto"
        && info.text
        && !looksLikeQuestionPayload(info.text)
    ) {
        return {
            entry: null,
            countAsMistake: false
        };
    }

    if (!info.text) {
        return {
            entry: null,
            countAsMistake: false
        };
    }

    const now = Date.now();

    const entry = {
        id: `wrong-${now}-${Math.random().toString(36).slice(2, 8)}`,
        question: info.text,
        knowledgePoints: info.knowledgePoints,
        focusPoints: info.focusPoints,
        category: info.category,
        difficulty: info.difficulty || "",
        feedback: compactFeedback(feedback),
        referenceAnswer: info.referenceAnswer || "",
        answer: "",
        analysis: "",
        answerUpdatedAt: null,
        analysisUpdatedAt: null,
        note: "",
        source: source === "auto" ? "auto" : "manual",
        corrected: false,
        mistakeCount: source === "auto" ? 1 : 0,
        sessionId: info.sessionId,
        createdAt: now,
        updatedAt: now,
        lastWrongAt: now,
        correctedAt: null,
        retestCount: 0,
        retestPassCount: 0,
        retestFailCount: 0,
        retestPassed: false,
        retestPassedAt: null,
        lastRetestAt: null,
        lastRetestQuestion: "",
        lastRetestFeedback: "",
        lastRetestResult: "",
        lastRetestSessionId: null
    };

    learningState.wrongQuestions.push(entry);

    if (learningState.wrongQuestions.length > MAX_WRONG_QUESTIONS) {
        learningState.wrongQuestions = learningState.wrongQuestions
            .slice(-MAX_WRONG_QUESTIONS);
    }

    saveLearningState();

    queueWrongQuestionAnswer(
        entry.id
    );

    return {
        entry,
        countAsMistake: true
    };
}

function currentLearningQuestion(session, teaching) {
    const saved = normalizeLearningQuestion(
        session?.learningQuestion
    );
    const currentTeaching = normalizeTeaching(
        teaching
    );

    if (saved) {
        const livePoints = currentTeaching?.knowledge_points || [];
        const liveFocus = currentTeaching?.focus_points || [];

        return {
            ...saved,
            // 当前题已经有实时分类时，以当前题为准，
            // 不再把上一道题的知识点继续混进来。
            knowledgePoints: livePoints.length
                ? livePoints.slice(0, 4)
                : saved.knowledgePoints,
            focusPoints: liveFocus.length
                ? liveFocus.slice(0, 2)
                : saved.focusPoints,
            category: (
                currentTeaching?.category
                && currentTeaching.category !== "待识别"
            )
                ? currentTeaching.category
                : saved.category,
            difficulty: currentTeaching?.difficulty
                || saved.difficulty
                || ""
        };
    }

    return buildLearningQuestionFromSession(
        session,
        teaching,
        true
    ) || buildLearningQuestionFromSession(
        session,
        teaching,
        false
    );
}

function processLearningFromReply(
    session,
    teaching,
    reply,
    generatedAnswer = "",
    generatedQuestion = ""
) {
    const normalized = normalizeTeaching(teaching);

    if (!session || !normalized) {
        return;
    }

    const points = normalized.knowledge_points;
    const latest = getLatestUserMessage(session);
    const latestText = latest?.text || "";

    // 用户明确让 AI 出练习题时，AI 返回的题目本身就是当前学习题。
    // “记为错题”应保存模型生成的题目，而不是“给我一道题”这句请求。
    if (
        (
            Boolean(String(generatedQuestion || "").trim())
            || normalized.mode === "exercise"
            || isExerciseRequestText(latestText)
        )
        && typeof reply === "string"
        && reply.trim()
    ) {
        const generatedExercise = (
            String(generatedQuestion || "").trim()
            || extractAiQuestionPayload(reply)
        );

        session.learningQuestion = {
            text: generatedExercise || reply.trim().slice(0, 3000),
            knowledgePoints: points.slice(0, 4),
            focusPoints: normalized.focus_points.slice(0, 2),
            category: normalized.category,
            difficulty: normalized.difficulty || "",
            source: "ai",
            referenceAnswer: String(
                generatedAnswer || ""
            ).trim().slice(0, 3000),
            sessionId: session.id,
            updatedAt: Date.now()
        };

        if (points.length) {
            updateKnowledge(
                points,
                "seen",
                session.id
            );
        }
    }

    const isSubstantiveQuestion = Boolean(
        latest
        && looksLikeActualLearningProblem(latest)
        && normalized.mode !== "check_answer"
        && normalized.mode !== "exercise"
    );

    // “上一道题再讲一下”以及后续“继续”都属于题目上下文切换/保持，
    // 不是新题。根据完整消息历史恢复真正的当前题，避免 learningQuestion
    // 仍停留在时间上更靠后的那道题。
    if (
        !isSubstantiveQuestion
        && normalized.mode !== "exercise"
        && !String(generatedQuestion || "").trim()
    ) {
        const activeCandidate = activeQuestionCandidateFromHistory(
            session
        );

        if (activeCandidate) {
            const latestMessage = getLatestUserMessage(session);
            const preserveActiveQuestionTeaching = Boolean(
                latestMessage
                && (
                    isShortLearningFollowUp(latestMessage.text)
                    || (
                        latestMessage.source === "ocr"
                        && !isRecordableOcrQuestionMessage(latestMessage)
                    )
                )
            );

            const targetTeaching = preserveActiveQuestionTeaching
                ? (
                    candidateTeachingSnapshot(
                        session,
                        activeCandidate
                    ) || normalized
                )
                : normalized;

            applyQuestionCandidateAsCurrent(
                session,
                activeCandidate,
                targetTeaching
            );
        }
    }

    if (isSubstantiveQuestion && points.length) {
        const learningQuestionText = extractQuestionOnlyFromMessage(latest) || latestText;

        session.learningQuestion = {
            text: learningQuestionText.slice(0, 3000),
            knowledgePoints: points.slice(0, 4),
            focusPoints: normalized.focus_points.slice(0, 2),
            category: normalized.category,
            difficulty: normalized.difficulty || "",
            source: latest.source === "ocr" ? "ocr" : "text",
            sessionId: session.id,
            updatedAt: Date.now()
        };

        updateKnowledge(points, "seen", session.id);
    }

    if (
        ["hint", "full_solution"].includes(normalized.mode)
        && points.length
    ) {
        updateKnowledge(
            normalized.focus_points.length
                ? normalized.focus_points
                : points,
            "support",
            session.id
        );
    }

    const selfReportsWrong = /(?:我|这题|刚才).{0,8}(?:做错|算错|写错|错了)/.test(
        latestText.replace(/\s+/g, "")
    );

    if (
        normalized.mode === "check_answer"
        || selfReportsWrong
    ) {
        const assessment = selfReportsWrong
            ? "wrong"
            : inferAnswerAssessment(reply);

        if (assessment === "wrong") {
            const questionInfo = currentLearningQuestion(
                session,
                normalized
            );

            const added = addWrongQuestion(
                questionInfo,
                selfReportsWrong
                    ? "你明确表示这道题做错了，建议完成订正后再标记为已订正。"
                    : reply,
                "auto"
            );

            if (added.countAsMistake) {
                updateKnowledge(
                    wrongBookLearningPoints(
                        questionInfo || {
                            knowledgePoints: points,
                            focusPoints: normalized.focus_points
                        }
                    ),
                    "wrong",
                    session.id
                );
            }
        } else if (assessment === "correct") {
            updateKnowledge(
                normalized.focus_points.length
                    ? normalized.focus_points
                    : points,
                "correct",
                session.id
            );
        }
    }

    saveState();
    saveLearningState();
    renderLearningSummary();
}

function manualMarkCurrentWrong() {
    const session = getCurrent();
    if (!session) return;

    const teaching = normalizeTeaching(
        session.teaching
    );

    const questionInfo = currentLearningQuestion(
        session,
        teaching
    );

    if (!questionInfo) {
        window.alert(
            "当前还没有可加入错题本的题目。"
        );
        return;
    }

    const choices = splitQuestionBankText(
        questionInfo.text
    );

    if (
        choices.length
        && openWrongQuestionPicker(
            questionInfo,
            choices
        )
    ) {
        return;
    }

    openWrongSafePreview(
        questionInfo
    );
}



function learningReviewItemLabel(item) {
    if (!item || typeof item !== "object") {
        return "";
    }

    const candidates = [
        ...(Array.isArray(item.focusPoints) ? item.focusPoints : []),
        ...(Array.isArray(item.knowledgePoints) ? item.knowledgePoints : []),
        item.category
    ];

    return candidates.find(
        value => (
            typeof value === "string"
            && value.trim()
            && value.trim() !== "待识别"
        )
    )?.trim() || "这道题";
}

function validLearningReviewEvents() {
    const liveSessionIds = new Set(
        (Array.isArray(sessions) ? sessions : [])
            .map(session => String(session?.id ?? ""))
            .filter(Boolean)
    );

    // 学习回顾只使用仍能对应到现存会话的事件。
    // 旧版本可能留下 sessionId 为空或原会话已删除的孤立事件，
    // 这些事件不能继续出现在“最近学习”里。
    return (Array.isArray(learningState.events) ? learningState.events : [])
        .filter(event => {
            if (!event || typeof event !== "object") return false;
            if (event.sessionId === null || event.sessionId === undefined) {
                return false;
            }
            return liveSessionIds.has(String(event.sessionId));
        });
}

function collectLearningReviewPoints() {
    const points = [];

    const events = [...validLearningReviewEvents()].sort(
        (a, b) => (Number(b.createdAt) || 0) - (Number(a.createdAt) || 0)
    );

    for (const event of events.slice(0, 18)) {
        points.push(...(
            Array.isArray(event.points)
                ? event.points
                : []
        ));
    }

    const recentWrong = [...(
        Array.isArray(learningState.wrongQuestions)
            ? learningState.wrongQuestions
            : []
    )].sort(
        (a, b) => (Number(b.updatedAt) || 0) - (Number(a.updatedAt) || 0)
    );

    for (const item of recentWrong.slice(0, 5)) {
        points.push(
            ...(item.focusPoints || []),
            ...(item.knowledgePoints || [])
        );
    }

    return uniqueTextList(points, 5);
}

function buildLearningReviewSnapshot() {
    const recentPoints = collectLearningReviewPoints();
    const wrongItems = Array.isArray(learningState.wrongQuestions)
        ? learningState.wrongQuestions
        : [];

    const pending = wrongItems
        .filter(item => !item.corrected)
        .sort(
            (a, b) => (
                (Number(b.lastWrongAt) || Number(b.updatedAt) || 0)
                - (Number(a.lastWrongAt) || Number(a.updatedAt) || 0)
            )
        );

    const needsRetest = wrongItems
        .filter(item => item.corrected && !item.retestPassed)
        .sort(
            (a, b) => (Number(b.updatedAt) || 0) - (Number(a.updatedAt) || 0)
        );

    const failedRetest = wrongItems
        .filter(item => (
            !item.retestPassed
            && (Number(item.retestFailCount) || 0) > 0
        ))
        .sort(
            (a, b) => (Number(b.lastRetestAt) || 0) - (Number(a.lastRetestAt) || 0)
        );

    const sections = [];

    if (recentPoints.length) {
        let recentText = "";

        if (recentPoints.length === 1) {
            recentText = `从现有记录看，最近主要围绕“${recentPoints[0]}”进行了学习。`;
        } else if (recentPoints.length === 2) {
            recentText = `从现有记录看，最近主要接触了“${recentPoints[0]}”和“${recentPoints[1]}”。`;
        } else {
            recentText = (
                `最近的学习比较分散，记录中出现了“${recentPoints[0]}”“${recentPoints[1]}”“${recentPoints[2]}”`
                + (recentPoints.length > 3 ? "等内容。" : "。")
            );
        }

        sections.push({
            title: "最近学习",
            text: recentText
        });
    }

    const attentionLines = [];
    const usedLabels = new Set();

    const addAttention = (item, kind) => {
        const label = learningReviewItemLabel(item);
        if (!label || usedLabels.has(label)) return;

        usedLabels.add(label);

        if (kind === "failed") {
            attentionLines.push(
                `“${label}”有复测未通过的记录，之后如果还想继续，可以再回看一次。`
            );
            return;
        }

        if (kind === "pending") {
            attentionLines.push(
                `“${label}”相关题目还留在错题本中，尚未完成订正。`
            );
            return;
        }

        attentionLines.push(
            `“${label}”已经有订正记录，但目前还没有通过复测。`
        );
    };

    failedRetest.slice(0, 2).forEach(
        item => addAttention(item, "failed")
    );

    pending.slice(0, 2).forEach(
        item => addAttention(item, "pending")
    );

    needsRetest.slice(0, 2).forEach(
        item => addAttention(item, "retest")
    );

    if (attentionLines.length) {
        sections.push({
            title: "值得再看看",
            text: attentionLines.slice(0, 2).join("\n")
        });
    }

    let nextText = "";

    if (pending.length) {
        nextText = "如果想继续，可以先从错题本里挑一道尚未订正的题重新做，不必一次处理很多。";
    } else if (needsRetest.length) {
        nextText = "如果想继续，可以从已经订正但还没有通过复测的题里挑一道，再测一次。";
    } else if (recentPoints.length) {
        nextText = `如果想继续，可以围绕“${recentPoints[0]}”再问一个具体问题，或者让 AI 出一道同类题。`;
    }

    if (nextText) {
        sections.push({
            title: "接下来可以做",
            text: nextText
        });
    }

    const hasAnyRecord = Boolean(
        recentPoints.length
        || wrongItems.length
        || validLearningReviewEvents().length
    );

    return {
        hasAnyRecord,
        sections
    };
}

function renderLearningReview() {
    const body = document.getElementById("learningReviewBody");
    if (!body) return;

    body.innerHTML = "";

    const snapshot = buildLearningReviewSnapshot();

    if (!snapshot.hasAnyRecord || !snapshot.sections.length) {
        const empty = document.createElement("div");
        empty.className = "learning-review-empty";
        empty.textContent = "无";
        body.appendChild(empty);
        return;
    }

    for (const section of snapshot.sections) {
        const card = document.createElement("section");
        card.className = "learning-review-section";

        const title = document.createElement("div");
        title.className = "learning-review-section-title";
        title.textContent = section.title;

        const text = document.createElement("p");
        text.className = "learning-review-section-text";
        text.textContent = section.text;

        card.appendChild(title);
        card.appendChild(text);
        body.appendChild(card);
    }
}

function openLearningReview() {
    const modal = document.getElementById("learningReviewModal");
    if (!modal) return;

    renderLearningReview();
    modal.classList.remove("hidden");
}

function closeLearningReview() {
    const modal = document.getElementById("learningReviewModal");
    if (modal) {
        modal.classList.add("hidden");
    }
}


function formatLearningDate(timestamp) {
    const date = new Date(timestamp);

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    const month = date.getMonth() + 1;
    const day = date.getDate();
    const hour = String(
        date.getHours()
    ).padStart(2, "0");
    const minute = String(
        date.getMinutes()
    ).padStart(2, "0");

    return `${month}月${day}日 ${hour}:${minute}`;
}

function renderLearningSummary() {
    const box = document.getElementById("learningSummary");
    const markButton = document.getElementById("markWrongBtn");
    const wrongButton = document.getElementById("wrongBookBtn");

    if (!box) return;

    const wrongCount = learningState.wrongQuestions.length;
    const pendingWrong = learningState.wrongQuestions
        .filter(item => !item.corrected)
        .sort((a, b) => b.updatedAt - a.updatedAt);
    const pendingCount = pendingWrong.length;
    const passedCount = learningState.wrongQuestions
        .filter(item => item.retestPassed)
        .length;

    const lines = [];

    lines.push(
        `错题本：${wrongCount} 道，待订正 ${pendingCount} 道，已通过复测 ${passedCount} 道`
    );

    box.innerText = lines.join("\n");

    if (wrongButton) {
        wrongButton.textContent = `查看错题本 (${wrongCount})`;
    }

    if (markButton) {
        const session = getCurrent();
        const teaching = normalizeTeaching(session?.teaching);

        markButton.disabled = !(
            session
            && currentLearningQuestion(session, teaching)
        );
    }
}


function setWrongBookFilter(filter) {
    if (!["pending", "corrected", "passed"].includes(filter)) {
        return;
    }

    // 不再单独放“全部”按钮：
    // 未选择任何状态时就是“全部”；
    // 再点一次当前筛选即可取消筛选。
    wrongBookFilter = (
        wrongBookFilter === filter
            ? "all"
            : filter
    );

    renderWrongBook();
}

function setWrongBookSearch(value) {
    wrongBookSearch = String(value || "")
        .trim()
        .toLowerCase();

    renderWrongBook();
}

function setWrongBookSort(value) {
    if (!["recent", "oldest", "mistakes"].includes(value)) {
        return;
    }

    wrongBookSort = value;
    renderWrongBook();
}

function wrongBookStatus(item) {
    if (item.retestPassed) {
        return {
            key: "passed",
            text: "已通过复测",
            className: "passed"
        };
    }

    if (item.corrected) {
        return {
            key: "corrected",
            text: "已完成订正",
            className: "corrected"
        };
    }

    if (item.lastRetestResult === "wrong") {
        return {
            key: "pending",
            text: "复测未通过",
            className: "failed"
        };
    }

    return {
        key: "pending",
        text: "待订正",
        className: ""
    };
}

function wrongBookSearchText(item) {
    return [
        item.question,
        item.category,
        ...(item.knowledgePoints || []),
        ...(item.focusPoints || []),
        item.feedback,
        item.referenceAnswer,
        item.answer,
        item.analysis,
        item.note,
        item.lastRetestQuestion,
        item.lastRetestFeedback
    ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
}

function getFilteredWrongBookItems() {
    let items = [...learningState.wrongQuestions];

    if (wrongBookFilter !== "all") {
        items = items.filter(
            item => wrongBookStatus(item).key === wrongBookFilter
        );
    }

    if (wrongBookSearch) {
        items = items.filter(
            item => wrongBookSearchText(item).includes(wrongBookSearch)
        );
    }

    if (wrongBookSort === "oldest") {
        items.sort((a, b) => a.updatedAt - b.updatedAt);
    } else if (wrongBookSort === "mistakes") {
        items.sort((a, b) => (
            b.mistakeCount - a.mistakeCount
            || b.updatedAt - a.updatedAt
        ));
    } else {
        items.sort((a, b) => b.updatedAt - a.updatedAt);
    }

    return items;
}

function updateWrongBookToolbar(allItems, visibleItems) {
    const stats = document.getElementById("wrongBookStats");
    const filterButtons = document.querySelectorAll(
        "[data-wrong-filter]"
    );

    const total = allItems.length;
    const pending = allItems.filter(
        item => wrongBookStatus(item).key === "pending"
    ).length;
    const corrected = allItems.filter(
        item => wrongBookStatus(item).key === "corrected"
    ).length;
    const passed = allItems.filter(
        item => wrongBookStatus(item).key === "passed"
    ).length;

    if (stats) {
        const visibleText = visibleItems.length === total
            ? ""
            : ` · 当前显示 ${visibleItems.length} 道`;

        stats.textContent =
            `共 ${total} 道 · 待处理 ${pending} · 已订正 ${corrected} · 已通过复测 ${passed}${visibleText}`;
    }

    for (const button of filterButtons) {
        const value = button.getAttribute("data-wrong-filter");
        button.classList.toggle(
            "active",
            value === wrongBookFilter
        );
    }
}

async function refreshWrongBookDifficulties() {
    const missing = learningState.wrongQuestions.filter(
        item => !["简单", "中等", "困难"].includes(item.difficulty)
    );
    if (!missing.length) return;

    try {
        const response = await fetch("/analyze-questions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                questions: missing.map(item => ({ key: item.id, text: item.question }))
            })
        });
        if (!response.ok) return;

        const payload = await parseResponseJson(response);
        const byId = new Map(
            (payload?.results || []).map(item => [
                String(item?.key || ""),
                normalizeTeaching(item?.teaching)
            ])
        );
        let changed = false;

        for (const item of missing) {
            const difficulty = byId.get(String(item.id))?.difficulty || "";
            if (!["简单", "中等", "困难"].includes(difficulty)) continue;
            item.difficulty = difficulty;
            changed = true;
        }

        if (changed) {
            saveLearningState();
            renderWrongBook();
        }
    } catch (error) {
        console.warn("错题难度补齐失败：", error);
    }
}


function openWrongBook() {
    const modal = document.getElementById("wrongBookModal");
    if (!modal) return;

    renderWrongBook();
    modal.classList.remove("hidden");
    void refreshWrongBookDifficulties();

    const search = document.getElementById("wrongBookSearch");
    if (search) {
        search.value = wrongBookSearch;
    }
}

function closeWrongBook() {
    const modal = document.getElementById("wrongBookModal");
    if (!modal) return;

    modal.classList.add("hidden");
}

function markWrongQuestionCorrected(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry || entry.corrected) return;

    const now = Date.now();

    entry.corrected = true;
    entry.correctedAt = now;
    entry.updatedAt = now;

    updateKnowledge(
        wrongBookLearningPoints(entry),
        "reviewed",
        entry.sessionId
    );

    saveLearningState();
    renderLearningSummary();
    renderWrongBook();
}

function removeWrongQuestion(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry) return;

    const confirmed = window.confirm(
        "确定要把这道题移出错题本吗？这不会删除原聊天。"
    );

    if (!confirmed) return;

    learningState.wrongQuestions = learningState.wrongQuestions.filter(
        item => item.id !== id
    );

    saveLearningState();
    renderLearningSummary();
    renderWrongBook();
}

function clearCompletedWrongQuestions() {
    const completed = learningState.wrongQuestions.filter(
        item => item.corrected || item.retestPassed
    );

    if (!completed.length) {
        window.alert("目前没有可以清理的已完成错题。");
        return;
    }

    const confirmed = window.confirm(
        `确定移出 ${completed.length} 道已完成的错题吗？原聊天不会被删除。`
    );

    if (!confirmed) return;

    const completedIds = new Set(
        completed.map(item => item.id)
    );

    learningState.wrongQuestions = learningState.wrongQuestions.filter(
        item => !completedIds.has(item.id)
    );

    saveLearningState();
    renderLearningSummary();
    renderWrongBook();
}

function openWrongQuestionSession(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry || entry.sessionId === null) return;

    const session = sessions.find(
        item => String(item.id) === String(entry.sessionId)
    );

    if (!session) return;

    if (typingTimer) {
        forceCompleteTyping();
    }

    currentId = session.id;
    saveState();
    closeWrongBook();
    renderAll();
}

function openWrongRetestSession(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry || entry.lastRetestSessionId === null) return;

    const session = sessions.find(
        item => String(item.id) === String(entry.lastRetestSessionId)
    );

    if (!session) return;

    if (typingTimer) {
        forceCompleteTyping();
    }

    currentId = session.id;
    saveState();
    closeWrongBook();
    renderAll();
}

function openWrongEdit(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry) return;

    currentWrongEditId = id;

    const modal = document.getElementById("wrongEditModal");
    const question = document.getElementById("wrongEditQuestion");
    const focus = document.getElementById("wrongEditFocus");
    const note = document.getElementById("wrongEditNote");

    if (!modal || !question || !focus || !note) return;

    question.value = entry.question;
    focus.value = (entry.focusPoints || []).join("、");
    note.value = entry.note || "";

    modal.classList.remove("hidden");
}

function closeWrongEdit() {
    const modal = document.getElementById("wrongEditModal");
    if (modal) {
        modal.classList.add("hidden");
    }

    currentWrongEditId = null;
}

function saveWrongEdit() {
    const entry = learningState.wrongQuestions.find(
        item => item.id === currentWrongEditId
    );

    if (!entry) {
        closeWrongEdit();
        return;
    }

    const questionBox = document.getElementById("wrongEditQuestion");
    const focusBox = document.getElementById("wrongEditFocus");
    const noteBox = document.getElementById("wrongEditNote");

    if (!questionBox || !focusBox || !noteBox) return;

    const question = questionBox.value.trim();

    if (!question) {
        window.alert("题目内容不能为空。");
        return;
    }

    const duplicate = learningState.wrongQuestions.find(
        item => (
            item.id !== entry.id
            && wrongQuestionFingerprint(item.question)
                === wrongQuestionFingerprint(question)
        )
    );

    if (duplicate) {
        window.alert("错题本里已经有这道题了，请不要重复保存。");
        return;
    }

    const focusPoints = focusBox.value
        .split(/[、,，;；]/)
        .map(item => item.trim())
        .filter(Boolean)
        .slice(0, 2);

    entry.question = question.slice(0, 3000);
    entry.focusPoints = focusPoints;
    entry.note = noteBox.value.trim().slice(0, 1500);

    if (focusPoints.length) {
        entry.knowledgePoints = [
            ...new Set([
                ...focusPoints,
                ...(entry.knowledgePoints || [])
            ])
        ].slice(0, 4);
    }

    entry.updatedAt = Date.now();

    saveLearningState();
    closeWrongEdit();
    renderLearningSummary();
    renderWrongBook();
}

function buildRetestPrompt(entry) {
    const target = wrongBookLearningPoints(entry);
    const targetText = target.length
        ? target.join("、")
        : (
            entry.category
            || "这道题涉及的核心知识点"
        );

    // 原错题通过 exercise_reference 单独、结构化地发给后端。
    // 这里仅保留“本轮动作”，避免原题在 prompt 里重复两遍，
    // 也避免把“原错题正文”误当成本轮要回答的题。
    return [
        "【错题复测】",
        `请围绕知识点“${targetText}”生成 1 道新的离散数学复测题。`,
        "要求：",
        "1. 与当前指向的原错题考查同一核心能力，但题面、数字或结构必须明显不同；",
        "2. 难度与原题大致相当，不要故意变难；",
        "3. 只给复测题目，不给答案、提示、解析或解题步骤；",
        "4. 题目必须信息完整、可独立作答；",
        "5. 不要回答原错题，只生成新的复测题。"
    ].join("\n");
}

function startWrongQuestionRetest(id) {
    if (
        isCurrentSessionTyping()
        || isSessionBusy(currentId)
    ) {
        return;
    }

    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry) return;

    if (!entry.corrected && !entry.retestPassed) {
        window.alert("请先完成这道错题的订正，再进行复测。");
        return;
    }

    const targetPoints = wrongBookLearningPoints(entry);
    const idValue = makeSessionId();
    const targetName = targetPoints.length
        ? targetPoints[0]
        : "错题";

    const visiblePrompt =
        `给我一道“${targetName}”的同知识点复测题。`;

    const session = {
        id: idValue,
        name: `复测：${targetName}`.slice(0, 22),
        messages: [{
            role: "user",
            text: visiblePrompt,
            apiText: buildRetestPrompt(entry),
            isRetestPrompt: true
        }],
        teaching: null,
        learningQuestion: null,
        retest: {
            wrongQuestionId: entry.id,
            stage: "generating",
            targetPoints,
            referenceQuestion: entry.question,
            generatedQuestion: "",
            generatedAnswer: "",
            startedAt: Date.now(),
            result: ""
        }
    };

    sessions.push(session);
    currentId = session.id;

    entry.lastRetestSessionId = session.id;
    entry.updatedAt = Date.now();

    saveLearningState();
    saveState();
    closeWrongBook();
    renderAll();

    requestAiReply(session);
}

function processWrongQuestionRetestReply(
    session,
    reply,
    generatedQuestion = "",
    generatedAnswer = ""
) {
    const retest = normalizeRetestSession(session?.retest);

    if (!session || !retest || !retest.wrongQuestionId) {
        return false;
    }

    const entry = learningState.wrongQuestions.find(
        item => item.id === retest.wrongQuestionId
    );

    if (!entry) {
        session.retest = null;
        saveState();
        return false;
    }

    if (retest.stage === "generating") {
        const cleanQuestion = sanitizeStoredWrongQuestionText(
            generatedQuestion
            || extractAiGeneratedExerciseText(reply)
            || reply
        );

        if (!cleanQuestion) {
            return false;
        }

        retest.referenceQuestion = (
            retest.referenceQuestion
            || entry.question
            || ""
        ).slice(0, 3000);
        retest.generatedQuestion = cleanQuestion.slice(0, 3000);
        retest.generatedAnswer = String(generatedAnswer || "")
            .trim()
            .slice(0, 1200);
        retest.stage = "awaiting_answer";
        session.retest = retest;

        saveState();
        return true;
    }

    if (retest.stage !== "checking") {
        return false;
    }

    const assessment = inferAnswerAssessment(reply);
    const now = Date.now();

    entry.lastRetestAt = now;
    entry.lastRetestSessionId = session.id;
    entry.lastRetestQuestion = (
        retest.generatedQuestion
        || entry.lastRetestQuestion
        || ""
    ).slice(0, 3000);
    entry.lastRetestFeedback = compactFeedback(reply);
    entry.lastRetestResult = assessment;

    if (assessment === "correct") {
        entry.retestCount += 1;
        entry.retestPassCount += 1;
        entry.retestPassed = true;
        entry.retestPassedAt = now;
        entry.corrected = true;
        entry.correctedAt = entry.correctedAt || now;

        updateKnowledge(
            retest.targetPoints.length
                ? retest.targetPoints
                : wrongBookLearningPoints(entry),
            "correct",
            session.id
        );
    } else if (assessment === "wrong") {
        entry.retestCount += 1;
        entry.retestFailCount += 1;
        entry.retestPassed = false;
        entry.retestPassedAt = null;
        entry.corrected = false;
        entry.correctedAt = null;

        updateKnowledge(
            retest.targetPoints.length
                ? retest.targetPoints
                : wrongBookLearningPoints(entry),
            "wrong",
            session.id
        );
    }

    entry.updatedAt = now;

    retest.result = assessment;
    retest.stage = assessment === "unknown"
        ? "awaiting_answer"
        : "finished";
    session.retest = retest;

    saveState();
    saveLearningState();
    renderLearningSummary();
    renderWrongBook();

    return true;
}

function rollbackRetestAfterRequestFailure(session) {
    const retest = normalizeRetestSession(session?.retest);
    if (!retest) return;

    if (retest.stage === "checking") {
        retest.stage = "awaiting_answer";
        session.retest = retest;
    } else if (retest.stage === "generating") {
        session.retest = null;
    }

    saveState();
}

function dedupeWrongBookItemsForPdf(items) {
    const seen = new Set();
    const unique = [];

    for (const item of items || []) {
        const fingerprint = wrongQuestionFingerprint(
            item?.question
        );
        const key = fingerprint || `id:${item?.id || unique.length}`;

        if (seen.has(key)) {
            continue;
        }

        seen.add(key);
        unique.push(item);
    }

    return unique;
}

function buildWrongBookPdfExportElement(items) {
    items = dedupeWrongBookItemsForPdf(items);

    const container = document.createElement("div");
    container.className = "wrong-pdf-export";
    container.style.position = "fixed";
    container.style.left = "-100000px";
    container.style.top = "0";
    container.style.width = "794px";
    container.style.boxSizing = "border-box";
    container.style.padding = "34px 40px";
    container.style.background = "#ffffff";
    container.style.color = "#111827";
    container.style.fontFamily = 'Arial, "Microsoft YaHei", "PingFang SC", sans-serif';
    container.style.lineHeight = "1.65";
    container.style.zIndex = "-1";

    const title = document.createElement("div");
    title.style.fontSize = "28px";
    title.style.fontWeight = "700";
    title.style.marginBottom = "6px";
    title.textContent = "离散数学错题本";
    container.appendChild(title);

    const subtitle = document.createElement("div");
    subtitle.style.fontSize = "13px";
    subtitle.style.color = "#64748b";
    subtitle.style.marginBottom = "22px";
    subtitle.textContent = (
        `共 ${items.length} 道 · 导出时间：${new Date().toLocaleString("zh-CN")}`
    );
    container.appendChild(subtitle);

    items.forEach((item, index) => {
        const status = wrongBookStatus(item);
        const card = document.createElement("section");
        card.className = "wrong-pdf-card";
        card.style.padding = "18px 0 20px";
        card.style.borderTop = (
            index === 0
                ? "0"
                : "1px solid #e2e8f0"
        );

        const statusLine = document.createElement("div");
        statusLine.style.fontSize = "15px";
        statusLine.style.fontWeight = "700";
        statusLine.style.marginBottom = "10px";
        statusLine.textContent = `${index + 1}. ${status.text}`;
        card.appendChild(statusLine);

        const question = document.createElement("div");
        question.className = "wrong-pdf-question";
        question.style.fontSize = "15px";
        question.style.whiteSpace = "pre-wrap";
        question.style.wordBreak = "break-word";
        question.innerHTML = markdownToHtml(item.question);
        card.appendChild(question);

        const metaParts = [];

        if (item.focusPoints?.length) {
            metaParts.push(
                `本题难点：${item.focusPoints.join("、")}`
            );
        }

        if (item.knowledgePoints?.length) {
            metaParts.push(
                `整题涉及：${item.knowledgePoints.join("、")}`
            );
        }

        if (item.retestCount) {
            metaParts.push(
                `复测 ${item.retestCount} 次，通过 ${item.retestPassCount || 0} 次`
            );
        }

        const meta = document.createElement("div");
        meta.style.marginTop = "10px";
        meta.style.fontSize = "12px";
        meta.style.color = "#64748b";
        meta.textContent = metaParts.join(" · ");
        card.appendChild(meta);

        if (shouldShowWrongBookFeedback(item)) {
            const block = document.createElement("div");
            block.style.marginTop = "12px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.background = "#f8fafc";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "最近反馈";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.feedback);
            block.appendChild(body);

            card.appendChild(block);
        }

        if (item.referenceAnswer) {
            const block = document.createElement("div");
            block.style.marginTop = "10px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.background = "#f8fafc";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "参考答案";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.referenceAnswer);
            block.appendChild(body);

            card.appendChild(block);
        }

        if (item.answer) {
            const block = document.createElement("div");
            block.style.marginTop = "10px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.background = "#f8fafc";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "答案";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.answer);
            block.appendChild(body);

            card.appendChild(block);
        }

        if (item.analysis) {
            const block = document.createElement("div");
            block.style.marginTop = "10px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.background = "#f8fafc";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "解析";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.analysis);
            block.appendChild(body);

            card.appendChild(block);
        }

        if (item.note) {
            const block = document.createElement("div");
            block.style.marginTop = "10px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.background = "#f8fafc";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "我的笔记";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.note);
            block.appendChild(body);

            card.appendChild(block);
        }

        if (item.lastRetestQuestion) {
            const block = document.createElement("div");
            block.style.marginTop = "10px";
            block.style.padding = "10px 12px";
            block.style.borderRadius = "8px";
            block.style.border = "1px solid #e2e8f0";
            block.style.fontSize = "13px";

            const label = document.createElement("div");
            label.style.fontWeight = "700";
            label.style.marginBottom = "4px";
            label.textContent = "最近复测题";
            block.appendChild(label);

            const body = document.createElement("div");
            body.innerHTML = markdownToHtml(item.lastRetestQuestion);
            block.appendChild(body);

            card.appendChild(block);
        }

        container.appendChild(card);
    });

    document.body.appendChild(container);
    return container;
}

async function typesetWrongBookPdfElement(container) {
    if (
        window.MathJax
        && MathJax.typesetPromise
    ) {
        try {
            await MathJax.typesetPromise([container]);
        } catch (error) {
            console.warn("导出 PDF 时公式渲染失败：", error);
        }
    }

    if (document.fonts?.ready) {
        try {
            await document.fonts.ready;
        } catch (_error) {
            // 字体等待失败不阻止导出。
        }
    }

    // 给 SVG 数学公式和字体两帧时间完成最终布局，
    // 避免 html2canvas 抓到中间态产生重影。
    await new Promise(resolve => {
        requestAnimationFrame(() => {
            requestAnimationFrame(resolve);
        });
    });
}

async function rasterizeMathJaxSvgForPdf(container) {
    if (!container) return;

    // MathJax SVG 输出旁边通常还带一份“辅助 MathML”。浏览器里它被
    // CSS 隐藏，但 html2canvas 在克隆 DOM 时可能把这份无障碍文本也画出来，
    // 于是出现矩阵/公式重影。导出副本里先彻底移除这些隐藏节点。
    container.querySelectorAll(
        "mjx-assistive-mml, .MJX_Assistive_MathML, [data-mjx-assistive-mml]"
    ).forEach(node => node.remove());

    const mathContainers = [
        ...container.querySelectorAll("mjx-container")
    ];

    for (const mathContainer of mathContainers) {
        const svg = mathContainer.querySelector("svg");
        if (!svg) continue;

        const rect = svg.getBoundingClientRect();
        const width = Math.max(1, rect.width);
        const height = Math.max(1, rect.height);

        const clone = svg.cloneNode(true);
        clone.setAttribute(
            "xmlns",
            "http://www.w3.org/2000/svg"
        );
        clone.setAttribute("width", `${width}px`);
        clone.setAttribute("height", `${height}px`);
        clone.style.color = "#111827";

        clone.querySelectorAll('[fill="currentColor"]').forEach(
            node => node.setAttribute("fill", "#111827")
        );
        clone.querySelectorAll('[stroke="currentColor"]').forEach(
            node => node.setAttribute("stroke", "#111827")
        );

        const serialized = new XMLSerializer()
            .serializeToString(clone);
        const blob = new Blob(
            [serialized],
            { type: "image/svg+xml;charset=utf-8" }
        );
        const url = URL.createObjectURL(blob);

        try {
            const image = new Image();

            await new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = reject;
                image.src = url;
            });

            const scale = 2.5;
            const canvas = document.createElement("canvas");
            canvas.width = Math.max(
                1,
                Math.ceil(width * scale)
            );
            canvas.height = Math.max(
                1,
                Math.ceil(height * scale)
            );
            canvas.style.width = `${width}px`;
            canvas.style.height = `${height}px`;

            const isDisplay = (
                mathContainer.getAttribute("display") === "true"
                || mathContainer.style.display === "block"
            );

            canvas.style.display = isDisplay
                ? "block"
                : "inline-block";
            canvas.style.verticalAlign = "middle";

            if (isDisplay) {
                canvas.style.margin = "0.65em auto";
            }

            const context = canvas.getContext("2d");
            context.setTransform(
                scale,
                0,
                0,
                scale,
                0,
                0
            );
            context.drawImage(
                image,
                0,
                0,
                width,
                height
            );

            // 关键：替换整个 mjx-container，而不是只替换里面的 svg。
            // 这样 SVG、辅助 MathML、MathJax 包装层不会同时残留在截图 DOM 中。
            mathContainer.replaceWith(canvas);
        } catch (error) {
            console.warn(
                "PDF 数学公式栅格化失败：",
                error
            );

            // 即使某个 SVG 转换失败，也至少移除无障碍 MathML，防止重影。
            mathContainer.querySelectorAll(
                "mjx-assistive-mml, .MJX_Assistive_MathML"
            ).forEach(node => node.remove());
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    await new Promise(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
}

function canvasSlice(sourceCanvas, startY, sliceHeight) {
    const slice = document.createElement("canvas");
    slice.width = sourceCanvas.width;
    slice.height = sliceHeight;

    const context = slice.getContext("2d");
    context.drawImage(
        sourceCanvas,
        0,
        startY,
        sourceCanvas.width,
        sliceHeight,
        0,
        0,
        sourceCanvas.width,
        sliceHeight
    );

    return slice;
}

function findPdfSafeSliceHeight(
    canvas,
    startY,
    maxHeight
) {
    const remaining = canvas.height - startY;

    if (remaining <= maxHeight) {
        return remaining;
    }

    const target = Math.min(
        canvas.height - 1,
        startY + maxHeight
    );
    // 宁可上一页底部多留一点空白，也不要把一整行公式 / 矩阵 / 路径
    // 从中间切成两页。旧版最多只向前找 320px，数学块稍高就找不到
    // 段落间隙。现在允许回看约半页，优先在真正的空白带分页。
    const searchBack = Math.min(
        Math.floor(maxHeight * 0.52),
        1100
    );
    const searchStart = Math.max(
        startY + Math.floor(maxHeight * 0.34),
        target - searchBack
    );

    const context = canvas.getContext(
        "2d",
        { willReadFrequently: true }
    );

    if (!context) {
        return maxHeight;
    }

    let imageData;

    try {
        imageData = context.getImageData(
            0,
            searchStart,
            canvas.width,
            target - searchStart + 1
        );
    } catch (_error) {
        return maxHeight;
    }

    const { data, width, height } = imageData;
    const sampleStep = Math.max(2, Math.floor(width / 260));
    const blankRows = [];

    for (let y = 0; y < height; y += 1) {
        let ink = 0;
        let samples = 0;

        for (let x = 0; x < width; x += sampleStep) {
            const offset = (y * width + x) * 4;
            const r = data[offset];
            const g = data[offset + 1];
            const b = data[offset + 2];
            const a = data[offset + 3];

            if (a > 20) {
                samples += 1;

                // 白色 / #f8fafc 等浅背景都视为空白；真正文字和公式会
                // 至少有一个通道明显变暗。
                if (Math.min(r, g, b) < 218) {
                    ink += 1;
                }
            }
        }

        const ratio = samples ? ink / samples : 0;
        blankRows.push(ratio < 0.008);
    }

    let bestEnd = -1;
    let runStart = -1;

    for (let y = 0; y <= blankRows.length; y += 1) {
        const blank = y < blankRows.length
            ? blankRows[y]
            : false;

        if (blank && runStart < 0) {
            runStart = y;
            continue;
        }

        if (!blank && runStart >= 0) {
            const runLength = y - runStart;

            if (runLength >= 8) {
                bestEnd = y - 1;
            }

            runStart = -1;
        }
    }

    if (bestEnd >= 0) {
        const safeGlobalY = searchStart + bestEnd;
        const safeHeight = safeGlobalY - startY + 1;

        if (safeHeight >= maxHeight * 0.34) {
            return Math.max(1, safeHeight);
        }
    }

    return maxHeight;
}

async function exportWrongBookPdf() {
    const items = getFilteredWrongBookItems();

    if (!items.length) {
        window.alert("当前没有可以导出的错题。");
        return;
    }

    if (
        typeof window.html2canvas !== "function"
        || !window.jspdf?.jsPDF
    ) {
        window.alert(
            "PDF 组件加载失败，请刷新页面后重试。"
        );
        return;
    }

    const button = document.getElementById(
        "wrongPdfBtn"
    );
    const originalText = button?.textContent || "";

    if (button) {
        button.disabled = true;
        button.textContent = "正在生成 PDF…";
    }

    let exportElement = null;

    try {
        exportElement = buildWrongBookPdfExportElement(
            items
        );

        await typesetWrongBookPdfElement(
            exportElement
        );
        await rasterizeMathJaxSvgForPdf(
            exportElement
        );

        const {
            jsPDF
        } = window.jspdf;

        const pdf = new jsPDF({
            orientation: "portrait",
            unit: "mm",
            format: "a4",
            compress: true
        });

        const pageWidth = 210;
        const pageHeight = 297;
        const marginX = 12;
        const marginY = 12;
        const usableWidth = pageWidth - marginX * 2;
        const usableHeight = pageHeight - marginY * 2;

        const sections = [
            ...exportElement.children
        ];

        let currentY = marginY;
        let hasContent = false;

        for (const section of sections) {
            const canvas = await window.html2canvas(
                section,
                {
                    scale: 2,
                    backgroundColor: "#ffffff",
                    useCORS: true,
                    foreignObjectRendering: false,
                    logging: false
                }
            );

            if (!canvas.width || !canvas.height) {
                continue;
            }

            const renderedHeight = (
                canvas.height
                * usableWidth
                / canvas.width
            );

            const remaining = (
                usableHeight
                - (currentY - marginY)
            );

            if (renderedHeight <= usableHeight) {
                if (
                    hasContent
                    && renderedHeight > remaining
                ) {
                    pdf.addPage();
                    currentY = marginY;
                }

                const image = canvas.toDataURL(
                    "image/jpeg",
                    0.92
                );

                pdf.addImage(
                    image,
                    "JPEG",
                    marginX,
                    currentY,
                    usableWidth,
                    renderedHeight,
                    undefined,
                    "FAST"
                );

                currentY += renderedHeight + 4;
                hasContent = true;
                continue;
            }

            // 单个内容块超过一页时，从一张新页开始再切片。
            // 旧版会在这里先 addPage，进入 while 后又 addPage 一次，
            // 因此中间会凭空多出整张白页。
            if (hasContent) {
                pdf.addPage();
            }

            currentY = marginY;

            const pixelsPerMm = canvas.width / usableWidth;
            const fullPagePixels = Math.max(
                1,
                Math.floor(
                    usableHeight * pixelsPerMm
                )
            );

            let startY = 0;
            let firstSlice = true;

            while (startY < canvas.height) {
                if (!firstSlice) {
                    pdf.addPage();
                }

                const sliceHeight = Math.min(
                    findPdfSafeSliceHeight(
                        canvas,
                        startY,
                        fullPagePixels
                    ),
                    canvas.height - startY
                );

                const slice = canvasSlice(
                    canvas,
                    startY,
                    sliceHeight
                );

                const sliceHeightMm = (
                    sliceHeight
                    * usableWidth
                    / canvas.width
                );

                pdf.addImage(
                    slice.toDataURL(
                        "image/jpeg",
                        0.92
                    ),
                    "JPEG",
                    marginX,
                    marginY,
                    usableWidth,
                    sliceHeightMm,
                    undefined,
                    "FAST"
                );

                hasContent = true;
                currentY = marginY + sliceHeightMm + 4;
                startY += sliceHeight;
                firstSlice = false;
            }
        }

        const date = new Date()
            .toISOString()
            .slice(0, 10);

        pdf.save(
            `离散数学错题本-${date}.pdf`
        );
    } catch (error) {
        console.error("错题本 PDF 导出失败：", error);

        window.alert(
            "PDF 生成失败，请刷新页面后重试。"
        );
    } finally {
        exportElement?.remove();

        if (button) {
            button.disabled = false;
            button.textContent = originalText || "导出 PDF";
        }
    }
}


function formatWrongBookGeneratedText(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    // 旧版本已保存的 LaTeX 做“可读化”迁移，避免再次裸露反斜杠。
    value = value.replace(
        /\\begin\{(?:bmatrix|pmatrix|matrix)\}([\s\S]*?)\\end\{(?:bmatrix|pmatrix|matrix)\}/g,
        (_match, body) => {
            const rows = String(body)
                .split(/\\\\/)
                .map(row => row.trim())
                .filter(Boolean)
                .map(row => (
                    "[ "
                    + row
                        .split("&")
                        .map(cell => cell.trim())
                        .join("  ")
                    + " ]"
                ));

            return `\n${rows.join("\n")}\n`;
        }
    );

    value = value
        .replace(/\\xrightarrow\{([^{}]+)\}/g, " —$1→ ")
        .replace(/\\rightarrow/g, "→")
        .replace(/\\Rightarrow/g, "⇒")
        .replace(/\\to/g, "→")
        .replace(/\\neq|\\ne/g, "≠")
        .replace(/\\leq|\\le/g, "≤")
        .replace(/\\geq|\\ge/g, "≥")
        .replace(/\\in\b/g, "∈")
        .replace(/\\notin\b/g, "∉")
        .replace(/\\times/g, "×")
        .replace(/\\cdot/g, "·")
        .replace(/\\land/g, "∧")
        .replace(/\\lor/g, "∨")
        .replace(/\\neg/g, "¬");

    value = value.replace(
        /\b([A-Za-z])_\{?([A-Za-z0-9]+)\}?/g,
        "$1$2"
    );

    value = value.replace(
        /\\text\{([^{}]*)\}/g,
        "$1"
    );

    value = value
        .replace(/\$\$/g, "")
        .replace(/\$/g, "")
        .replace(/\\[;,!]/g, " ")
        .replace(/\\\\/g, "\n");

    // 最后移除仍残留的纯排版命令，保留正文。
    value = value.replace(
        /\\(?:left|right|displaystyle|quad|qquad)\b/g,
        ""
    );

    value = value
        .replace(/[ \t]{2,}/g, " ")
        .replace(/\n{3,}/g, "\n\n")
        .trim();

    return value;
}

function extractAnswerOnlyText(text) {
    let value = String(text || "").trim();

    if (!value) return "";

    const marker = value.match(
        /\[\[ANSWER_ONLY\]\]([\s\S]*?)\[\[\/ANSWER_ONLY\]\]/i
    );

    if (marker) {
        value = marker[1].trim();
    }

    // 去掉模型常见客套开头。
    value = value.replace(
        /^(?:好的[，,。]?\s*)?(?:以下是)?(?:这道题的)?(?:最终)?答案(?:是|为)?[：:\s]*/i,
        ""
    ).trim();

    // 一旦进入解析/理由/过程，后面全部不要。
    const stopPatterns = [
        /\n\s*(?:#{1,6}\s*)?(?:解析|理由|过程|推导|说明|易错点)\s*[:：]?/i,
        /\n\s*(?:因为|所以)\b/,
    ];

    let end = value.length;

    for (const pattern of stopPatterns) {
        const match = value.match(pattern);
        if (match && typeof match.index === "number") {
            end = Math.min(end, match.index);
        }
    }

    return value.slice(0, end).trim();
}


function queueWrongQuestionAnswer(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (
        !entry
        || entry.referenceAnswer
        || entry.answer
        || wrongAnswerLoadingIds.has(id)
        || wrongAnswerQueue.includes(id)
    ) {
        return;
    }

    wrongAnswerQueue.push(id);
    runWrongAnswerQueue();
}

async function runWrongAnswerQueue() {
    if (wrongAnswerQueueBusy) {
        return;
    }

    wrongAnswerQueueBusy = true;

    try {
        while (wrongAnswerQueue.length) {
            const id = wrongAnswerQueue.shift();

            await generateWrongQuestionAnswer(
                id,
                {
                    silent: true
                }
            );
        }
    } finally {
        wrongAnswerQueueBusy = false;
    }
}






function toggleWrongAnalysis(id) {
    if (wrongAnalysisExpandedIds.has(id)) {
        wrongAnalysisExpandedIds.delete(id);
    } else {
        wrongAnalysisExpandedIds.add(id);
    }

    renderWrongBook();
}

async function generateWrongQuestionAnswer(
    id,
    {
        silent = false
    } = {}
) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry) return false;

    if (entry.referenceAnswer || entry.answer) {
        return true;
    }

    if (wrongAnswerLoadingIds.has(id)) {
        return false;
    }

    wrongAnswerLoadingIds.add(id);
    renderWrongBook();

    const prompt = [
        "请只给出下面这道离散数学题的最终答案。",
        "绝对不要提供解析、理由、推导、说明、提示，也不要写“因为/所以/由……可得”。",
        "",
        "请严格只返回下面这个机器可读格式：",
        "[[ANSWER_ONLY]]",
        "最终答案",
        "[[/ANSWER_ONLY]]",
        "",
        "答案内部可以使用规范 MathJax LaTeX：",
        "- 行内公式使用 $...$；",
        "- 矩阵/多行公式使用 $$...$$；",
        "- 不要在答案块之外输出任何文字。",
        "",
        "【题目】",
        entry.question
    ].join("\n");

    try {
        const response = await fetch(
            "/chat",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    messages: [
                        {
                            role: "user",
                            content: prompt
                        }
                    ]
                })
            }
        );

        const data = await parseResponseJson(
            response
        );

        if (
            !response.ok
            || data.error
            || typeof data.reply !== "string"
            || !data.reply.trim()
        ) {
            if (!silent) {
                window.alert(
                    data.error
                    || "答案生成失败，请稍后重试。"
                );
            }
            return false;
        }

        entry.answer = extractAnswerOnlyText(
            data.reply
        ).slice(0, 3000);

        entry.answerUpdatedAt = Date.now();
        entry.updatedAt = Date.now();

        saveLearningState();
        renderWrongBook();
        return true;

    } catch (error) {
        console.error("错题答案生成失败：", error);

        if (!silent) {
            window.alert(
                "网络连接失败，暂时无法生成答案。"
            );
        }

        return false;

    } finally {
        wrongAnswerLoadingIds.delete(id);
        renderWrongBook();
    }
}

async function generateWrongQuestionAnalysis(id) {
    const entry = learningState.wrongQuestions.find(
        item => item.id === id
    );

    if (!entry) return;

    if (entry.analysis) {
        wrongAnalysisExpandedIds.add(id);
        renderWrongBook();
        return;
    }

    if (wrongAnalysisLoadingIds.has(id)) {
        return;
    }

    wrongAnalysisLoadingIds.add(id);
    renderWrongBook();

    const knownAnswer = (
        entry.referenceAnswer
        || entry.answer
        || ""
    );

    const prompt = [
        "请为下面这道离散数学错题提供完整解析，直接讲解，不要反问学生。",
        "",
        "内容要求：",
        "1. 已知最终答案如下，先核对后围绕它解释：",
        knownAnswer || "（暂无参考答案）",
        "2. 分步骤写关键推理；",
        "3. 解析要清楚，但不要重复抄题或堆废话；",
        "4. 最后给一条易错点。",
        "",
        "数学格式必须严格使用 MathJax 可解析的标准 LaTeX：",
        "- 行内公式使用 $...$；",
        "- 独立公式、矩阵、cases、多行推导使用 $$...$$；",
        "- 矩阵必须写成 $$\\\\begin{bmatrix}...\\\\end{bmatrix}$$；",
        "- 下标写 $v_1$、$a_{ij}$；",
        "- 路径可以写 $v_1\\\\to v_2\\\\to v_3$；",
        "- 所有 $ 必须成对闭合；",
        "- 不允许裸露 \\\\begin{...}、\\\\to、v_1 这类未被数学定界符包裹的 LaTeX。",
        "",
        "【错题】",
        entry.question
    ].join("\n");

    try {
        const response = await fetch(
            "/chat",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    messages: [
                        {
                            role: "user",
                            content: prompt
                        }
                    ]
                })
            }
        );

        const data = await parseResponseJson(
            response
        );

        if (
            !response.ok
            || data.error
            || typeof data.reply !== "string"
            || !data.reply.trim()
        ) {
            window.alert(
                data.error
                || "解析生成失败，请稍后重试。"
            );
            return;
        }

        entry.analysis = data.reply.trim().slice(
            0,
            8000
        );

        entry.analysisUpdatedAt = Date.now();
        entry.updatedAt = Date.now();

        wrongAnalysisExpandedIds.add(id);
        saveLearningState();
        renderWrongBook();

    } catch (error) {
        console.error("错题解析生成失败：", error);
        window.alert(
            "网络连接失败，暂时无法生成解析。"
        );
    } finally {
        wrongAnalysisLoadingIds.delete(id);
        renderWrongBook();
    }
}


function shouldShowWrongBookFeedback(item) {
    const text = String(item?.feedback || "").trim();

    if (!text) return false;

    if (
        item?.source === "manual"
        && (
            text.includes("加入错题本")
            || text.includes("完成订正后")
            || text.includes("手动加入")
        )
    ) {
        return false;
    }

    return true;
}

function renderWrongBook() {
    const list = document.getElementById("wrongBookList");
    if (!list) return;

    list.innerHTML = "";

    const allItems = [...learningState.wrongQuestions];
    const items = getFilteredWrongBookItems();

    updateWrongBookToolbar(allItems, items);

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "wrong-empty";

        if (!allItems.length) {
            empty.textContent = "错题本还是空的。";
        } else if (wrongBookSearch) {
            empty.textContent = "没有找到匹配的错题。";
        } else if (wrongBookFilter === "pending") {
            empty.textContent = "目前没有待处理的错题。";
        } else if (wrongBookFilter === "corrected") {
            empty.textContent = "目前没有已完成订正但未通过复测的错题。";
        } else {
            empty.textContent = "目前还没有已通过复测的错题。";
        }

        list.appendChild(empty);
        return;
    }

    for (const item of items) {
        const card = document.createElement("div");
        card.className = "wrong-card";

        const top = document.createElement("div");
        top.className = "wrong-card-top";

        const statusInfo = wrongBookStatus(item);
        const status = document.createElement("span");
        status.className = [
            "wrong-status",
            statusInfo.className
        ]
            .filter(Boolean)
            .join(" ");
        status.textContent = statusInfo.text;

        const date = document.createElement("span");
        date.className = "wrong-date";
        date.textContent = formatLearningDate(item.updatedAt);

        top.appendChild(status);
        top.appendChild(date);

        const difficulty = ["简单", "中等", "困难"].includes(item.difficulty)
            ? item.difficulty
            : "";
        const difficultyBadge = difficulty
            ? document.createElement("div")
            : null;

        if (difficultyBadge) {
            difficultyBadge.className = "difficulty-badge";
            difficultyBadge.textContent = difficulty;
        }

        const question = document.createElement("div");
        question.className = "wrong-question";
        question.innerHTML = markdownToHtml(item.question);

        const meta = document.createElement("div");
        meta.className = "wrong-meta";

        const appendMetaRow = (
            label,
            value,
            className = ""
        ) => {
            if (!value) return;

            const row = document.createElement("div");
            row.className = [
                "wrong-meta-row",
                className
            ]
                .filter(Boolean)
                .join(" ");

            const labelNode = document.createElement("span");
            labelNode.className = "wrong-meta-label";
            labelNode.textContent = label;

            const valueNode = document.createElement("span");
            valueNode.className = "wrong-meta-value";
            valueNode.textContent = value;

            row.appendChild(labelNode);
            row.appendChild(valueNode);
            meta.appendChild(row);
        };

        if (item.focusPoints.length) {
            appendMetaRow(
                "本题难点",
                item.focusPoints.join("、"),
                "focus"
            );
        }

        if (item.knowledgePoints.length) {
            appendMetaRow(
                "整题涉及",
                item.knowledgePoints.join("、")
            );
        }

        if (item.retestCount) {
            appendMetaRow(
                "复测情况",
                `${item.retestCount} 次，通过 ${item.retestPassCount} 次`
            );
        }

        const feedback = document.createElement("div");
        feedback.className = "wrong-feedback";

        if (shouldShowWrongBookFeedback(item)) {
            const prefixNode = document.createElement("strong");
            prefixNode.textContent = "最近反馈";

            const feedbackBody = document.createElement("div");
            feedbackBody.className = "wrong-feedback-body";
            feedbackBody.innerHTML = markdownToHtml(item.feedback);

            feedback.appendChild(prefixNode);
            feedback.appendChild(feedbackBody);
        }

        const note = document.createElement("div");
        note.className = "wrong-note";

        if (item.note) {
            const noteTitle = document.createElement("strong");
            noteTitle.textContent = "我的笔记：";

            const noteBody = document.createElement("div");
            noteBody.className = "wrong-note-body";
            noteBody.innerHTML = markdownToHtml(item.note);

            note.appendChild(noteTitle);
            note.appendChild(noteBody);
        }

        const retest = document.createElement("div");
        retest.className = "wrong-retest";

        if (item.lastRetestAt) {
            const resultText = item.lastRetestResult === "correct"
                ? "最近复测：通过"
                : (
                    item.lastRetestResult === "wrong"
                        ? "最近复测：未通过"
                        : "最近复测：尚未确认"
                );

            retest.textContent = resultText;
        }

        const answerDetails = document.createElement("details");
        answerDetails.className = "wrong-answer-details";

        const answerSummary = document.createElement("summary");
        answerSummary.className = "wrong-answer-summary";

        if (
            item.referenceAnswer
            || item.answer
        ) {
            answerSummary.textContent = "查看答案";
        } else if (wrongAnswerLoadingIds.has(item.id)) {
            answerSummary.textContent = "查看答案 · 正在准备";
        } else {
            answerSummary.textContent = "查看答案";
        }

        const answerInner = document.createElement("div");
        answerInner.className = "wrong-answer-inner";

        const visibleAnswer = (
            item.referenceAnswer
            || item.answer
            || ""
        );

        if (visibleAnswer) {
            answerInner.innerHTML = markdownToHtml(
                visibleAnswer
            );
        } else {
            answerInner.textContent = wrongAnswerLoadingIds.has(item.id)
                ? "答案正在后台准备，请稍等。"
                : "答案尚未准备，已重新加入生成队列。";
        }

        answerDetails.appendChild(answerSummary);
        answerDetails.appendChild(answerInner);

        answerDetails.addEventListener(
            "toggle",
            () => {
                if (
                    answerDetails.open
                    && !item.referenceAnswer
                    && !item.answer
                ) {
                    queueWrongQuestionAnswer(
                        item.id
                    );
                }
            }
        );

        const analysisBox = document.createElement("div");
        analysisBox.className = "wrong-analysis-box";

        if (item.analysis) {
            const analysisDetails = document.createElement("details");
            analysisDetails.className = "wrong-analysis-details";
            analysisDetails.open = wrongAnalysisExpandedIds.has(
                item.id
            );

            const analysisSummary = document.createElement("summary");
            analysisSummary.className = "wrong-analysis-summary";
            analysisSummary.textContent = "查看解析";

            const analysisBody = document.createElement("div");
            analysisBody.className = "wrong-analysis-body";
            analysisBody.innerHTML = markdownToHtml(
                item.analysis
            );

            analysisDetails.appendChild(analysisSummary);
            analysisDetails.appendChild(analysisBody);

            analysisDetails.addEventListener(
                "toggle",
                () => {
                    if (analysisDetails.open) {
                        wrongAnalysisExpandedIds.add(item.id);
                    } else {
                        wrongAnalysisExpandedIds.delete(item.id);
                    }
                }
            );

            analysisBox.appendChild(analysisDetails);
        }

        const actions = document.createElement("div");
        actions.className = "wrong-actions";

        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "secondary";
        copyButton.textContent = "复制";
        copyButton.title = "复制这道错题及当前已有内容；公式优先保留视觉渲染";
        copyButton.onclick = () => copyRenderedNode(card);
        actions.appendChild(copyButton);

        if (!item.analysis) {
            const analysisButton = document.createElement("button");
            analysisButton.type = "button";
            analysisButton.className = "secondary";

            if (wrongAnalysisLoadingIds.has(item.id)) {
                analysisButton.textContent = "正在生成解析…";
                analysisButton.disabled = true;
            } else {
                analysisButton.textContent = "生成解析";
            }

            analysisButton.onclick = () => (
                generateWrongQuestionAnalysis(item.id)
            );

            actions.appendChild(analysisButton);
        }

        if (!item.corrected) {
            const correctedButton = document.createElement("button");
            correctedButton.type = "button";
            correctedButton.textContent = "完成订正";
            correctedButton.onclick = () => (
                markWrongQuestionCorrected(item.id)
            );
            actions.appendChild(correctedButton);
        }

        const retestButton = document.createElement("button");
        retestButton.type = "button";
        retestButton.className = item.corrected || item.retestPassed
            ? ""
            : "secondary";
        retestButton.textContent = item.retestPassed
            ? "再测一次"
            : "再测一道";
        retestButton.disabled = !item.corrected && !item.retestPassed;
        retestButton.title = retestButton.disabled
            ? "先完成订正，再进行同知识点复测"
            : "生成一道同知识点、难度相近的新题进行验证";
        retestButton.onclick = () => (
            startWrongQuestionRetest(item.id)
        );
        actions.appendChild(retestButton);

        const hasRetestSession = (
            item.lastRetestSessionId !== null
            && sessions.some(
                session => String(session.id) === String(item.lastRetestSessionId)
            )
        );

        if (hasRetestSession) {
            const retestHistoryButton = document.createElement("button");
            retestHistoryButton.type = "button";
            retestHistoryButton.className = "secondary";
            retestHistoryButton.textContent = "查看最近复测";
            retestHistoryButton.onclick = () => (
                openWrongRetestSession(item.id)
            );
            actions.appendChild(retestHistoryButton);
        }

        const editButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "secondary";
        editButton.textContent = "编辑/笔记";
        editButton.onclick = () => openWrongEdit(item.id);
        actions.appendChild(editButton);

        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "secondary danger";
        removeButton.textContent = "移出错题本";
        removeButton.onclick = () => (
            removeWrongQuestion(item.id)
        );
        actions.appendChild(removeButton);

        card.appendChild(top);
        if (difficultyBadge) {
            card.appendChild(difficultyBadge);
        }
        card.appendChild(question);

        if (meta.textContent) {
            card.appendChild(meta);
        }

        if (feedback.textContent.trim()) {
            card.appendChild(feedback);
        }

        if (item.note) {
            card.appendChild(note);
        }

        if (retest.textContent) {
            card.appendChild(retest);
        }

        card.appendChild(answerDetails);

        if (analysisBox.childNodes.length) {
            card.appendChild(analysisBox);
        }

        card.appendChild(actions);
        list.appendChild(card);

        renderMath(question);
        renderMath(feedback);
        renderMath(note);
        renderMath(answerDetails);
        renderMath(analysisBox);
    }
}


function isGenericTeachingCategory(value) {
    const text = String(value || "").trim();
    return !text || text === "待识别" || text === "离散数学综合";
}

function getFriendlyCategory(value) {
    const text = String(value || "").trim();

    if (isGenericTeachingCategory(text)) {
        return "正在重新判定";
    }

    return text;
}

function getFriendlyQuestionType(value) {
    const text = String(value || "").trim();

    if (!text) {
        return "综合问题";
    }

    if (text === "综合题") {
        return "综合问题";
    }

    if (text === "出题请求") {
        return "练习题需求";
    }

    if (text === "答案检查") {
        return "答案检查";
    }

    return text;
}

function getFriendlyMode(value) {
    const text = String(value || "").trim();

    if (!text || text === "提示引导") {
        return "先给思路和提示";
    }

    if (text === "完整解析") {
        return "直接讲完整解法";
    }

    if (text === "概念讲解") {
        return "先解释概念";
    }

    if (text === "练习出题") {
        return "给你出练习题";
    }

    if (text === "答案诊断") {
        return "帮你检查答案";
    }

    return text;
}

function getFriendlyConfidence(value) {
    const text = String(value || "").trim();

    if (!text || text === "低") {
        return "不太确定";
    }

    if (text === "中") {
        return "比较确定";
    }

    if (text === "高") {
        return "较确定";
    }

    return text;
}

function getFriendlyInputSource(value) {
    const text = String(value || "").trim();

    if (!text || text === "文本输入") {
        return "手动输入";
    }

    if (text === "图片识题") {
        return "图片识题";
    }

    return text;
}


// -----------------------------
// 本地持久化
// -----------------------------
function saveState() {
    try {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({
                sessions,
                currentId
            })
        );
    } catch (error) {
        console.warn("本地会话保存失败：", error);
    }
    scheduleCloudSync();
}

function loadState() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return false;

        const data = JSON.parse(raw);
        if (!data || !Array.isArray(data.sessions)) {
            return false;
        }

        const loadedSessions = [];

        for (const session of data.sessions) {
            if (
                !session
                || typeof session !== "object"
                || !Array.isArray(session.messages)
            ) {
                continue;
            }

            const messages = [];

            for (const message of session.messages) {
                if (
                    !message
                    || typeof message !== "object"
                    || !["user", "ai"].includes(message.role)
                ) {
                    continue;
                }

                const text = typeof message.text === "string"
                    ? message.text
                    : String(message.text ?? "");

                if (!text.trim()) continue;

                messages.push({
                    role: message.role,
                    text,
                    source: message.source === "ocr" ? "ocr" : undefined,
                    apiText: typeof message.apiText === "string"
                        ? message.apiText
                        : undefined,
                    generatedExercise: Boolean(
                        message.generatedExercise
                    ),
                    generatedQuestion: typeof message.generatedQuestion === "string"
                        ? message.generatedQuestion
                        : "",
                    generatedAnswer: typeof message.generatedAnswer === "string"
                        ? message.generatedAnswer
                        : "",
                    generatedTeaching: normalizeTeaching(
                        message.generatedTeaching
                    ),
                    questionTeaching: normalizeTeaching(
                        message.questionTeaching
                    ),
                    isRetestPrompt: Boolean(message.isRetestPrompt),
                    isRetestAnswer: Boolean(message.isRetestAnswer),
                    isError: Boolean(message.isError),
                    isNotice: Boolean(message.isNotice)
                });
            }

            loadedSessions.push({
                id: session.id,
                name: typeof session.name === "string" && session.name.trim()
                    ? session.name
                    : "新对话",
                messages,
                teaching: normalizeTeaching(session.teaching),
                learningQuestion: normalizeLearningQuestion(
                    session.learningQuestion
                ),
                retest: normalizeRetestSession(session.retest)
            });
        }

        sessions = loadedSessions;

        // 允许“零会话”作为一个合法的持久化状态。
        // 这样用户删除最后一个对话后，刷新页面也不会自动长回来。
        if (!sessions.length) {
            currentId = null;
            return true;
        }

        const savedIdExists = sessions.some(
            session => session.id === data.currentId
        );

        currentId = savedIdExists
            ? data.currentId
            : sessions[0].id;

        return true;

    } catch (error) {
        console.warn("本地会话读取失败：", error);
        return false;
    }
}


// -----------------------------
// Markdown / MathJax
// -----------------------------
function escapeRawHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function protectMathForMarkdown(source) {
    const mathSegments = [];

    const stash = match => {
        const index = mathSegments.length;
        mathSegments.push(match);
        return `MATHPROTECTTOKEN${index}ENDTOKEN`;
    };

    let protectedText = String(source ?? "");

    // 在 marked 解析 Markdown 之前先藏起公式。
    // 否则 _、*、\begin{cases} 等可能被 Markdown 当成强调语法。
    protectedText = protectedText.replace(
        /\$\$[\s\S]*?\$\$/g,
        stash
    );

    protectedText = protectedText.replace(
        /\\\[[\s\S]*?\\\]/g,
        stash
    );

    protectedText = protectedText.replace(
        /\\\([\s\S]*?\\\)/g,
        stash
    );

    protectedText = protectedText.replace(
        /\$(?!\$)(?:\\.|[^$\n])+\$/g,
        stash
    );

    return {
        protectedText,
        mathSegments
    };
}

function restoreMathAfterMarkdown(html, mathSegments) {
    let restored = String(html ?? "");

    for (let index = 0; index < mathSegments.length; index += 1) {
        const token = `MATHPROTECTTOKEN${index}ENDTOKEN`;
        const safeMath = escapeRawHtml(mathSegments[index]);

        restored = restored
            .split(token)
            .join(safeMath);
    }

    return restored;
}

function repairBareLatexTextSegment(segment) {
    const source = String(segment || "");

    if (!source) return "";

    return source
        .split("\n")
        .map(line => {
            const trimmed = line.trim();

            if (!trimmed) return line;

            // 对“整行几乎就是公式”的裸 LaTeX 先做块级包裹。
            // 先处理这一层，避免后面的单命令修复把一个完整公式拆成很多小块。
            if (
                !trimmed.includes("$")
                && !/[\u4e00-\u9fff]/.test(trimmed)
                && /\\(?:frac|binom|sqrt|sum|prod|cup|cap|lor|land|neg|operatorname|to|rightarrow|Rightarrow)\b/.test(trimmed)
                && /^[A-Za-z0-9\s\\{}()[\]|=+\-*/!,.^_:<>]+$/.test(trimmed)
            ) {
                const indent = line.match(/^\s*/)?.[0] || "";
                return `${indent}$$${trimmed}$$`;
            }

            let value = line;

            // 正文里偶尔会出现单独裸露的 LaTeX 运算符。只包裹命令本身，
            // 避免把旁边的中文一起塞进 MathJax。
            value = value.replace(
                /(?<![$\\])\\(lor|land|neg|cup|cap|in|notin|subseteq|subset|supseteq|supset|leq|le|geq|ge|neq|to|rightarrow|Rightarrow)(?![A-Za-z])/g,
                match => `$${match}$`
            );

            // 路径类表达式：v_1 \to v_2 \to v_3
            value = value.replace(
                /((?:[A-Za-z]_(?:\{[^}\n]+\}|[A-Za-z0-9]+)|[A-Za-z][0-9]+)(?:\s*\\(?:to|rightarrow|Rightarrow|xrightarrow\{[^}\n]+\})\s*(?:[A-Za-z]_(?:\{[^}\n]+\}|[A-Za-z0-9]+)|[A-Za-z][0-9]+))+)/g,
                match => `$${match}$`
            );

            // 单个常见上下标/幂表达式低风险包裹。
            value = value.replace(
                /(?<![$A-Za-z0-9])([A-Za-z](?:_\{[^}\n]{1,30}\}|_[A-Za-z0-9]{1,12}|\^\{[^}\n]{1,30}\}|\^[A-Za-z0-9]{1,8}))(?![$A-Za-z0-9])/g,
                match => `$${match}$`
            );

            return value;
        })
        .join("\n");
}

function prepareAiDisplayText(text) {
    let value = String(text ?? "");

    if (!value) return "";

    // 裸矩阵/cases/aligned 只在它们尚未处在 $$ 中时补块公式。
    value = value.replace(
        /(^|\n)(\s*)(\\begin\{(bmatrix|pmatrix|matrix|cases|aligned)\}[\s\S]*?\\end\{\3\})(?=\n|$)/g,
        (_match, prefix, indent, math, _env, offset, full) => {
            const before = full.slice(
                Math.max(0, offset - 4),
                offset
            );

            if (/\$\$\s*$/.test(before)) {
                return _match;
            }

            return `${prefix}${indent}$$\n${math}\n$$`;
        }
    );

    // 只修复数学定界符外的文本，避免破坏已经正确的 MathJax。
    const parts = value.split(/(\$\$[\s\S]*?\$\$|\$[^$\n]*\$|```[\s\S]*?```|`[^`\n]*`)/g);

    return parts.map(part => {
        if (
            /^\$\$/.test(part)
            || /^\$/.test(part)
            || /^```/.test(part)
            || /^`/.test(part)
        ) {
            return part;
        }

        return repairBareLatexTextSegment(part);
    }).join("");
}


function markdownToHtml(text) {
    const source = String(text ?? "");

    const {
        protectedText,
        mathSegments
    } = protectMathForMarkdown(source);

    const rawHtml = marked.parse(protectedText);

    const safeHtml = window.DOMPurify
        ? window.DOMPurify.sanitize(rawHtml)
        : marked.parse(escapeRawHtml(protectedText));

    return restoreMathAfterMarkdown(
        safeHtml,
        mathSegments
    );
}

function renderMath(target) {
    if (!window.MathJax || !MathJax.typesetPromise) {
        return Promise.resolve();
    }

    return MathJax.typesetPromise(
        target ? [target] : undefined
    ).catch(error => {
        console.warn("MathJax 渲染失败：", error);
    });
}


// -----------------------------
// 第三阶段：富文本 / 公式复制
// -----------------------------
function copyMathLatex(mathContainer) {
    if (!mathContainer) return "";

    const math = mathContainer.querySelector(
        "mjx-assistive-mml math, .MJX_Assistive_MathML math, math[alttext]"
    );

    const alt = math?.getAttribute?.("alttext");
    if (alt && alt.trim()) return alt.trim();

    const aria = mathContainer.getAttribute?.("aria-label");
    if (aria && aria.trim()) return aria.trim();

    return "";
}

function clipboardSvgDataUrl(svg) {
    if (!svg) return "";

    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.style.color = "#111827";

    clone.querySelectorAll('[fill="currentColor"]').forEach(
        node => node.setAttribute("fill", "#111827")
    );
    clone.querySelectorAll('[stroke="currentColor"]').forEach(
        node => node.setAttribute("stroke", "#111827")
    );

    const serialized = new XMLSerializer().serializeToString(clone);
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialized)}`;
}

function flattenClipboardDetails(root) {
    root.querySelectorAll("details").forEach(details => {
        const block = document.createElement("div");
        block.style.margin = "8px 0";

        const summary = details.querySelector(":scope > summary");
        if (summary) {
            const heading = document.createElement("div");
            heading.style.fontWeight = "700";
            heading.style.marginBottom = "5px";
            heading.textContent = summary.textContent || "";
            block.appendChild(heading);
        }

        [...details.childNodes].forEach(child => {
            if (child === summary) return;
            block.appendChild(child.cloneNode(true));
        });

        details.replaceWith(block);
    });
}

function stripClipboardControls(root) {
    root.querySelectorAll(
        [
            "script",
            "style",
            "button",
            "input",
            "textarea",
            "select",
            ".msg-actions",
            ".wrong-actions",
            ".kg-history-actions",
            ".copy-compact",
            ".rich-copy-button",
            ".graph-side-copy",
            ".modal-close-dot"
        ].join(",")
    ).forEach(node => node.remove());

    root.querySelectorAll("[hidden], .hidden").forEach(node => node.remove());
}

function replaceClipboardMathForPlain(root) {
    root.querySelectorAll("mjx-container").forEach(container => {
        const latex = copyMathLatex(container);
        const display = container.getAttribute("display") === "true";
        const fallback = latex
            ? (display ? `\n$$${latex}$$\n` : `$${latex}$`)
            : (container.textContent || "");
        container.replaceWith(document.createTextNode(fallback));
    });

    root.querySelectorAll(
        "mjx-assistive-mml, .MJX_Assistive_MathML, [data-mjx-assistive-mml]"
    ).forEach(node => node.remove());
}

function replaceClipboardMathForHtml(root) {
    root.querySelectorAll("mjx-container").forEach(container => {
        const svg = container.querySelector("svg");
        const latex = copyMathLatex(container);
        const display = container.getAttribute("display") === "true";

        if (!svg) {
            if (latex) {
                const fallback = document.createElement(display ? "div" : "span");
                fallback.textContent = display ? `$$${latex}$$` : `$${latex}$`;
                container.replaceWith(fallback);
            }
            return;
        }

        const image = document.createElement("img");
        image.src = clipboardSvgDataUrl(svg);
        image.alt = latex ? (display ? `$$${latex}$$` : `$${latex}$`) : "数学公式";
        image.setAttribute("data-latex", latex || "");

        const rect = svg.getBoundingClientRect();
        if (rect.width > 0) image.style.width = `${rect.width}px`;
        if (rect.height > 0) image.style.height = `${rect.height}px`;
        image.style.maxWidth = "100%";
        image.style.objectFit = "contain";

        if (display) {
            const wrapper = document.createElement("div");
            wrapper.style.textAlign = "center";
            wrapper.style.margin = "8px 0";
            wrapper.appendChild(image);
            container.replaceWith(wrapper);
        } else {
            image.style.display = "inline-block";
            image.style.verticalAlign = "middle";
            image.style.margin = "0 2px";
            container.replaceWith(image);
        }
    });

    root.querySelectorAll(
        "mjx-assistive-mml, .MJX_Assistive_MathML, [data-mjx-assistive-mml]"
    ).forEach(node => node.remove());
}

function applyClipboardRichStyles(root) {
    root.style.fontFamily = 'Arial, "Microsoft YaHei", "PingFang SC", sans-serif';
    root.style.lineHeight = "1.6";

    root.querySelectorAll("table").forEach(table => {
        table.style.borderCollapse = "collapse";
        table.style.margin = "8px 0";
    });

    root.querySelectorAll("th, td").forEach(cell => {
        cell.style.border = "1px solid #94a3b8";
        cell.style.padding = "5px 8px";
        cell.style.verticalAlign = "top";
    });

    root.querySelectorAll("pre").forEach(pre => {
        pre.style.whiteSpace = "pre-wrap";
        pre.style.wordBreak = "break-word";
        pre.style.padding = "9px 11px";
        pre.style.border = "1px solid #cbd5e1";
        pre.style.borderRadius = "6px";
        pre.style.background = "#f8fafc";
    });

    root.querySelectorAll("code").forEach(code => {
        code.style.fontFamily = 'Consolas, "SFMono-Regular", monospace';
    });

    root.querySelectorAll("blockquote").forEach(block => {
        block.style.marginLeft = "0";
        block.style.paddingLeft = "10px";
        block.style.borderLeft = "3px solid #94a3b8";
    });

    root.querySelectorAll("h1,h2,h3,h4").forEach(heading => {
        heading.style.margin = "10px 0 6px";
        heading.style.fontWeight = "700";
    });

    root.querySelectorAll("p").forEach(paragraph => {
        paragraph.style.margin = "0 0 8px";
    });

    root.querySelectorAll("ul,ol").forEach(list => {
        list.style.paddingLeft = "24px";
        list.style.margin = "6px 0 10px";
    });

    root.querySelectorAll("li").forEach(item => {
        item.style.margin = "2px 0";
    });

    root.querySelectorAll("strong,b").forEach(node => {
        node.style.fontWeight = "700";
    });

    root.querySelectorAll("em,i").forEach(node => {
        node.style.fontStyle = "italic";
    });

    root.querySelectorAll("a").forEach(link => {
        link.style.textDecoration = "underline";
    });

    root.querySelectorAll("hr").forEach(rule => {
        rule.style.border = "0";
        rule.style.borderTop = "1px solid #cbd5e1";
        rule.style.margin = "10px 0";
    });
}

function cloneClipboardRoot(node) {
    const wrapper = document.createElement("div");

    if (node instanceof DocumentFragment) {
        wrapper.appendChild(node.cloneNode(true));
    } else if (node) {
        wrapper.appendChild(node.cloneNode(true));
    }

    return wrapper;
}

function clipboardPlainTextFromRoot(root) {
    const plainRoot = root.cloneNode(true);
    flattenClipboardDetails(plainRoot);
    stripClipboardControls(plainRoot);
    replaceClipboardMathForPlain(plainRoot);

    const holder = document.createElement("div");
    holder.style.position = "fixed";
    holder.style.left = "-100000px";
    holder.style.top = "0";
    holder.style.width = "900px";
    holder.style.whiteSpace = "normal";
    holder.appendChild(plainRoot);
    document.body.appendChild(holder);

    const text = (holder.innerText || holder.textContent || "")
        .replace(/\u00a0/g, " ")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();

    holder.remove();
    return text;
}

function clipboardHtmlFromRoot(root) {
    const htmlRoot = root.cloneNode(true);
    flattenClipboardDetails(htmlRoot);
    stripClipboardControls(htmlRoot);
    replaceClipboardMathForHtml(htmlRoot);
    applyClipboardRichStyles(htmlRoot);
    return htmlRoot.innerHTML.trim();
}

function buildClipboardPayload(node) {
    const root = cloneClipboardRoot(node);
    return {
        text: clipboardPlainTextFromRoot(root),
        html: clipboardHtmlFromRoot(root)
    };
}

function showCopyToast(message = "已复制") {
    document.querySelectorAll(".copy-toast").forEach(node => node.remove());
    const toast = document.createElement("div");
    toast.className = "copy-toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 1200);
}

async function writeRichClipboard(payload) {
    const text = String(payload?.text || "");
    const html = String(payload?.html || "");

    if (
        navigator.clipboard?.write
        && window.ClipboardItem
        && html
    ) {
        try {
            const item = new ClipboardItem({
                "text/plain": new Blob([text], { type: "text/plain" }),
                "text/html": new Blob([html], { type: "text/html" })
            });
            await navigator.clipboard.write([item]);
            return true;
        } catch (error) {
            console.warn("富文本剪贴板写入失败，降级为纯文本：", error);
        }
    }

    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (error) {
            console.warn("剪贴板文本写入失败：", error);
        }
    }

    const legacy = document.createElement("div");
    legacy.contentEditable = "true";
    legacy.style.position = "fixed";
    legacy.style.left = "-100000px";
    legacy.style.top = "0";
    legacy.style.width = "900px";
    legacy.innerHTML = html || escapeRawHtml(text).replace(/\n/g, "<br>");
    document.body.appendChild(legacy);

    const range = document.createRange();
    range.selectNodeContents(legacy);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    legacy.focus();

    const ok = document.execCommand("copy");
    selection.removeAllRanges();
    legacy.remove();
    return ok;
}

async function copyRenderedNode(node, successText = "已复制") {
    if (!node) return false;
    const payload = buildClipboardPayload(node);
    if (!payload.text && !payload.html) return false;

    const ok = await writeRichClipboard(payload);
    if (ok) showCopyToast(successText);
    return ok;
}

function effectiveElementBackground(element) {
    let current = element;

    while (current instanceof Element) {
        const color = getComputedStyle(current).backgroundColor;
        if (
            color
            && color !== "transparent"
            && color !== "rgba(0, 0, 0, 0)"
        ) {
            return color;
        }
        current = current.parentElement;
    }

    return "#ffffff";
}

function buildKnowledgeGraphImageCopyTarget() {
    const canvas = document.getElementById("knowledgeGraphCanvas");
    if (!canvas) return null;

    const mobileStage = canvas.querySelector?.(".kg-mobile-stage");
    const svg = canvas.querySelector?.(".kg-svg");
    const source = mobileStage || svg;
    if (!source) return null;

    let width = 1;
    let height = 1;
    let clone = null;

    if (mobileStage) {
        // 手机端已经不再使用 .kg-svg 作为完整图谱主体，而是
        // HTML 节点 + 一层 SVG 连线。旧逻辑只找 .kg-svg，导致手机端
        // 点击“复制图谱”直接返回 null，看起来就像按钮完全没有作用。
        width = Math.ceil(
            mobileStage.scrollWidth
            || parseFloat(mobileStage.style.width)
            || mobileStage.getBoundingClientRect().width
            || 1
        );
        height = Math.ceil(
            mobileStage.scrollHeight
            || parseFloat(mobileStage.style.height)
            || mobileStage.getBoundingClientRect().height
            || 1
        );

        clone = mobileStage.cloneNode(true);
        clone.style.position = "relative";
        clone.style.left = "0";
        clone.style.top = "0";
        clone.style.width = `${width}px`;
        clone.style.height = `${height}px`;
        clone.style.minWidth = `${width}px`;
        clone.style.maxWidth = "none";
        clone.style.maxHeight = "none";
        clone.style.margin = "0";
        clone.style.transform = "none";
    } else {
        // 桌面端仍沿用 SVG；复制整张图谱而不是当前滚动窗口。
        let bbox = null;
        try {
            bbox = svg.getBBox();
        } catch (_error) {
            bbox = null;
        }

        const fallbackViewBox = svg.viewBox?.baseVal;
        const padding = 18;
        const x = Number.isFinite(bbox?.x)
            ? bbox.x - padding
            : (fallbackViewBox?.x || 0);
        const y = Number.isFinite(bbox?.y)
            ? bbox.y - padding
            : (fallbackViewBox?.y || 0);
        width = Math.ceil(
            (Number.isFinite(bbox?.width) && bbox.width > 0
                ? bbox.width + padding * 2
                : fallbackViewBox?.width)
            || svg.scrollWidth
            || svg.getBoundingClientRect().width
            || 1
        );
        height = Math.ceil(
            (Number.isFinite(bbox?.height) && bbox.height > 0
                ? bbox.height + padding * 2
                : fallbackViewBox?.height)
            || svg.scrollHeight
            || svg.getBoundingClientRect().height
            || 1
        );

        clone = svg.cloneNode(true);
        clone.setAttribute("viewBox", `${x} ${y} ${width} ${height}`);
        clone.setAttribute("width", String(width));
        clone.setAttribute("height", String(height));
        clone.style.setProperty("width", `${width}px`, "important");
        clone.style.setProperty("height", `${height}px`, "important");
        clone.style.maxWidth = "none";
        clone.style.maxHeight = "none";
        clone.style.display = "block";
        clone.style.overflow = "visible";
        clone.style.background = "transparent";
    }

    const wrapper = document.createElement("div");
    wrapper.className = "kg-copy-render-target";
    wrapper.style.position = "absolute";
    wrapper.style.left = "0";
    wrapper.style.top = `${Math.max(
        document.documentElement.scrollHeight,
        document.body?.scrollHeight || 0
    ) + 80}px`;
    wrapper.style.width = `${width}px`;
    wrapper.style.height = `${height}px`;
    wrapper.style.padding = "0";
    wrapper.style.margin = "0";
    wrapper.style.background = (
        effectiveElementBackground(
            mobileStage?.closest?.(".kg-mobile-viewport") || canvas
        ) || "#07142d"
    );
    wrapper.style.overflow = "visible";
    wrapper.style.pointerEvents = "none";
    wrapper.style.zIndex = "-2147483648";

    wrapper.appendChild(clone);
    document.body.appendChild(wrapper);
    return wrapper;
}

let knowledgeGraphPreparedPngPromise = null;
let knowledgeGraphPreparedPngKey = "";

function knowledgeGraphCopyKey() {
    const canvas = document.getElementById("knowledgeGraphCanvas");
    const mobileStage = canvas?.querySelector?.(".kg-mobile-stage");
    const svg = canvas?.querySelector?.(".kg-svg");
    const source = mobileStage || svg;
    if (!source) return "";

    return [
        knowledgeGraphFilter || "全部",
        knowledgeGraphViewMode,
        knowledgeGraphScope,
        source.scrollWidth || source.getBoundingClientRect().width || 0,
        source.scrollHeight || source.getBoundingClientRect().height || 0,
        source.querySelectorAll?.(".kg-mobile-node, .kg-node")?.length || 0
    ].join("|");
}

async function renderKnowledgeGraphPngBlob() {
    const target = buildKnowledgeGraphImageCopyTarget();
    if (!target) {
        throw new Error("没有可导出的图谱");
    }

    try {
        if (typeof window.html2canvas !== "function") {
            throw new Error("html2canvas 不可用");
        }

        if (document.fonts?.ready) {
            await document.fonts.ready.catch(() => {});
        }

        const exportWidth = Math.ceil(
            target.scrollWidth
            || target.getBoundingClientRect().width
            || 1
        );
        const exportHeight = Math.ceil(
            target.scrollHeight
            || target.getBoundingClientRect().height
            || 1
        );

        const renderedCanvas = await window.html2canvas(target, {
            backgroundColor: effectiveElementBackground(target),
            scale: Math.min(2, window.devicePixelRatio || 1.5),
            useCORS: true,
            logging: false,
            width: exportWidth,
            height: exportHeight,
            windowWidth: Math.max(window.innerWidth, exportWidth),
            windowHeight: Math.max(window.innerHeight, exportHeight),
            scrollX: 0,
            scrollY: 0
        });

        const png = await new Promise(resolve => {
            renderedCanvas.toBlob(resolve, "image/png");
        });

        if (!png) {
            throw new Error("图谱 PNG 生成失败");
        }

        return png;
    } finally {
        target.remove();
    }
}

function prepareKnowledgeGraphPng(force = false) {
    const key = knowledgeGraphCopyKey();
    if (!key) return null;

    if (
        !force
        && knowledgeGraphPreparedPngPromise
        && knowledgeGraphPreparedPngKey === key
    ) {
        return knowledgeGraphPreparedPngPromise;
    }

    knowledgeGraphPreparedPngKey = key;
    knowledgeGraphPreparedPngPromise = renderKnowledgeGraphPngBlob()
        .catch(error => {
            if (knowledgeGraphPreparedPngKey === key) {
                knowledgeGraphPreparedPngPromise = null;
            }
            throw error;
        });

    return knowledgeGraphPreparedPngPromise;
}

function scheduleKnowledgeGraphPngPreparation() {
    const prepare = () => {
        prepareKnowledgeGraphPng().catch(() => {});
    };

    if (typeof window.requestIdleCallback === "function") {
        window.requestIdleCallback(prepare, { timeout: 900 });
    } else {
        window.setTimeout(prepare, 120);
    }
}

function downloadKnowledgeGraphPng(blob) {
    if (!blob) return false;

    try {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `离散数学知识图谱-${knowledgeGraphFilter || "全部"}.png`;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1500);
        return true;
    } catch (error) {
        console.warn("保存图谱 PNG 失败：", error);
        return false;
    }
}

async function copyKnowledgeGraphVisual() {
    const pngPromise = prepareKnowledgeGraphPng();
    if (!pngPromise) {
        showCopyToast("当前没有可复制的图谱");
        return false;
    }

    // 这里绝不再退化为文字。此前把 text/plain 同时塞进 ClipboardItem，
    // 一些安卓浏览器/粘贴目标会优先取文字，看起来就像“复制图谱=复制文字”。
    if (
        navigator.clipboard?.write
        && window.ClipboardItem
        && (
            typeof window.ClipboardItem.supports !== "function"
            || window.ClipboardItem.supports("image/png")
        )
    ) {
        try {
            // Chromium 支持 Promise<Blob> 时，先在用户点击仍然有效的时刻
            // 发起 write，避免等截图完成后丢失剪贴板权限。
            const item = new ClipboardItem({
                "image/png": pngPromise
            });
            await navigator.clipboard.write([item]);
            showCopyToast("图谱图片已复制");
            return true;
        } catch (firstError) {
            console.warn("图谱图片即时复制失败：", firstError);

            // 某些浏览器不接受 Promise<Blob>，再用已经生成好的真实 Blob 试一次。
            try {
                const png = await pngPromise;
                const item = new ClipboardItem({ "image/png": png });
                await navigator.clipboard.write([item]);
                showCopyToast("图谱图片已复制");
                return true;
            } catch (secondError) {
                console.warn("图谱图片 Blob 复制失败：", secondError);
            }
        }
    }

    // 浏览器若根本禁止网页写图片剪贴板，就保存 PNG，而不是偷偷复制文字。
    try {
        const png = await pngPromise;
        if (downloadKnowledgeGraphPng(png)) {
            showCopyToast("浏览器不支持直接复制图片，已保存 PNG");
            return true;
        }
    } catch (error) {
        console.warn("图谱 PNG 生成失败：", error);
    }

    showCopyToast("图谱图片复制失败");
    return false;
}

function selectionNodeElement(node) {
    if (node instanceof Element) return node;
    return node?.parentElement || null;
}

function cloneSelectionContentsForRichCopy(selection) {
    if (!selection || selection.rangeCount < 1) {
        return null;
    }

    const sourceRange = selection.getRangeAt(0);
    const range = sourceRange.cloneRange();

    // 普通文字起选、跨过 MathJax 公式时，浏览器的 Range 只能停在
    // SVG 容器边界。这里仍把这种“跨过公式”的边界补成完整公式，
    // 但不会用于下面的“直接从公式内部起选”路径；后者按字形精确处理。
    const startMath = selectionNodeElement(range.startContainer)
        ?.closest?.("mjx-container");
    const endMath = selectionNodeElement(range.endContainer)
        ?.closest?.("mjx-container");

    try {
        if (startMath && range.intersectsNode(startMath)) {
            range.setStartBefore(startMath);
        }
        if (endMath && range.intersectsNode(endMath)) {
            range.setEndAfter(endMath);
        }
    } catch (error) {
        console.warn("框选公式边界扩展失败，使用原始选择：", error);
        return sourceRange.cloneContents();
    }

    return range.cloneContents();
}

let richMathGranularSelectionState = null;
let richMathGranularDragState = null;

function ensureRichSelectionVisualStyle() {
    if (document.getElementById("richSelectionVisualStyle")) {
        return;
    }

    const style = document.createElement("style");
    style.id = "richSelectionVisualStyle";
    style.textContent = `
        /*
         * 浏览器原生文字选区和 CSS 系统色 Highlight 在部分 Chromium / Edge
         * 环境里并不是同一个蓝色。用户截图里普通文字是深蓝，而 SVG 公式
         * 用 Highlight 会变成更亮的蓝。这里显式统一两类选区的配色：
         * 普通文字仍由浏览器原生 Selection 负责，只统一它的视觉颜色；
         * MathJax SVG 的整块/局部反馈使用完全相同的颜色变量。
         */
        :root {
            --rich-selection-bg: rgb(6, 60, 169);
            --rich-selection-fg: rgb(255, 255, 255);
        }

        ::selection {
            background: var(--rich-selection-bg);
            color: var(--rich-selection-fg);
        }

        ::-moz-selection {
            background: var(--rich-selection-bg);
            color: var(--rich-selection-fg);
        }

        mjx-container.rich-selection-hit > svg {
            background: var(--rich-selection-bg) !important;
            color: var(--rich-selection-fg) !important;
            border-radius: 2px;
            box-decoration-break: clone;
            -webkit-box-decoration-break: clone;
        }

        mjx-container.rich-selection-hit > svg [fill="currentColor"] {
            fill: var(--rich-selection-fg) !important;
        }

        mjx-container.rich-selection-hit > svg [stroke="currentColor"] {
            stroke: var(--rich-selection-fg) !important;
        }

        /*
         * 直接从公式内部拖选时不再把整条公式当成一个原子。
         * 下面按 MathJax SVG 的单个 data-c 字形逐个高亮；局部公式选区
         * 和上面的普通文字原生选区使用同一组颜色变量。
         */
        mjx-container.rich-granular-selection {
            position: relative !important;
            isolation: isolate;
        }

        mjx-container.rich-granular-selection > svg {
            position: relative;
            z-index: 1;
        }

        mjx-container .rich-math-selection-overlay {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: visible;
            pointer-events: none;
            z-index: 0;
        }

        mjx-container .rich-math-selection-piece {
            position: absolute;
            background: var(--rich-selection-bg);
            pointer-events: none;
        }

        mjx-container svg [data-c].rich-glyph-selected {
            fill: var(--rich-selection-fg) !important;
            stroke: var(--rich-selection-fg) !important;
            color: var(--rich-selection-fg) !important;
        }
    `;
    document.head.appendChild(style);
}

function clearRichMathSelectionFeedback() {
    document.querySelectorAll(
        "mjx-container.rich-selection-hit"
    ).forEach(node => {
        node.classList.remove("rich-selection-hit");
    });
}

function clearGranularMathSelectionVisual() {
    document.querySelectorAll(
        ".rich-math-selection-overlay"
    ).forEach(node => node.remove());

    document.querySelectorAll(
        "svg [data-c].rich-glyph-selected"
    ).forEach(node => {
        node.classList.remove("rich-glyph-selected");
    });

    document.querySelectorAll(
        "mjx-container.rich-granular-selection"
    ).forEach(node => {
        node.classList.remove("rich-granular-selection");
    });
}

function clearGranularMathSelection() {
    richMathGranularSelectionState = null;
    clearGranularMathSelectionVisual();
}

function refreshRichMathSelectionFeedback() {
    const selection = window.getSelection();

    clearRichMathSelectionFeedback();

    if (!selection || selection.isCollapsed || selection.rangeCount < 1) {
        return;
    }

    const focusElement = selectionNodeElement(selection.focusNode);
    if (
        focusElement
        && focusElement.closest(
            "input, textarea, [contenteditable='true']"
        )
    ) {
        return;
    }

    const ranges = [];
    for (let i = 0; i < selection.rangeCount; i += 1) {
        ranges.push(selection.getRangeAt(i));
    }

    document.querySelectorAll("mjx-container").forEach(container => {
        // 直接从公式内部起选的这一条公式由逐字形高亮负责，
        // 不能再叠加整块蓝色，否则又退回“整条一起选”的效果。
        if (
            richMathGranularSelectionState?.mathContainer === container
        ) {
            return;
        }

        let intersects = false;

        for (const range of ranges) {
            try {
                if (range.intersectsNode(container)) {
                    intersects = true;
                    break;
                }
            } catch (_error) {
                // 某些浏览器对特殊 SVG/Shadow DOM 节点可能抛异常。
            }
        }

        if (intersects) {
            container.classList.add("rich-selection-hit");
        }
    });
}

function installRichMathSelectionFeedback() {
    ensureRichSelectionVisualStyle();

    let framePending = false;

    const scheduleRefresh = () => {
        if (framePending) return;
        framePending = true;

        requestAnimationFrame(() => {
            framePending = false;
            refreshRichMathSelectionFeedback();
        });
    };

    document.addEventListener("selectionchange", scheduleRefresh);
    window.addEventListener("blur", clearRichMathSelectionFeedback);
}

function mathContainerFromPointerTarget(target) {
    const element = target instanceof Element
        ? target
        : target?.parentElement;

    return element?.closest?.("mjx-container") || null;
}

function mathGlyphNodes(mathContainer) {
    if (!mathContainer) return [];

    return [
        ...mathContainer.querySelectorAll("svg [data-c]")
    ].filter(node => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    });
}

function mathGlyphCharacter(glyph) {
    const code = glyph?.getAttribute?.("data-c") || "";
    if (!/^[0-9A-F]+$/i.test(code)) return "";

    try {
        // MathJax 对拉丁字母经常使用“数学斜体 Unicode”码位。
        // NFKC 后复制出来仍是用户熟悉的 A、R、x 等普通字符。
        return String.fromCodePoint(parseInt(code, 16)).normalize("NFKC");
    } catch (_error) {
        return "";
    }
}

function mathGlyphIndexFromPointer(mathContainer, clientX, clientY) {
    const glyphs = mathGlyphNodes(mathContainer);
    if (!glyphs.length) return -1;

    let nearestIndex = -1;
    let nearestDistance = Infinity;

    for (let i = 0; i < glyphs.length; i += 1) {
        const rect = glyphs[i].getBoundingClientRect();

        if (
            clientX >= rect.left
            && clientX <= rect.right
            && clientY >= rect.top
            && clientY <= rect.bottom
        ) {
            return i;
        }

        const dx = clientX < rect.left
            ? rect.left - clientX
            : clientX > rect.right
                ? clientX - rect.right
                : 0;
        const dy = clientY < rect.top
            ? rect.top - clientY
            : clientY > rect.bottom
                ? clientY - rect.bottom
                : 0;
        const distance = Math.hypot(dx, dy);

        if (distance < nearestDistance) {
            nearestDistance = distance;
            nearestIndex = i;
        }
    }

    return nearestIndex;
}

function granularMathSelectedIndexes(state) {
    if (!state) return [];

    const start = Math.min(state.startIndex, state.endIndex);
    const end = Math.max(state.startIndex, state.endIndex);
    const result = [];

    for (let i = start; i <= end; i += 1) {
        result.push(i);
    }

    return result;
}

function mergeMathSelectionRects(rects) {
    const items = rects
        .filter(rect => rect.width > 0 && rect.height > 0)
        .map(rect => ({ ...rect }))
        .sort((a, b) => {
            const dy = a.top - b.top;
            return Math.abs(dy) > 2 ? dy : a.left - b.left;
        });

    const merged = [];

    for (const rect of items) {
        const expanded = {
            left: rect.left - 0.75,
            top: rect.top - 0.5,
            right: rect.right + 0.75,
            bottom: rect.bottom + 0.5
        };
        expanded.width = expanded.right - expanded.left;
        expanded.height = expanded.bottom - expanded.top;

        const last = merged[merged.length - 1];
        if (!last) {
            merged.push(expanded);
            continue;
        }

        const overlapTop = Math.max(last.top, expanded.top);
        const overlapBottom = Math.min(last.bottom, expanded.bottom);
        const overlapHeight = Math.max(0, overlapBottom - overlapTop);
        const minHeight = Math.max(
            1,
            Math.min(last.height, expanded.height)
        );
        const sameVisualLine = overlapHeight / minHeight >= 0.72;
        const gap = expanded.left - last.right;

        if (sameVisualLine && gap <= 1.75) {
            last.left = Math.min(last.left, expanded.left);
            last.top = Math.min(last.top, expanded.top);
            last.right = Math.max(last.right, expanded.right);
            last.bottom = Math.max(last.bottom, expanded.bottom);
            last.width = last.right - last.left;
            last.height = last.bottom - last.top;
        } else {
            merged.push(expanded);
        }
    }

    return merged;
}

function renderGranularMathSelection(state) {
    clearGranularMathSelectionVisual();

    const mathContainer = state?.mathContainer;
    if (!mathContainer) return;

    const glyphs = mathGlyphNodes(mathContainer);
    const selectedIndexes = granularMathSelectedIndexes(state)
        .filter(index => index >= 0 && index < glyphs.length);

    if (!selectedIndexes.length) return;

    mathContainer.classList.add("rich-granular-selection");

    const containerRect = mathContainer.getBoundingClientRect();
    const rawRects = [];

    selectedIndexes.forEach(index => {
        const glyph = glyphs[index];
        glyph.classList.add("rich-glyph-selected");

        const rect = glyph.getBoundingClientRect();
        rawRects.push({
            left: rect.left - containerRect.left,
            top: rect.top - containerRect.top,
            right: rect.right - containerRect.left,
            bottom: rect.bottom - containerRect.top,
            width: rect.width,
            height: rect.height
        });
    });

    const overlay = document.createElement("span");
    overlay.className = "rich-math-selection-overlay";
    overlay.setAttribute("aria-hidden", "true");

    mergeMathSelectionRects(rawRects).forEach(rect => {
        const piece = document.createElement("span");
        piece.className = "rich-math-selection-piece";
        piece.style.left = `${rect.left}px`;
        piece.style.top = `${rect.top}px`;
        piece.style.width = `${rect.width}px`;
        piece.style.height = `${rect.height}px`;
        overlay.appendChild(piece);
    });

    mathContainer.appendChild(overlay);
}

function mathBoundaryPointFromPointer(mathContainer, clientX) {
    if (!mathContainer?.parentNode) return null;

    const parent = mathContainer.parentNode;
    const siblings = [...parent.childNodes];
    const index = siblings.indexOf(mathContainer);
    if (index < 0) return null;

    const rect = mathContainer.getBoundingClientRect();
    const useAfter = clientX >= (rect.left + rect.width / 2);

    return {
        node: parent,
        offset: index + (useAfter ? 1 : 0),
        mathContainer
    };
}

function caretBoundaryFromViewportPoint(clientX, clientY) {
    let node = null;
    let offset = 0;

    try {
        if (typeof document.caretPositionFromPoint === "function") {
            const position = document.caretPositionFromPoint(
                clientX,
                clientY
            );
            node = position?.offsetNode || null;
            offset = Number(position?.offset || 0);
        } else if (typeof document.caretRangeFromPoint === "function") {
            const range = document.caretRangeFromPoint(
                clientX,
                clientY
            );
            node = range?.startContainer || null;
            offset = Number(range?.startOffset || 0);
        }
    } catch (_error) {
        return null;
    }

    if (!node) return null;

    const mathContainer = selectionNodeElement(node)
        ?.closest?.("mjx-container");

    if (mathContainer) {
        return mathBoundaryPointFromPointer(
            mathContainer,
            clientX
        );
    }

    return { node, offset, mathContainer: null };
}

function collapsedRangeAtBoundary(point) {
    if (!point?.node) return null;

    const range = document.createRange();

    try {
        range.setStart(point.node, point.offset);
        range.collapse(true);
        return range;
    } catch (_error) {
        return null;
    }
}

function compareBoundaryPointToMath(point, mathContainer) {
    const probe = collapsedRangeAtBoundary(point);
    if (!probe || !mathContainer?.parentNode) return 0;

    const before = document.createRange();
    const after = document.createRange();

    try {
        before.setStartBefore(mathContainer);
        before.collapse(true);
        after.setStartAfter(mathContainer);
        after.collapse(true);

        if (
            probe.compareBoundaryPoints(
                Range.START_TO_START,
                before
            ) <= 0
        ) {
            return -1;
        }

        if (
            probe.compareBoundaryPoints(
                Range.START_TO_START,
                after
            ) >= 0
        ) {
            return 1;
        }
    } catch (_error) {
        return 0;
    }

    return 0;
}

function clearNativeDocumentSelection() {
    const selection = window.getSelection();
    if (selection) selection.removeAllRanges();
}

function setNativeSelectionOutsideMath(mathContainer, point, direction) {
    const selection = window.getSelection();
    if (!selection || !point?.node || !mathContainer?.parentNode) {
        return false;
    }

    const range = document.createRange();

    try {
        if (direction > 0) {
            range.setStartAfter(mathContainer);
            range.setEnd(point.node, point.offset);
        } else {
            range.setStart(point.node, point.offset);
            range.setEndBefore(mathContainer);
        }

        selection.removeAllRanges();
        selection.addRange(range);
        return true;
    } catch (_error) {
        return false;
    }
}

function mathSelectionPlainText(state) {
    const glyphs = mathGlyphNodes(state?.mathContainer);
    const selected = granularMathSelectedIndexes(state);

    return selected
        .map(index => mathGlyphCharacter(glyphs[index]))
        .join("");
}

function partialMathSvgPayload(state) {
    const mathContainer = state?.mathContainer;
    const originalSvg = mathContainer?.querySelector?.("svg");
    if (!originalSvg) return null;

    const glyphs = mathGlyphNodes(mathContainer);
    const selectedIndexes = granularMathSelectedIndexes(state)
        .filter(index => index >= 0 && index < glyphs.length);
    if (!selectedIndexes.length) return null;

    const selectedSet = new Set(selectedIndexes);
    const selectedRects = selectedIndexes.map(index => (
        glyphs[index].getBoundingClientRect()
    ));

    const left = Math.min(...selectedRects.map(rect => rect.left));
    const top = Math.min(...selectedRects.map(rect => rect.top));
    const right = Math.max(...selectedRects.map(rect => rect.right));
    const bottom = Math.max(...selectedRects.map(rect => rect.bottom));

    const svgRect = originalSvg.getBoundingClientRect();
    if (!svgRect.width || !svgRect.height) return null;

    const clone = originalSvg.cloneNode(true);
    clone.classList.remove("rich-glyph-selected");
    clone.querySelectorAll(".rich-glyph-selected").forEach(node => {
        node.classList.remove("rich-glyph-selected");
    });

    const cloneGlyphs = [
        ...clone.querySelectorAll("[data-c]")
    ];
    cloneGlyphs.forEach((glyph, index) => {
        if (!selectedSet.has(index)) {
            glyph.setAttribute("visibility", "hidden");
        }
    });

    const baseViewBox = originalSvg.viewBox?.baseVal;
    if (baseViewBox?.width && baseViewBox?.height) {
        const scaleX = baseViewBox.width / svgRect.width;
        const scaleY = baseViewBox.height / svgRect.height;
        const paddingPx = 1;
        const cropLeft = Math.max(svgRect.left, left - paddingPx);
        const cropTop = Math.max(svgRect.top, top - paddingPx);
        const cropRight = Math.min(svgRect.right, right + paddingPx);
        const cropBottom = Math.min(svgRect.bottom, bottom + paddingPx);

        const viewX = baseViewBox.x
            + (cropLeft - svgRect.left) * scaleX;
        const viewY = baseViewBox.y
            + (cropTop - svgRect.top) * scaleY;
        const viewWidth = Math.max(1, (cropRight - cropLeft) * scaleX);
        const viewHeight = Math.max(1, (cropBottom - cropTop) * scaleY);

        clone.setAttribute(
            "viewBox",
            `${viewX} ${viewY} ${viewWidth} ${viewHeight}`
        );
    }

    const width = Math.max(1, right - left + 2);
    const height = Math.max(1, bottom - top + 2);
    clone.setAttribute("width", `${width}px`);
    clone.setAttribute("height", `${height}px`);
    clone.style.width = `${width}px`;
    clone.style.height = `${height}px`;
    clone.style.color = "#111827";

    const dataUrl = clipboardSvgDataUrl(clone);
    const text = mathSelectionPlainText(state);

    const image = document.createElement("img");
    image.src = dataUrl;
    image.alt = text || "数学公式";
    image.style.display = "inline-block";
    image.style.verticalAlign = "middle";
    image.style.width = `${width}px`;
    image.style.height = `${height}px`;
    image.style.maxWidth = "100%";

    return {
        text,
        html: image.outerHTML,
        width,
        height
    };
}

function buildGranularMathClipboardPayload(state, selection) {
    const partial = partialMathSvgPayload(state);
    if (!partial) {
        return { text: mathSelectionPlainText(state), html: "" };
    }

    const direction = Number(state?.outsideDirection || 0);

    if (
        !direction
        || !selection
        || selection.isCollapsed
        || selection.rangeCount < 1
    ) {
        return {
            text: partial.text,
            html: partial.html
        };
    }

    let nativePayload = { text: "", html: "" };

    try {
        const fragment = selection.getRangeAt(0).cloneContents();
        nativePayload = buildClipboardPayload(fragment);
    } catch (_error) {
        // 外部文字范围复制失败时至少保留已经精确选中的公式部分。
    }

    if (direction < 0) {
        return {
            text: `${nativePayload.text}${partial.text}`,
            html: `${nativePayload.html}${partial.html}`
        };
    }

    return {
        text: `${partial.text}${nativePayload.text}`,
        html: `${partial.html}${nativePayload.html}`
    };
}

function installDirectMathSelectionStart() {
    const finishDrag = () => {
        richMathGranularDragState = null;
    };

    document.addEventListener("mousedown", event => {
        if (event.button !== 0) return;

        const mathContainer = mathContainerFromPointerTarget(
            event.target
        );

        if (!mathContainer) {
            clearGranularMathSelection();
            return;
        }

        const startIndex = mathGlyphIndexFromPointer(
            mathContainer,
            event.clientX,
            event.clientY
        );
        if (startIndex < 0) return;

        // SVG path 不能成为浏览器原生文字选区的锚点，因此只接管
        // “鼠标从公式本身按下”的这次拖选。不是整条选中，而是记录
        // 起始字形，随后鼠标拖到哪个字形就精确选到哪个字形。
        event.preventDefault();
        clearGranularMathSelection();
        clearNativeDocumentSelection();

        richMathGranularDragState = {
            mathContainer,
            startIndex,
            startX: event.clientX,
            startY: event.clientY,
            active: false
        };
    }, true);

    window.addEventListener("mousemove", event => {
        const drag = richMathGranularDragState;
        if (!drag) return;

        if ((event.buttons & 1) !== 1) {
            finishDrag();
            return;
        }

        const distance = Math.hypot(
            event.clientX - drag.startX,
            event.clientY - drag.startY
        );

        // 与普通文字拖选一样，单击不产生选区；真正拖动后才开始高亮。
        if (!drag.active && distance < 2) return;
        drag.active = true;
        event.preventDefault();

        const pointedMath = mathContainerFromPointerTarget(
            document.elementFromPoint(event.clientX, event.clientY)
        );

        if (pointedMath === drag.mathContainer) {
            const endIndex = mathGlyphIndexFromPointer(
                drag.mathContainer,
                event.clientX,
                event.clientY
            );
            if (endIndex < 0) return;

            richMathGranularSelectionState = {
                mathContainer: drag.mathContainer,
                startIndex: drag.startIndex,
                endIndex,
                outsideDirection: 0
            };

            clearNativeDocumentSelection();
            renderGranularMathSelection(
                richMathGranularSelectionState
            );
            return;
        }

        const point = caretBoundaryFromViewportPoint(
            event.clientX,
            event.clientY
        );
        if (!point) return;

        let relative = compareBoundaryPointToMath(
            point,
            drag.mathContainer
        );

        // 极少数浏览器在 SVG 附近给出的 caret 点仍落在容器边界内部，
        // 用鼠标实际坐标做一次方向兜底。
        if (relative === 0) {
            const rect = drag.mathContainer.getBoundingClientRect();
            if (event.clientX < rect.left) relative = -1;
            else if (event.clientX > rect.right) relative = 1;
            else if (event.clientY < rect.top) relative = -1;
            else if (event.clientY > rect.bottom) relative = 1;
        }

        if (relative === 0) return;

        const glyphs = mathGlyphNodes(drag.mathContainer);
        const endIndex = relative > 0
            ? Math.max(0, glyphs.length - 1)
            : 0;

        richMathGranularSelectionState = {
            mathContainer: drag.mathContainer,
            startIndex: drag.startIndex,
            endIndex,
            outsideDirection: relative
        };

        setNativeSelectionOutsideMath(
            drag.mathContainer,
            point,
            relative
        );
        renderGranularMathSelection(
            richMathGranularSelectionState
        );
        refreshRichMathSelectionFeedback();
    }, true);

    window.addEventListener("mouseup", event => {
        const drag = richMathGranularDragState;
        if (drag && !drag.active) {
            clearGranularMathSelection();
            clearNativeDocumentSelection();
        }
        finishDrag();
    }, true);

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            clearGranularMathSelection();
            clearNativeDocumentSelection();
        }
    });

    window.addEventListener("resize", () => {
        if (richMathGranularSelectionState) {
            renderGranularMathSelection(
                richMathGranularSelectionState
            );
        }
    });
}

function selectionTouchesMathJax(selection) {
    if (!selection || selection.isCollapsed || selection.rangeCount < 1) {
        return false;
    }

    const anchorMath = selectionNodeElement(selection.anchorNode)
        ?.closest?.("mjx-container");
    const focusMath = selectionNodeElement(selection.focusNode)
        ?.closest?.("mjx-container");

    if (anchorMath || focusMath) {
        return true;
    }

    const mathContainers = document.querySelectorAll("mjx-container");

    for (let i = 0; i < selection.rangeCount; i += 1) {
        const range = selection.getRangeAt(i);

        for (const container of mathContainers) {
            try {
                if (range.intersectsNode(container)) {
                    return true;
                }
            } catch (_error) {
                // 特殊 SVG 节点异常时继续检查其他公式。
            }
        }
    }

    return false;
}

function writeSelectionClipboard(event, payload) {
    if (!payload?.text && !payload?.html) return false;
    if (!event.clipboardData) return false;

    event.clipboardData.setData(
        "text/plain",
        String(payload.text || "")
    );
    if (payload.html) {
        event.clipboardData.setData(
            "text/html",
            String(payload.html)
        );
    }
    event.preventDefault();
    return true;
}

function installRichSelectionCopy() {
    installRichMathSelectionFeedback();
    installDirectMathSelectionStart();

    document.addEventListener("copy", event => {
        const target = event.target;
        if (
            target instanceof Element
            && target.closest("input, textarea, [contenteditable='true']")
        ) {
            return;
        }

        const selection = window.getSelection();

        // 直接从公式内部拖出的“逐字形选区”优先。即使没有原生 DOM
        // Selection（只在一个公式内部拖选时就是这种情况），Ctrl+C 仍然
        // 能精确复制当前选中的那一段，而不是整条公式。
        if (richMathGranularSelectionState) {
            const payload = buildGranularMathClipboardPayload(
                richMathGranularSelectionState,
                selection
            );
            writeSelectionClipboard(event, payload);
            return;
        }

        if (!selection || selection.isCollapsed || selection.rangeCount < 1) {
            return;
        }

        // 阶段一之前的原版对普通文字/列表/表格完全使用浏览器原生复制。
        // 只有普通 DOM 选区真正跨过 MathJax 时才做公式增强。
        if (!selectionTouchesMathJax(selection)) {
            return;
        }

        const fragment = cloneSelectionContentsForRichCopy(selection);
        if (!fragment || !fragment.childNodes.length) return;

        const payload = buildClipboardPayload(fragment);
        writeSelectionClipboard(event, payload);
    });
}


function isChatNearBottom(chat, threshold = 90) {
    if (!chat) return true;

    const distance = (
        chat.scrollHeight
        - chat.scrollTop
        - chat.clientHeight
    );

    return distance <= threshold;
}

function scrollChatToBottom() {
    const chat = document.getElementById("chat");

    if (chat) {
        chat.scrollTop = chat.scrollHeight;
    }
}

function chatBottomDistance(chat) {
    if (!chat) return 0;

    return Math.max(
        0,
        chat.scrollHeight
        - chat.scrollTop
        - chat.clientHeight
    );
}

function stopTypingAutoFollow() {
    if (!typingTimer) return;

    typingScrollLockedByUser = true;
    typingAutoFollow = false;
}

function handleChatWheelWhileTyping(event) {
    if (!typingTimer) return;

    // 只要用户主动滚轮，就先停止自动跟随。
    // 这样上下滚动都不会和打字机争夺 scrollTop。
    if (event.deltaY !== 0) {
        stopTypingAutoFollow();
    }
}

function handleChatPointerWhileTyping() {
    if (!typingTimer) return;

    // 支持拖动滚动条。
    stopTypingAutoFollow();
}

function handleChatTouchWhileTyping() {
    if (!typingTimer) return;

    stopTypingAutoFollow();
}

function handleChatScrollWhileTyping() {
    if (!typingTimer) return;

    const chat = document.getElementById("chat");
    if (!chat) return;

    const distance = chatBottomDistance(chat);

    if (typingScrollLockedByUser) {
        if (distance <= 12) {
            typingScrollLockedByUser = false;
            typingAutoFollow = true;
        } else {
            typingAutoFollow = false;
        }

        return;
    }

    typingAutoFollow = distance <= 90;
}

function maybeAutoFollowTyping() {
    if (
        !typingAutoFollow
        || typingScrollLockedByUser
    ) {
        return;
    }

    // 不再每个字符都操作滚动条。
    const now = Date.now();

    if (now - lastTypingAutoScrollAt < 120) {
        return;
    }

    lastTypingAutoScrollAt = now;
    scrollChatToBottom();
}


function deriveSessionName(text, source = "text") {
    let value = String(text || "")
        .replace(/【题目文字】/g, "")
        .replace(/【图形信息】/g, "")
        .replace(/\[图片识题\]/g, "")
        .replace(/[#*_`>]/g, "")
        .trim();

    const firstUsefulLine = value
        .split(/\r?\n/)
        .map(line => line.trim())
        .find(line => (
            line
            && !/^[-—=]{2,}$/.test(line)
        ));

    value = firstUsefulLine || value;

    if (!value) {
        return source === "ocr"
            ? "图片识题"
            : "新对话";
    }

    value = value
        .replace(/\s+/g, " ")
        .replace(/^题目[:：]\s*/, "")
        .trim();

    const maxLength = 15;

    return value.length > maxLength
        ? `${value.slice(0, maxLength)}…`
        : value;
}

function maybeAutoNameSession(
    session,
    text,
    source = "text"
) {
    if (
        !session
        || session.name !== "新对话"
    ) {
        return false;
    }

    const name = deriveSessionName(
        text,
        source
    );

    if (!name || name === "新对话") {
        return false;
    }

    session.name = name;
    return true;
}

function refreshUnnamedSessionNames() {
    let changed = false;

    for (const session of sessions) {
        if (
            session.name !== "新对话"
            || !Array.isArray(session.messages)
        ) {
            continue;
        }

        const firstUser = session.messages.find(
            message => (
                message
                && message.role === "user"
                && typeof message.text === "string"
                && message.text.trim()
            )
        );

        if (
            firstUser
            && maybeAutoNameSession(
                session,
                firstUser.text,
                firstUser.source || "text"
            )
        ) {
            changed = true;
        }
    }

    if (changed) {
        saveState();
    }
}


// -----------------------------
// 新对话
// -----------------------------
function newChat() {
    if (typingTimer) {
        forceCompleteTyping();
    }

    const id = makeSessionId();

    sessions.push({
        id,
        name: "新对话",
        messages: [],
        teaching: null,
        learningQuestion: null,
        retest: null
    });

    currentId = id;

    saveState();
    renderAll();
    animateMobileConversationSwitch();
}


// -----------------------------
// 发送聊天
// -----------------------------
function questionCandidateFingerprint(candidate) {
    return candidate
        ? wrongQuestionFingerprint(candidate.text)
        : "";
}

function findQuestionCandidateByFingerprint(
    session,
    fingerprint
) {
    const target = String(fingerprint || "").trim();
    if (!target) return null;

    return collectConversationQuestionCandidates(session)
        .find(candidate => (
            questionCandidateFingerprint(candidate) === target
        )) || null;
}

function currentQuestionCandidateFromLearningState(session) {
    const saved = normalizeLearningQuestion(
        session?.learningQuestion
    );

    if (!saved) return null;

    return findQuestionCandidateByFingerprint(
        session,
        wrongQuestionFingerprint(saved.text)
    );
}

function structuralQuestionReference(text) {
    const value = normalizeQuestionReferenceText(text);
    if (!value) return null;

    const relative = relativeQuestionReference(value);
    if (relative) {
        return {
            kind: "relative",
            offset: relative.offset,
            anchorOrdinal: relative.anchorOrdinal,
            anchorReverseOrdinal: relative.anchorReverseOrdinal,
            anchorBoundary: relative.anchorBoundary
        };
    }

    const reverseOrdinal = questionReverseOrdinalReference(value);
    if (reverseOrdinal) {
        return {
            kind: "reverse_ordinal",
            ordinal: reverseOrdinal
        };
    }

    const ordinal = questionOrdinalReference(value);
    if (ordinal) {
        return {
            kind: "ordinal",
            ordinal
        };
    }

    const boundary = questionBoundaryReference(value);
    if (boundary) {
        return {
            kind: boundary
        };
    }

    return null;
}

function currentQuestionPositionInCandidates(session, candidates) {
    if (!Array.isArray(candidates) || !candidates.length) {
        return -1;
    }

    const current = currentQuestionCandidateFromLearningState(
        session
    );

    if (current) {
        const fingerprint = questionCandidateFingerprint(current);
        const position = candidates.findIndex(candidate => (
            questionCandidateFingerprint(candidate) === fingerprint
        ));

        if (position >= 0) {
            return position;
        }
    }

    return candidates.length - 1;
}

function resolveStructuralQuestionPosition(
    reference,
    candidateCount,
    currentPosition
) {
    if (!reference || candidateCount <= 0) {
        return -1;
    }

    let position = -1;

    if (reference.kind === "relative") {
        let basePosition = currentPosition;

        if (reference.anchorOrdinal) {
            basePosition = reference.anchorOrdinal - 1;
        } else if (reference.anchorReverseOrdinal) {
            basePosition = candidateCount - reference.anchorReverseOrdinal;
        } else if (reference.anchorBoundary === "first") {
            basePosition = 0;
        } else if (reference.anchorBoundary === "last") {
            basePosition = candidateCount - 1;
        } else if (reference.anchorBoundary === "current") {
            basePosition = currentPosition;
        }

        if (basePosition < 0 || basePosition >= candidateCount) {
            return -1;
        }

        position = basePosition + reference.offset;
    } else if (reference.kind === "ordinal") {
        position = reference.ordinal - 1;
    } else if (reference.kind === "reverse_ordinal") {
        position = candidateCount - reference.ordinal;
    } else if (reference.kind === "first") {
        position = 0;
    } else if (reference.kind === "last") {
        position = candidateCount - 1;
    } else if (reference.kind === "current") {
        position = currentPosition;
    }

    return (
        Number.isInteger(position)
        && position >= 0
        && position < candidateCount
    )
        ? position
        : -1;
}

function resolveStructuralQuestionCandidate(session, text) {
    const reference = structuralQuestionReference(text);
    if (!reference) return null;

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    const currentPosition = currentQuestionPositionInCandidates(
        session,
        candidates
    );
    const position = resolveStructuralQuestionPosition(
        reference,
        candidates.length,
        currentPosition
    );

    return position >= 0
        ? candidates[position]
        : null;
}

function resolvePreviousQuestionCandidate(session, steps = 1) {
    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    const currentPosition = currentQuestionPositionInCandidates(
        session,
        candidates
    );
    const offset = -Math.max(1, Number(steps) || 1);
    const position = currentPosition + offset;

    return position >= 0
        ? candidates[position]
        : null;
}

function resolveNextQuestionCandidate(session, steps = 1) {
    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    const currentPosition = currentQuestionPositionInCandidates(
        session,
        candidates
    );
    const offset = Math.max(1, Number(steps) || 1);
    const position = currentPosition + offset;

    return position < candidates.length
        ? candidates[position]
        : null;
}

function resolveOrdinalQuestionCandidate(session, text) {
    const ordinal = questionOrdinalReference(text);
    if (!ordinal) return null;

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    return candidates[ordinal - 1] || null;
}

function resolveReverseOrdinalQuestionCandidate(session, text) {
    const ordinal = questionReverseOrdinalReference(text);
    if (!ordinal) return null;

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    return candidates[candidates.length - ordinal] || null;
}

function resolveNamedQuestionCandidate(session, text) {
    const topic = namedQuestionTopicReference(text);
    if (!topic) return null;

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) return null;

    const aliases = {
        命题逻辑: ["命题逻辑", "命题", "真值", "真值表", "逻辑联结词", "范式", "主析取", "主合取"],
        谓词逻辑: ["谓词逻辑", "谓词", "量词", "个体域", "辖域", "前束范式"],
        证明与归纳: ["证明与归纳", "直接证明", "反证", "反证法", "数学归纳", "强归纳"],
        集合与关系: ["集合与关系", "集合", "关系", "偏序", "等价关系", "闭包"],
        集合: ["集合", "全集", "子集", "补集", "并集", "交集", "幂集"],
        关系: ["关系", "二元关系", "自反", "对称", "传递", "偏序", "等价", "哈斯图", "闭包"],
        函数: ["函数", "映射", "单射", "满射", "双射", "逆函数", "复合函数"],
        初等数论: ["初等数论", "数论", "整除", "素数", "质数", "因数", "约数", "同余", "欧几里得", "RSA"],
        数论: ["初等数论", "数论", "整除", "素数", "质数", "因数", "约数", "同余", "欧几里得", "RSA"],
        计数与组合: ["计数与组合", "组合", "排列", "鸽巢", "容斥", "计数"],
        组合: ["计数与组合", "组合", "排列", "鸽巢", "容斥", "计数"],
        递推关系: ["递推关系", "递推", "递归", "生成函数"],
        递推: ["递推关系", "递推", "递归", "生成函数"],
        图论: ["图论", "图", "顶点", "边", "欧拉", "邻接", "路径", "哈密顿", "生成树", "最短路"],
        代数结构: ["代数结构", "代数", "群", "子群", "半群", "幺半群", "同态", "同构", "环", "域", "格", "布尔代数"],
        代数: ["代数结构", "代数", "群", "子群", "半群", "幺半群", "同态", "同构", "环", "域", "格", "布尔代数"],
        逻辑: ["命题逻辑", "谓词逻辑", "逻辑", "命题", "真值", "量词", "谓词", "范式"],
        归纳: ["证明与归纳", "数学归纳", "强归纳", "反证", "直接证明"]
    };

    let terms = [topic];

    for (const [name, values] of Object.entries(aliases)) {
        if (
            topic === name
            || topic.includes(name)
            || name.includes(topic)
        ) {
            terms = [...new Set([...terms, ...values])];
        }
    }

    let best = null;
    let bestScore = 0;

    for (const candidate of candidates) {
        const teaching = candidateTeachingSnapshot(
            session,
            candidate
        );

        const haystack = [
            candidate.text,
            teaching?.category || "",
            ...(teaching?.knowledge_points || []),
            ...(teaching?.focus_points || [])
        ].join(" ");

        let score = 0;

        for (const term of terms) {
            if (term && haystack.includes(term)) {
                // 精确模块/主题名称权重更高，避免“谓词逻辑”被最近的命题逻辑题抢走。
                score += term === topic ? 8 : 1;
            }
        }

        if (
            teaching?.category
            && (
                teaching.category === topic
                || topic.includes(teaching.category)
                || teaching.category.includes(topic)
            )
        ) {
            score += 12;
        }

        if (
            score > bestScore
            || (
                score === bestScore
                && score > 0
                && best
                && candidate.index > best.index
            )
        ) {
            best = candidate;
            bestScore = score;
        }
    }

    return bestScore > 0 ? best : null;
}

function resolveQuestionNavigationCandidate(session, text) {
    const structural = structuralQuestionReference(text);

    if (structural) {
        return resolveStructuralQuestionCandidate(
            session,
            text
        );
    }

    return resolveNamedQuestionCandidate(
        session,
        text
    );
}

function questionNavigationFailureMessage(session, text) {
    const candidates = collectConversationQuestionCandidates(
        session
    );
    const count = candidates.length;

    if (!count) {
        return "当前会话还没有识别到可引用的题目，请先输入或生成一道题。";
    }

    const structural = structuralQuestionReference(text);

    if (structural?.kind === "relative") {
        const currentPosition = currentQuestionPositionInCandidates(
            session,
            candidates
        );
        let basePosition = currentPosition;

        if (structural.anchorOrdinal) {
            basePosition = structural.anchorOrdinal - 1;
        } else if (structural.anchorReverseOrdinal) {
            basePosition = count - structural.anchorReverseOrdinal;
        } else if (structural.anchorBoundary === "first") {
            basePosition = 0;
        } else if (structural.anchorBoundary === "last") {
            basePosition = count - 1;
        }

        const targetPosition = basePosition + structural.offset;

        if (targetPosition < 0) {
            return "前面已经没有更早的题目了；当前指代已经到第一道已识别题。";
        }

        if (targetPosition >= count) {
            return "后面还没有可切换的已识别题目；当前指代已经到最后一道题。";
        }
    }

    if (structural?.kind === "ordinal") {
        return `当前会话共识别到 ${count} 道题，找不到第 ${structural.ordinal} 题。`;
    }

    if (structural?.kind === "reverse_ordinal") {
        return `当前会话共识别到 ${count} 道题，找不到倒数第 ${structural.ordinal} 题。`;
    }

    if (namedQuestionTopicReference(text)) {
        return "没找到你指的那一道主题题目。可以改说“第2题”“上一道题”“下一道题”或更具体的知识点名称。";
    }

    return "没找到你指的那一道题。可以改说“第2题”“上一道题”“下一道题”“最后一道题”或具体知识点名称。";
}

function buildTargetQuestionApiText(userText, candidate) {
    const question = String(candidate?.text || "").trim();
    const latestRequest = String(userText || "").trim();

    if (!question) return latestRequest;

    // 题目正文只是定位上下文，不是另一条待执行的用户请求。
    // 把它与“本轮唯一请求”合并成同一个 user 消息，避免模型把
    // 连续两条用户话语都当作本轮任务一起回答。
    return [
        "【当前指向题目】",
        question,
        "【当前指向题目结束】",
        "",
        "【本轮唯一需要执行的用户请求】",
        latestRequest,
        "【本轮请求结束】",
        "",
        "只回答上面的本轮最新请求。不要重新执行、补答、总结或继续处理更早的用户请求；",
        "更早的内容只能用于理解指代和题目背景。"
    ].join("\n");
}

function buildApiMessages(session, targetCandidate = null) {
    if (!session || !Array.isArray(session.messages)) {
        return [];
    }

    const valid = session.messages
        .map((message, index) => ({ message, index }))
        .filter(({ message }) => (
            message
            && !message.isError
            && !message.isNotice
            && typeof message.text === "string"
            && message.text.trim()
        ));

    if (!valid.length) return [];

    const latestUserEntry = [...valid]
        .reverse()
        .find(({ message }) => message.role === "user");

    if (!latestUserEntry) return [];

    const latestUser = latestUserEntry.message;
    const latestIndex = latestUserEntry.index;
    const target = targetCandidate
        || activeQuestionCandidateFromHistory(session)
        || currentQuestionCandidateFromLearningState(session);

    const mapRole = role => (
        role === "user" ? "user" : "assistant"
    );

    const messageContent = message => {
        let content = (
            message.role === "user"
            && typeof message.apiText === "string"
            && message.apiText.trim()
        )
            ? message.apiText
            : message.text;

        if (
            message.role === "user"
            && message.source === "ocr"
        ) {
            content = `[图片识题]\n${content}`;
        }

        return content;
    };

    // 同知识点练习必须携带它引用的题目；指定新主题的独立出题不带旧题。
    // 注意：裸“下一题”在历史中确实存在后一道题时，会被 send() 解析为
    // 导航并写入 targetQuestionFingerprint，此时不能再误走出题分支。
    const latestIsResolvedNavigation = Boolean(
        isQuestionNavigationFollowUp(latestUser.text)
        && latestUser.targetQuestionFingerprint
        && !hasExplicitExerciseGenerationCue(latestUser.text)
    );

    if (
        isExerciseRequestText(latestUser.text)
        && !latestIsResolvedNavigation
    ) {
        const reference = isContextualExerciseRequest(latestUser.text)
            ? (targetCandidate || resolveExerciseReference(session, latestUser.text))
            : null;
        return [{
            role: "user",
            content: reference
                ? buildTargetQuestionApiText(latestUser.text, reference)
                : messageContent(latestUser)
        }];
    }

    // 真正的新自包含题也优先独立发送，不要因为会话中已有 target 就
    // 被错误包装成“上一题的追问”。
    if (
        (
            latestUser.source === "ocr"
            || looksLikeActualLearningProblem(latestUser)
        )
        && !isQuestionNavigationFollowUp(latestUser.text)
    ) {
        return [{
            role: "user",
            content: messageContent(latestUser)
        }];
    }

    if (target) {
        const targetFingerprint = questionCandidateFingerprint(
            target
        );

        // 对“上一题 / 第一题 / 继续 / 为什么 / 我不会”等追问，
        // 请求中只允许存在一个“当前 user 指令”。题目正文是定位信息，
        // 不能再单独伪装成另一条 user 消息，否则模型可能把两条都执行。
        if (
            target.index < latestIndex
            || isShortLearningFollowUp(latestUser.text)
            || latestUser.targetQuestionFingerprint
        ) {
            const scoped = [];

            // 只有真正依赖上一段讲解位置的短追问，才保留最近一次相关
            // assistant 回复作为背景。明确的“第一题/第二题/上一题”导航
            // 不需要旧回答，直接围绕目标题处理最新一句即可。
            const needsAssistantContext = (
                !isQuestionNavigationFollowUp(latestUser.text)
                && /(?:继续|为什么|然后呢|下一步|这一步|这里|这个|再解释|再讲一下)/.test(
                    String(latestUser.text || "").replace(/\s+/g, "")
                )
            );

            if (needsAssistantContext) {
                let lastRelatedAssistant = null;

                for (let index = latestIndex - 1; index >= 0; index -= 1) {
                    const message = session.messages[index];

                    if (!message || message.role !== "ai") {
                        continue;
                    }

                    if (
                        targetFingerprint
                        && message.targetQuestionFingerprint === targetFingerprint
                        && !message.isError
                        && !message.isNotice
                    ) {
                        lastRelatedAssistant = message;
                        break;
                    }
                }

                if (lastRelatedAssistant) {
                    scoped.push({
                        role: "assistant",
                        content: lastRelatedAssistant.text
                    });
                }
            }

            const latestContent = latestUser.isRetestAnswer
                ? messageContent(latestUser)
                : buildTargetQuestionApiText(
                    latestUser.text,
                    target
                );

            scoped.push({
                role: "user",
                content: latestContent
            });

            return scoped;
        }
    }

    // 一道全新的自包含题目，不需要把上一道题的完整回答继续塞进请求。
    if (
        latestUser.source === "ocr"
        || looksLikeActualLearningProblem(latestUser)
    ) {
        return [{
            role: "user",
            content: messageContent(latestUser)
        }];
    }

    // 兼容无法识别题目锚点的旧会话，退回有限的最近窗口。
    // 正常题目追问仍优先使用显式题目状态，不会把整段历史无差别塞给模型。
    return valid
        .slice(-FALLBACK_API_CONTEXT_MESSAGES)
        .map(({ message }) => ({
            role: mapRole(message.role),
            content: messageContent(message)
        }));
}

async function parseResponseJson(response) {
    try {
        return await response.json();
    } catch (_error) {
        return {};
    }
}

function fallbackHttpError(status) {
    if (status === 400) {
        return "请求内容有误，请检查后重新发送。";
    }
    if (status === 413) {
        return "上传内容过大，请重新选择。";
    }
    if (status === 429) {
        return "当前请求过于频繁，请稍后再试。";
    }
    if (status >= 500) {
        return "服务暂时不可用，请稍后重试。";
    }

    return "请求失败，请稍后重试。";
}

function attachTeachingSnapshotToLatestQuestion(
    session,
    teaching
) {
    const normalized = normalizeTeaching(teaching);

    if (
        !session
        || !normalized
        || !Array.isArray(session.messages)
    ) {
        return;
    }

    for (
        let index = session.messages.length - 1;
        index >= 0;
        index -= 1
    ) {
        const message = session.messages[index];

        if (
            !message
            || message.role !== "user"
            || message.isRetestAnswer
        ) {
            continue;
        }

        // “随便出一道题 / 给我来个难题 / 再来一道”等只是出题命令，
        // 不是一道可评级的用户题目。即使后端 teaching 带有目标难度，
        // 也绝不能把这个快照挂到用户命令气泡上。
        if (isExerciseRequestText(message.text)) {
            return;
        }

        const question = extractQuestionOnlyFromMessage(
            message
        );

        if (message.source === "ocr") {
            if (isRecordableOcrQuestionMessage(message)) {
                message.questionTeaching = normalized;
            }
            return;
        }

        if (
            question
            && looksLikeQuestionPayload(question)
            && !isConversationControlOnly(message.text)
        ) {
            message.questionTeaching = normalized;
            return;
        }

        // 最近用户消息只是“不会做/继续”等追问时，
        // 不把这个 follow-up 错当成一道新题。
        if (isConversationControlOnly(message.text)) {
            return;
        }
    }
}


async function requestAiReply(session) {
    if (!session) return;

    const latestUserBeforeRequest = getLatestUserMessage(
        session
    );
    const retestBeforeRequest = normalizeRetestSession(
        session.retest
    );
    const latestIsRetestGeneration = Boolean(
        latestUserBeforeRequest?.isRetestPrompt
        && retestBeforeRequest?.stage === "generating"
    );

    const latestText = latestUserBeforeRequest?.text || "";
    const latestIsNavigationRequest = Boolean(
        latestUserBeforeRequest
        && isQuestionNavigationFollowUp(latestText)
    );

    // send() 已经解析过导航时，优先使用它写入的强指纹；
    // 兼容旧会话/旧消息时，再现场解析一次。避免“下一题”被解析两次而跳两格。
    let navigationCandidate = null;

    if (latestIsNavigationRequest) {
        navigationCandidate = latestUserBeforeRequest?.targetQuestionFingerprint
            ? findQuestionCandidateByFingerprint(
                session,
                latestUserBeforeRequest.targetQuestionFingerprint
            )
            : resolveQuestionNavigationCandidate(
                session,
                latestText
            );
    }

    const rawExerciseRequest = isExerciseRequestText(latestText);
    const latestIsExerciseRequest = Boolean(
        latestIsRetestGeneration
        || (
            rawExerciseRequest
            && !(
                navigationCandidate
                && !hasExplicitExerciseGenerationCue(latestText)
            )
        )
    );

    const latestIsFreshQuestion = Boolean(
        latestUserBeforeRequest
        && (
            latestUserBeforeRequest.source === "ocr"
            || looksLikeActualLearningProblem(
                latestUserBeforeRequest
            )
        )
        && !latestIsNavigationRequest
    );

    // 明确说“第99题 / 下一题不太会 / 某主题那道题”却找不到目标时，
    // 不能悄悄回落到当前题，否则就是用户截图里那类“答错题”的根源。
    // 裸“下一题”在已经位于最后一题时仍允许走“继续出题”快捷逻辑。
    if (
        latestIsNavigationRequest
        && !navigationCandidate
        && !latestIsExerciseRequest
    ) {
        showAssistantMessage(
            session,
            questionNavigationFailureMessage(
                session,
                latestText
            ),
            { isError: true }
        );
        return;
    }

    // 普通“同知识点出题”从当前会话里找参照题；
    // 错题复测则直接使用错题本保存的原题，不能再去新建的复测会话里找。
    const exerciseReference = (
        latestIsExerciseRequest
        && !latestIsRetestGeneration
    )
        ? resolveExerciseReference(
            session,
            latestUserBeforeRequest?.text || ""
        )
        : null;

    let retestReferenceQuestion = "";

    if (latestIsRetestGeneration && retestBeforeRequest) {
        const entry = learningState.wrongQuestions.find(
            item => item.id === retestBeforeRequest.wrongQuestionId
        );

        retestReferenceQuestion = String(
            retestBeforeRequest.referenceQuestion
            || entry?.question
            || ""
        ).trim().slice(0, 3000);
    }

    if (
        latestIsExerciseRequest
        && !latestIsRetestGeneration
        && isContextualExerciseRequest(
            latestUserBeforeRequest?.text || ""
        )
        && !exerciseReference
    ) {
        showAssistantMessage(
            session,
            "还没找到要参照的题目。你可以说“第一道题 / 上一道题 / 数论那道题”，也可以直接说明要练习的知识点。",
            { isError: true }
        );
        return;
    }

    if (
        latestIsRetestGeneration
        && !retestReferenceQuestion
    ) {
        rollbackRetestAfterRequestFailure(session);
        showAssistantMessage(
            session,
            "复测原题已经丢失，请回到错题本重新发起复测。",
            { isError: true }
        );
        return;
    }

    const requestTargetCandidate = latestIsExerciseRequest
        ? exerciseReference
        : latestIsFreshQuestion ? null : (
            navigationCandidate
            || activeQuestionCandidateFromHistory(session)
            || currentQuestionCandidateFromLearningState(session)
        );
    const requestTargetFingerprint = questionCandidateFingerprint(
        requestTargetCandidate
    );

    setSessionBusy(session.id, true);

    try {
        // 导航到历史 AI 生成题时，旧记录可能还没有教学快照。先用
        // 规则分类补齐，这样右侧“学习内容 / 本题难点”会和目标题同步。
        if (
            requestTargetCandidate
            && !candidateTeachingSnapshot(
                session,
                requestTargetCandidate
            )
        ) {
            const targetTeaching = await analyzeSingleQuestionTeaching(
                requestTargetCandidate.text,
                requestTargetCandidate.key
            );

            if (targetTeaching) {
                applyQuestionCandidateAsCurrent(
                    session,
                    requestTargetCandidate,
                    targetTeaching
                );
                saveState();
                renderInfo();
            }
        }

        const response = await fetch("/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                messages: buildApiMessages(
                    session,
                    requestTargetCandidate
                ),
                // 强约束：明确出题请求由前端直接告诉后端。
                // 后端据此必须返回 generated_question + generated_teaching，
                // 不再只靠自然语言二次猜测“这是不是出题”。
                request_kind: latestIsExerciseRequest
                    ? "exercise"
                    : "chat",
                exercise_reference: retestReferenceQuestion
                    ? { question: retestReferenceQuestion }
                    : exerciseReference
                        ? { question: exerciseReference.text }
                        : undefined
            })
        });

        const data = await parseResponseJson(response);

        let localGeneratedQuestion = sanitizeStoredWrongQuestionText(
            data.generated_question || ""
        );

        // 后端旧版本或异常输出没有 generated_question 时，前端仍可根据
        // “本轮明确出题请求”从回复中恢复真正题干。只在 exercise 请求下做，
        // 不会把普通讲解误判为题目。
        if (
            !localGeneratedQuestion
            && latestIsExerciseRequest
            && typeof data.reply === "string"
        ) {
            const recovered = sanitizeStoredWrongQuestionText(
                extractAiGeneratedExerciseText(data.reply)
            );

            if (
                recovered
                && looksLikeQuestionPayload(recovered)
            ) {
                localGeneratedQuestion = recovered;
            }
        }

        let localGeneratedTeaching = normalizeTeaching(
            data.generated_teaching
        );

        if (
            localGeneratedQuestion
            && !localGeneratedTeaching
        ) {
            localGeneratedTeaching = await analyzeSingleQuestionTeaching(
                localGeneratedQuestion,
                "generated-current"
            );
        }

        // 系统不变量：明确“出题”的本轮请求，只有在题干与题目分类都拿到后
        // 才允许把 AI 回复写进聊天历史。否则宁可提示重试，也不能留下一个
        // “看得见但错题本/题目历史都不认识”的孤儿题目。
        if (
            response.ok
            && !data.error
            && latestIsExerciseRequest
            && (
                !localGeneratedQuestion
                || !localGeneratedTeaching
            )
        ) {
            rollbackRetestAfterRequestFailure(session);
            showAssistantMessage(
                session,
                "练习题生成结果未完成题目登记，请重新出题。",
                { isError: true }
            );
            return;
        }

        const returnedTeaching = (
            localGeneratedTeaching
            || data.teaching
        );

        if (returnedTeaching) {
            const normalizedReturnedTeaching = normalizeTeaching(
                returnedTeaching
            );
            const latestUser = getLatestUserMessage(session);
            const activeCandidate = activeQuestionCandidateFromHistory(
                session
            );

            // “上一道题/继续/再讲一下”不是新题。返回的教学分析必须写回
            // 当前指向题，而不是重新覆盖到时间上最新的另一道题。
            if (
                !localGeneratedQuestion
                && latestUser
                && isShortLearningFollowUp(latestUser.text)
                && activeCandidate
            ) {
                applyQuestionCandidateAsCurrent(
                    session,
                    activeCandidate,
                    normalizedReturnedTeaching
                );
            } else {
                session.teaching = normalizedReturnedTeaching;

                if (!localGeneratedQuestion) {
                    attachTeachingSnapshotToLatestQuestion(
                        session,
                        normalizedReturnedTeaching
                    );
                }
            }

            saveState();
            renderInfo();

            const graphModal = document.getElementById(
                "knowledgeGraphModal"
            );

            if (
                graphModal
                && !graphModal.classList.contains("hidden")
            ) {
                if (knowledgeGraphScope === "current") {
                    const context = getCurrentKnowledgeContext();

                    if (context.category) {
                        knowledgeGraphFilter = context.category;
                        knowledgeGraphViewMode = "focus";
                    }
                }

                renderKnowledgeGraph();
            }
        }

        if (!response.ok || data.error) {
            const message = data.error
                || fallbackHttpError(response.status);

            rollbackRetestAfterRequestFailure(session);

            showAssistantMessage(
                session,
                message,
                { isError: true }
            );
            return;
        }

        if (
            typeof data.reply !== "string"
            || !data.reply.trim()
        ) {
            rollbackRetestAfterRequestFailure(session);

            showAssistantMessage(
                session,
                "AI 服务没有返回有效内容，请重新发送。",
                { isError: true }
            );
            return;
        }

        const retestHandled = processWrongQuestionRetestReply(
            session,
            data.reply,
            localGeneratedQuestion,
            data.generated_answer || ""
        );

        if (!retestHandled) {
            processLearningFromReply(
                session,
                localGeneratedTeaching
                    || session.teaching,
                data.reply,
                data.generated_answer || "",
                localGeneratedQuestion
            );
        }

        const assistantMeta = {
            // 只有后端明确返回 generated_question，才标记为“AI 生成题”。
            // 普通讲解里出现编号、反问、步骤，不再被误判。
            generatedExercise: Boolean(
                localGeneratedQuestion
                || data.generated_exercise
            ),
            generatedQuestion: localGeneratedQuestion,
            generatedAnswer: data.generated_answer || "",
            generatedTeaching: (
                localGeneratedQuestion
                    ? (
                        localGeneratedTeaching
                        || returnedTeaching
                    )
                    : null
            ),
            targetQuestionFingerprint: requestTargetFingerprint
        };

        if (currentId === session.id) {
            startTyping(
                data.reply,
                session,
                assistantMeta
            );
        } else {
            addAssistantMessage(
                session,
                data.reply,
                assistantMeta
            );
            saveState();
            renderSessions();
            renderInfo();
        }

    } catch (error) {
        console.error("聊天请求失败：", error);

        rollbackRetestAfterRequestFailure(session);

        showAssistantMessage(
            session,
            "网络连接失败，请检查网络后重试。",
            { isError: true }
        );

    } finally {
        setSessionBusy(session.id, false);
    }
}

function send() {
    if (
        ocrReviewInProgress
        || isCurrentSessionTyping()
        || isSessionBusy(currentId)
    ) {
        return;
    }

    const input = document.getElementById("text");
    if (!input) return;

    const text = input.value.trim();
    if (!text) return;

    if (!currentId) {
        newChat();
    }

    const session = getCurrent();
    if (!session) return;

    const message = {
        role: "user",
        text
    };

    const retest = normalizeRetestSession(session.retest);

    if (retest && retest.stage === "awaiting_answer") {
        const retestCheckParts = [
            "【错题复测回答】",
            "请只检查下面这道复测题的学生作答，不要把它和原错题或会话里的其他题混在一起。",
            "如果全部正确，请明确说“这次作答正确”；",
            "如果存在任何实质错误，请明确说“这次作答有错误”；",
            "如果信息不足，请明确说“现有信息不足以判断”。",
            "",
            "【复测题目】",
            retest.generatedQuestion || "（题目缺失）"
        ];

        if (retest.generatedAnswer) {
            retestCheckParts.push(
                "",
                "【系统参考答案，仅用于核验】",
                retest.generatedAnswer,
                "不要直接向学生泄露这段系统参考答案；应先判断学生作答，再按教学模式给纠正方向。"
            );
        }

        retestCheckParts.push(
            "",
            "【学生作答】",
            text
        );

        message.apiText = retestCheckParts.join("\n");
        message.isRetestAnswer = true;

        retest.stage = "checking";
        session.retest = retest;
    }

    session.messages.push(message);

    // “上一道题 / 第一题 / 第二题”都属于明确的题目导航。
    // 在请求发出前先切换 current learningQuestion，右侧信息和后端上下文
    // 都围绕同一道目标题，避免旧题/新题一起被回答。
    if (isQuestionNavigationFollowUp(text)) {
        const targetCandidate = resolveQuestionNavigationCandidate(
            session,
            text
        );

        if (targetCandidate) {
            const targetFingerprint = questionCandidateFingerprint(
                targetCandidate
            );

            message.targetQuestionFingerprint = targetFingerprint;
            message.apiText = buildTargetQuestionApiText(
                text,
                targetCandidate
            );

            applyQuestionCandidateAsCurrent(
                session,
                targetCandidate
            );
        }
    }

    maybeAutoNameSession(
        session,
        text,
        "text"
    );

    input.value = "";

    forceChatBottomOnce = true;

    saveState();
    renderChat();
    renderSessions();
    renderInfo();

    const pendingKey = sessionBusyKey(session.id);
    pendingAiStartSessionIds.add(pendingKey);
    refreshInputAvailability();

    requestAiReply(session).finally(() => {
        pendingAiStartSessionIds.delete(pendingKey);
        refreshInputAvailability();
    });
}


// -----------------------------
// 图片题文字清理
// -----------------------------
function cleanOcrTextForVisual(rawText, hasVisualStructure) {
    const source = String(rawText ?? "").trim();

    // 没有图形结构识别结果时，保留 OCR 原文，避免误删。
    if (!source || !hasVisualStructure) {
        return source;
    }

    // 找第一道小题的编号，例如 (1)、（1）、1.、1、
    const questionMatch = source.match(
        /(?:\(\s*1\s*\)|（\s*1\s*）|(?:^|\s)1\s*[.．、])/m
    );

    if (!questionMatch || typeof questionMatch.index !== "number") {
        return source;
    }

    const questionIndex = questionMatch.index;
    const beforeQuestions = source.slice(0, questionIndex);
    const questions = source.slice(questionIndex).trim();

    // 这类提示语后面通常紧跟题图。OCR 会把图中的 v1、e1、e2……
    // 当成普通文字塞进题干。既然视觉模型已经单独识别了图形结构，
    // 就把“提示语 → 第(1)问”之间的图形 OCR 噪声去掉。
    const cues = [
        "回答下列问题",
        "回答以下问题",
        "完成下列问题",
        "解答下列问题",
        "求解下列问题",
        "回答问题"
    ];

    let bestEnd = -1;

    for (const cue of cues) {
        const index = beforeQuestions.lastIndexOf(cue);

        if (index >= 0) {
            bestEnd = Math.max(bestEnd, index + cue.length);
        }
    }

    if (bestEnd < 0) {
        return source;
    }

    const heading = beforeQuestions
        .slice(0, bestEnd)
        .trim()
        .replace(/[：:]\s*$/, "");

    if (!heading || !questions) {
        return source;
    }

    return `${heading}\n${questions}`;
}


// -----------------------------
// OCR 图片识题
// -----------------------------
let ocrReviewInProgress = false;
let ocrRequestInFlight = false;
let ocrAbortController = null;
let ocrRequestId = "";

function makeOcrRequestId() {
    try {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }
    } catch (_error) {
        // 旧浏览器回退到时间戳 + 随机串。
    }

    return `ocr-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function notifyOcrCancelled(requestId) {
    const value = String(requestId || "").trim();
    if (!value) return;

    fetch("/ocr/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: value }),
        keepalive: true
    }).catch(() => {
        // 撤销通知失败也不影响前端立即结束本次识别。
    });
}

function cancelImageRecognition() {
    if (!ocrRequestInFlight || !ocrAbortController) {
        return;
    }

    const requestId = ocrRequestId;

    // 前端立即停止等待本次 /ocr，并通知后端尽早结束后续阶段。
    ocrRequestInFlight = false;
    ocrAbortController.abort();
    ocrAbortController = null;
    ocrRequestId = "";
    notifyOcrCancelled(requestId);
    refreshInputAvailability();
}

function reviewRecognizedQuestion(file, data) {
    const dialog = document.getElementById("ocrReviewDialog");
    const preview = document.getElementById("ocrReviewImage");
    const question = document.getElementById("ocrReviewQuestion");
    const graph = document.getElementById("ocrReviewGraph");
    const requestText = document.getElementById("ocrReviewRequest");
    const error = document.getElementById("ocrReviewError");
    const confirm = document.getElementById("ocrReviewConfirm");
    const cancel = document.getElementById("ocrReviewCancel");
    const zoom = document.getElementById("ocrReviewZoom");
    if (!dialog || !preview || !question || !graph || !requestText || !confirm || !cancel) {
        throw new Error("图片核对界面未加载，请刷新页面。");
    }

    return new Promise((resolve, reject) => {
        const imageUrl = URL.createObjectURL(file);
        let result = null;
        preview.src = imageUrl;
        preview.style.width = "100%";
        if (zoom) zoom.value = "100";
        question.value = typeof data.text === "string" ? data.text.trim() : "";
        graph.value = typeof data.visual_text === "string" ? data.visual_text.trim() : "";

        // 本轮要求只在图片核对界面填写，不从主聊天框继承。
        requestText.value = "";
        error.textContent = "";

        const resizePreview = () => { preview.style.width = `${zoom.value}%`; };
        const cleanup = () => {
            dialog.removeEventListener("close", finish);
            confirm.removeEventListener("click", submit);
            cancel.removeEventListener("click", dismiss);
            if (zoom) zoom.removeEventListener("input", resizePreview);
            preview.removeAttribute("src");
            URL.revokeObjectURL(imageUrl);
            question.value = "";
            graph.value = "";
            requestText.value = "";
        };
        const finish = () => {
            cleanup();
            resolve(result);
        };
        const dismiss = () => dialog.close();
        const submit = () => {
            const text = question.value.trim();
            const visualText = graph.value.trim();
            const userRequest = requestText.value.trim();
            if (!text && !visualText) {
                error.textContent = "请至少保留题目文字或图形信息。";
                graph.focus();
                return;
            }
            if (/\[(?:待核对|不清楚)\]/.test(text + visualText)) {
                error.textContent = "请对照原图补全标为“待核对”的内容；看不清时可以取消并重新上传。";
                return;
            }
            if (text.length + visualText.length + userRequest.length > 5600) {
                error.textContent = "题目和本次要求合计过长，请适当精简后再发送。";
                return;
            }
            result = { text, visualText, userRequest };
            dialog.close();
        };
        confirm.addEventListener("click", submit);
        cancel.addEventListener("click", dismiss);
        if (zoom) zoom.addEventListener("input", resizePreview);
        dialog.addEventListener("close", finish);
        try {
            dialog.showModal();
            question.focus();
        } catch (exception) {
            cleanup();
            reject(exception);
        }
    });
}

function openImagePicker() {
    if (
        ocrReviewInProgress
        || isCurrentSessionTyping()
        || isSessionBusy(currentId)
    ) {
        return;
    }

    const imageInput = document.getElementById("imageInput");
    if (imageInput) {
        imageInput.click();
    }
}

async function handleImageSelected(event) {
    const input = event && event.target;
    const file = input && input.files
        ? input.files[0]
        : null;

    if (input) {
        // 允许连续选择同一张图片。
        input.value = "";
    }

    if (
        !file
        || ocrReviewInProgress
        || isCurrentSessionTyping()
        || isSessionBusy(currentId)
    ) {
        return;
    }

    if (
        file.type
        && !file.type.startsWith("image/")
    ) {
        showCurrentError(
            "请选择有效的图片文件。"
        );
        return;
    }

    if (file.size > MAX_IMAGE_BYTES) {
        showCurrentError(
            "图片过大，请上传 8MB 以内的图片。"
        );
        return;
    }

    if (!currentId) {
        newChat();
    }

    const session = getCurrent();
    if (!session) return;

    ocrReviewInProgress = true;
    ocrRequestInFlight = true;
    ocrAbortController = new AbortController();
    ocrRequestId = makeOcrRequestId();
    refreshInputAvailability();

    try {
        const formData = new FormData();
        formData.append("image", file);
        formData.append("request_id", ocrRequestId);

        const response = await fetch("/ocr", {
            method: "POST",
            body: formData,
            signal: ocrAbortController.signal
        });

        const data = await parseResponseJson(response);

        // 网络识别阶段已经结束；进入核对页后由核对页自己的取消按钮负责。
        ocrRequestInFlight = false;
        ocrAbortController = null;
        ocrRequestId = "";
        refreshInputAvailability();

        if (data && data.cancelled) {
            return;
        }

        if (!response.ok || data.error) {
            showAssistantMessage(
                session,
                data.error
                    || fallbackHttpError(response.status),
                { isError: true }
            );
            return;
        }

        if (!data.text && !data.visual_text) {
            showAssistantMessage(
                session,
                "没有识别到有效的题目内容，请重新拍摄或裁剪图片。",
                { isError: true }
            );
            return;
        }

        // 对照原图修改后再登记为题目；取消、Esc 均不产生聊天/错题记录。
        // 这里不再自动删除题干片段，避免把真实条件当成图形噪声删掉。
        const reviewed = await reviewRecognizedQuestion(file, data);
        if (!reviewed || !sessions.some(item => item.id === session.id)) return;
        const { text, visualText, userRequest } = reviewed;

        const questionParts = [];

        if (text) {
            questionParts.push(`【题目文字】\n${text}`);
        }

        if (visualText) {
            questionParts.push(`【图形信息】\n${visualText}`);
        }

        const questionText = questionParts.join("\n\n");
        const displayParts = [questionText];

        if (userRequest) {
            displayParts.push(`【我的要求】\n${userRequest}`);
        }

        const combinedText = displayParts.join("\n\n");
        const apiText = userRequest
            ? [
                "【当前指向题目】",
                questionText,
                "【当前指向题目结束】",
                "",
                "【本轮唯一需要执行的用户请求】",
                userRequest,
                "【本轮请求结束】",
                "",
                "只回答上面的本轮最新请求。题目正文只作为本轮题目背景，不要把要求混入题干。"
            ].join("\n")
            : undefined;

        session.messages.push({
            role: "user",
            text: combinedText,
            source: "ocr",
            apiText
        });

        maybeAutoNameSession(
            session,
            text || visualText || "图片识题",
            "ocr"
        );

        saveState();
        renderChat();
        renderSessions();
        renderInfo();

    } catch (error) {
        if (error && error.name === "AbortError") {
            // 用户主动撤销：不产生错误气泡，也不登记题目。
            return;
        }

        console.error("OCR 请求失败：", error);

        showAssistantMessage(
            session,
            "图片识别请求失败，请检查网络后重试。",
            { isError: true }
        );
        return;

    } finally {
        ocrRequestInFlight = false;
        ocrAbortController = null;
        ocrRequestId = "";
        ocrReviewInProgress = false;
        refreshInputAvailability();
    }

    // 只把用户核对后的题目交给 AI。
    // 后端 SYSTEM_PROMPT 会把“图片识题”默认处理为提示优先。
    await requestAiReply(session);
}


function isClearlyNonQuestionWrongBookText(text) {
    const value = String(text || "").trim();

    if (!value) return true;

    const patterns = [
        /这道题出现的是一份题库答案的片段/,
        /并不是一道待求解的题目/,
        /请问你希望我帮你做什么/,
        /我可以帮你出题/,
        /我先确认一下/,
        /先确认一下你希望/,
        /告诉我一个具体的.*(?:方向|章节|知识点)/,
        /你(?:希望|想要).*(?:方向|章节|知识点)/,
        /你选哪个/,
        /可以从以下.*选/,
        /从以下.*选择/,
        /如果你是想让我.*(?:核对|整理|讲解)/,
        /^(?:思路提示|解题提示|关键提示)[：:\s]/,
        /^做这道题[，,。\s]/,
        /^没关系[，,。\s].*(?:一步一步|一点一点)/,
        /^第(?:一|二|三|1|2|3)步[：:\s].*(?:先|看|理解|弄清)/,
        /以上是一个.*(?:测试文本|测试内容)/,
        /如果你要检测的是.*(?:渲染|格式|显示)/,
        /可以对照这些段落查看/,
        /这只是.*(?:示例|演示|测试)/
    ];

    return patterns.some(
        pattern => pattern.test(value)
    );
}

function stripQuestionWrappers(text) {
    return String(text || "")
        .replace(/【题目文字】/g, "")
        .replace(/【图形信息】/g, "")
        .replace(/\[图片识题\]/g, "")
        .trim();
}

function looksLikeChatQuestionText(text) {
    const original = String(text || "").trim();

    if (!original) return false;

    if (isClearlyNonQuestionWrongBookText(original)) {
        return false;
    }

    if (splitQuestionBankText(original).length) {
        return true;
    }

    const value = stripQuestionWrappers(
        original
    );

    if (
        !value
        || isShortLearningFollowUp(value)
        || isExerciseRequestText(value)
    ) {
        return false;
    }

    const numberedQuestion = (
        /(?:^|\n)\s*\d{1,2}\s*[、.．]\s*\S{3,}/m.test(value)
        && /[？?（(]|求|判断|写出|证明|计算|选择|填空/.test(value)
    );

    const parenthesizedSubQuestion = (
        /(?:^|\n)\s*[（(]\s*\d{1,2}\s*[)）]\s*\S{3,}/m.test(value)
        && /求|判断|写出|证明|计算|选择|填空|通路|回路|矩阵/.test(value)
    );

    if (
        numberedQuestion
        || parenthesizedSubQuestion
    ) {
        return true;
    }

    const strongStarts = [
        "已知",
        "给定",
        "设 ",
        "设：",
        "设有",
        "求",
        "求解",
        "证明",
        "计算",
        "判断",
        "写出",
        "列出",
        "下列"
    ];

    const compact = value
        .replace(/^[#>*\s]+/, "")
        .trim();

    if (
        strongStarts.some(signal => compact.startsWith(signal))
        && compact.length >= 10
    ) {
        return true;
    }

    if (
        /[？?]\s*$/.test(compact)
        && /(命题|公式|集合|关系|函数|图|矩阵|树|通路|回路|欧拉|哈密顿|递推|组合|群|环|域)/.test(compact)
        && compact.length >= 8
    ) {
        return true;
    }

    return false;
}

function looksLikeAiGeneratedQuestion(
    text,
    previousUserText = ""
) {
    const value = String(text || "").trim();

    if (
        !value
        || isClearlyNonQuestionWrongBookText(value)
    ) {
        return false;
    }

    const extracted = extractStructuredAiQuestion(
        value
    );

    if (!extracted) {
        return false;
    }

    const hasExplicitHeading = (
        explicitQuestionHeadingEnd(value) >= 0
    );

    if (hasExplicitHeading) {
        return looksLikeChatQuestionText(
            extracted
        );
    }

    return (
        countQuestionSubparts(extracted) >= 2
        && looksLikeChatQuestionText(
            extracted
        )
    );
}


function previousUserMessageBefore(session, messageIndex) {
    if (!session || !Array.isArray(session.messages)) {
        return null;
    }

    for (let index = messageIndex - 1; index >= 0; index -= 1) {
        const message = session.messages[index];

        if (
            message
            && message.role === "user"
            && typeof message.text === "string"
            && message.text.trim()
        ) {
            return message;
        }
    }

    return null;
}

function canMessageBeWrongQuestion(session, messageIndex, message) {
    return shouldOfferWrongBookAction(
        message,
        session,
        messageIndex
    );
}


function questionInfoFromChatMessage(session, messageIndex) {
    if (!session || !Array.isArray(session.messages)) {
        return null;
    }

    const message = session.messages[messageIndex];

    if (
        !message
        || message.isError
        || message.isNotice
    ) {
        return null;
    }

    const teaching = normalizeTeaching(session.teaching);
    const messageTeaching = normalizeTeaching(
        message.generatedTeaching
        || message.questionTeaching
    );
    const saved = normalizeLearningQuestion(
        session.learningQuestion
    );

    if (message.role === "ai") {
        recoverGeneratedQuestionFromAssistant(
            session,
            messageIndex,
            message
        );
    }

    let text = sanitizeStoredWrongQuestionText(
        extractQuestionOnlyFromMessage(
            message
        )
    );

    let source = message.source === "ocr"
        ? "ocr"
        : "text";

    if (message.role === "ai") {
        source = "ai";
    }

    if (!text) {
        return null;
    }

    const savedMatches = Boolean(
        saved
        && (
            wrongQuestionFingerprint(saved.text)
            === wrongQuestionFingerprint(text)
        )
    );

    const isRecent = (
        messageIndex >= session.messages.length - 2
    );

    return {
        text,
        knowledgePoints: messageTeaching
            ? messageTeaching.knowledge_points.slice(0, 4)
            : (
                savedMatches
                    ? saved.knowledgePoints
                    : (
                        isRecent
                            ? (teaching?.knowledge_points || []).slice(0, 4)
                            : []
                    )
            ),
        focusPoints: messageTeaching
            ? messageTeaching.focus_points.slice(0, 2)
            : (
                savedMatches
                    ? saved.focusPoints
                    : (
                        isRecent
                            ? (teaching?.focus_points || []).slice(0, 2)
                            : []
                    )
            ),
        category: messageTeaching
            ? messageTeaching.category
            : (
                savedMatches
                    ? saved.category
                    : (
                        isRecent
                            ? (teaching?.category || "")
                            : ""
                    )
            ),
        difficulty: messageTeaching?.difficulty
            || (savedMatches ? saved.difficulty : "")
            || (isRecent ? (teaching?.difficulty || "") : ""),
        source,
        referenceAnswer: (
            String(message.generatedAnswer || "").trim()
            || (
                savedMatches
                    ? saved.referenceAnswer
                    : ""
            )
        ),
        sessionId: session.id,
        updatedAt: Date.now()
    };
}

function markChatMessageAsWrong(sessionId, messageIndex) {
    const session = sessions.find(
        item => String(item.id) === String(sessionId)
    );

    if (!session) return;

    const questionInfo = questionInfoFromChatMessage(
        session,
        messageIndex
    );

    if (!questionInfo || !questionInfo.text) {
        window.alert(
            "没有从这条内容中提取到有效题目。你可以先把题目单独发一条消息，再加入错题本。"
        );
        return;
    }

    const choices = splitQuestionBankText(
        questionInfo.text
    );

    if (
        choices.length
        && openWrongQuestionPicker(
            questionInfo,
            choices
        )
    ) {
        return;
    }

    openWrongSafePreview(
        questionInfo
    );
}

async function deleteChatMessage(sessionId, messageIndex) {
    const session = sessions.find(
        item => String(item.id) === String(sessionId)
    );

    if (
        !session
        || !Array.isArray(session.messages)
        || !session.messages[messageIndex]
    ) {
        return;
    }

    const confirmed = window.confirm(
        "删除这条消息吗？\n\n只删除聊天中的这条消息；已经加入错题本的内容不会被删除。"
    );

    if (!confirmed) return;

    const chat = document.getElementById("chat");

    if (chat) {
        preserveChatScrollOnce = chat.scrollTop;
    }

    const removed = session.messages[messageIndex];

    session.messages.splice(
        messageIndex,
        1
    );

    const learningQuestion = normalizeLearningQuestion(
        session.learningQuestion
    );

    if (learningQuestion) {
        const removedText = removed.role === "ai"
            ? (
                extractAiGeneratedExerciseText(
                    removed.text
                ) || removed.text
            )
            : removed.text;

        if (
            wrongQuestionFingerprint(learningQuestion.text)
            === wrongQuestionFingerprint(removedText)
        ) {
            session.learningQuestion = null;
        }
    }

    // 删除当前题后，不继续沿用已删除题目的 session.teaching。
    // 按剩余消息历史重新确定当前题；如果上一题没有本地教学快照，
    // 再通过轻量 /analyze-questions 接口补一次分类。
    await ensureActiveQuestionAfterHistoryChange(
        session
    );

    saveState();
    renderChat();
    renderSessions();
    renderInfo();
    renderLearningSummary();
}


// -----------------------------
// AI 消息与打字效果
// -----------------------------
function addAssistantMessage(
    session,
    text,
    meta = {}
) {
    if (!session || !text) return;

    session.messages.push({
        role: "ai",
        text,
        generatedExercise: Boolean(
            meta.generatedExercise
        ),
        generatedQuestion: typeof meta.generatedQuestion === "string"
            ? meta.generatedQuestion
            : "",
        generatedAnswer: typeof meta.generatedAnswer === "string"
            ? meta.generatedAnswer
            : "",
        generatedTeaching: normalizeTeaching(
            meta.generatedTeaching
        ),
        targetQuestionFingerprint: typeof meta.targetQuestionFingerprint === "string"
            ? meta.targetQuestionFingerprint
            : "",
        isError: Boolean(meta.isError),
        isNotice: Boolean(meta.isNotice)
    });
}

function showAssistantMessage(
    session,
    text,
    meta = {}
) {
    if (!session) return;

    if (currentId === session.id && !typingTimer) {
        startTyping(text, session, meta);
        return;
    }

    addAssistantMessage(
        session,
        text,
        meta
    );

    saveState();
    renderAll();
}

function showCurrentError(text) {
    let session = getCurrent();

    if (!session) {
        newChat();
        session = getCurrent();
    }

    showAssistantMessage(
        session,
        text,
        { isError: true }
    );
}

function startTyping(
    text,
    session,
    meta = {}
) {
    if (!session || !text) return;

    if (currentId !== session.id) {
        addAssistantMessage(
            session,
            text,
            meta
        );
        saveState();
        return;
    }

    if (typingTimer) {
        forceCompleteTyping();
    }

    // 长回答继续逐字输出会等待几十秒，期间 LaTeX 只能以源码形式裸露。
    // 超过阈值时直接完整渲染 Markdown + MathJax；短回答仍保留打字机效果。
    if (text.length >= LONG_RESPONSE_DIRECT_RENDER_CHARS) {
        addAssistantMessage(
            session,
            text,
            meta
        );

        forceChatBottomOnce = true;
        saveState();
        renderChat();
        renderSessions();
        renderInfo();
        refreshInputAvailability();
        return;
    }

    typingFullText = text;
    typingSessionId = session.id;
    typingMeta = {
        generatedExercise: Boolean(
            meta.generatedExercise
        ),
        generatedQuestion: typeof meta.generatedQuestion === "string"
            ? meta.generatedQuestion
            : "",
        generatedAnswer: typeof meta.generatedAnswer === "string"
            ? meta.generatedAnswer
            : "",
        generatedTeaching: normalizeTeaching(
            meta.generatedTeaching
        ),
        targetQuestionFingerprint: typeof meta.targetQuestionFingerprint === "string"
            ? meta.targetQuestionFingerprint
            : "",
        isError: Boolean(meta.isError),
        isNotice: Boolean(meta.isNotice)
    };

    const chat = document.getElementById("chat");
    if (!chat) return;

    typingAutoFollow = isChatNearBottom(
        chat,
        90
    );
    typingScrollLockedByUser = false;
    lastTypingAutoScrollAt = 0;

    const div = document.createElement("div");
    div.className = "msg ai";
    chat.appendChild(div);

    typingDiv = div;

    refreshInputAvailability();

    let index = 0;

    typingTimer = setInterval(() => {
        if (!typingDiv) {
            clearInterval(typingTimer);
            typingTimer = null;
            return;
        }

        if (index < text.length) {
            const nextIndex = Math.min(
                text.length,
                index + TYPING_CHARS_PER_TICK
            );

            typingDiv.textContent += text.slice(
                index,
                nextIndex
            );
            index = nextIndex;

            maybeAutoFollowTyping();

            return;
        }

        clearInterval(typingTimer);

        // 修复旧版核心 Bug：
        // 正常打字结束后必须清空 typingTimer，
        // 否则 send() 会永远认为仍在打字。
        typingTimer = null;

        finishTyping();
    }, TYPING_RENDER_INTERVAL);
}

function finishTyping() {
    const session = sessions.find(
        item => item.id === typingSessionId
    );

    if (typingDiv) {
        typingDiv.innerHTML =
            `<div class="ai-content">${markdownToHtml(
                prepareAiDisplayText(typingFullText)
            )}</div>`;
    }

    if (session) {
        addAssistantMessage(
            session,
            typingFullText,
            typingMeta || {}
        );
    }

    const finishedDiv = typingDiv;

    typingFullText = "";
    typingDiv = null;
    typingSessionId = null;
    typingMeta = null;

    saveState();

    if (
        typingAutoFollow
        && !typingScrollLockedByUser
    ) {
        forceChatBottomOnce = true;
    }

    // 重新渲染已落盘的最后一条 AI 消息，立即补上“删除”等消息操作。
    // 旧版只把 typingDiv 换成最终 HTML，没有重新生成 msg-actions，
    // 所以最新一条回答在下一次刷新前看不到删除按钮。
    renderChat();
    renderSessions();
    renderInfo();

    refreshInputAvailability();

    typingAutoFollow = true;
    typingScrollLockedByUser = false;
    lastTypingAutoScrollAt = 0;
}

// 强制完成当前打字动画
function forceCompleteTyping() {
    if (!typingTimer) {
        return;
    }

    clearInterval(typingTimer);
    typingTimer = null;

    const session = sessions.find(
        item => item.id === typingSessionId
    );

    if (typingDiv) {
        typingDiv.innerHTML =
            `<div class="ai-content">${markdownToHtml(
                prepareAiDisplayText(typingFullText)
            )}</div>`;
    }

    if (session) {
        addAssistantMessage(
            session,
            typingFullText,
            typingMeta || {}
        );
    }

    const finishedDiv = typingDiv;

    typingFullText = "";
    typingDiv = null;
    typingSessionId = null;
    typingMeta = null;

    saveState();

    if (
        typingAutoFollow
        && !typingScrollLockedByUser
    ) {
        forceChatBottomOnce = true;
    }

    // 重新渲染已落盘的最后一条 AI 消息，立即补上“删除”等消息操作。
    // 旧版只把 typingDiv 换成最终 HTML，没有重新生成 msg-actions，
    // 所以最新一条回答在下一次刷新前看不到删除按钮。
    renderChat();
    renderSessions();
    renderInfo();

    refreshInputAvailability();

    typingAutoFollow = true;
    typingScrollLockedByUser = false;
    lastTypingAutoScrollAt = 0;
}


// -----------------------------
// 渲染聊天
// -----------------------------
function renderChat() {
    const chat = document.getElementById("chat");
    if (!chat) return;

    const oldScrollTop = chat.scrollTop;
    const oldBottomDistance = chatBottomDistance(chat);
    const oldNearBottom = oldBottomDistance <= 90;
    const requestedScrollTop = (
        preserveChatScrollOnce !== null
        && Number.isFinite(preserveChatScrollOnce)
    )
        ? preserveChatScrollOnce
        : null;

    preserveChatScrollOnce = null;

    if (
        window.MathJax
        && typeof MathJax.typesetClear === "function"
    ) {
        try {
            MathJax.typesetClear([chat]);
        } catch (error) {
            console.warn("MathJax 清理旧公式失败：", error);
        }
    }

    chat.innerHTML = "";

    const session = getCurrent();

    if (!session) {
        chat.innerHTML =
            '<div class="empty-tip">暂无对话</div>';
        lastRenderedChatSessionId = null;
        return;
    }

    const sessionChanged = (
        String(lastRenderedChatSessionId ?? "")
        !== String(session.id)
    );

    for (
        let messageIndex = 0;
        messageIndex < session.messages.length;
        messageIndex += 1
    ) {
        const message = session.messages[messageIndex];

        const div = document.createElement("div");
        div.dataset.messageIndex = String(messageIndex);
        div.className =
            "msg " + (
                message.role === "user"
                    ? "user"
                    : "ai"
            );

        const content = document.createElement("div");
        content.className = "msg-content";

        if (message.role === "user") {
            content.textContent = message.text;
            content.style.whiteSpace = "pre-wrap";
        } else {
            content.innerHTML =
                `<div class="ai-content">${markdownToHtml(
                    prepareAiDisplayText(message.text)
                )}</div>`;
        }

        div.appendChild(content);

        const difficultyTeaching = normalizeTeaching(
            message.role === "user"
                ? (
                    isExerciseRequestText(message.text)
                        ? null
                        : message.questionTeaching
                )
                : (
                    message.generatedExercise
                        ? message.generatedTeaching
                        : null
                )
        );

        if (difficultyTeaching?.difficulty) {
            const difficultyBadge = document.createElement("div");
            difficultyBadge.className = "difficulty-badge";
            difficultyBadge.textContent = difficultyTeaching.difficulty;
            div.insertBefore(difficultyBadge, content);
        }

        const actions = document.createElement("div");
        actions.className = "msg-actions";

        if (
            shouldShowChatCopyButton(
                message,
                session,
                messageIndex
            )
        ) {
            const copyButton = document.createElement("button");
            copyButton.type = "button";
            copyButton.textContent = "复制";
            copyButton.title = "复制这道题目";
            copyButton.onclick = () => copyChatQuestionOnly(
                message,
                session,
                messageIndex
            );
            actions.appendChild(copyButton);
        }

        if (
            shouldOfferWrongBookAction(
                message,
                session,
                messageIndex
            )
        ) {
            const wrongButton = document.createElement("button");
            wrongButton.type = "button";
            wrongButton.textContent = "记为错题";
            wrongButton.title = "把这一条题目加入错题本";
            wrongButton.onclick = () => (
                markChatMessageAsWrong(
                    session.id,
                    messageIndex
                )
            );

            actions.appendChild(wrongButton);
        }

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "danger";
        deleteButton.textContent = "删除";
        deleteButton.title = "删除这一条聊天消息";
        deleteButton.onclick = () => (
            deleteChatMessage(
                session.id,
                messageIndex
            )
        );

        actions.appendChild(deleteButton);

        div.appendChild(actions);
        chat.appendChild(div);
    }

    const shouldStickBottom = Boolean(
        forceChatBottomOnce
        || sessionChanged
        || (requestedScrollTop === null && oldNearBottom)
    );

    forceChatBottomOnce = false;
    lastRenderedChatSessionId = session.id;

    // 先给一个同步位置，避免 MathJax 渲染期间出现肉眼可见的闪跳。
    if (shouldStickBottom) {
        scrollChatToBottom();
    } else if (requestedScrollTop !== null) {
        chat.scrollTop = requestedScrollTop;
    } else {
        chat.scrollTop = oldScrollTop;
    }

    renderMath(chat).then(() => {
        // 公式渲染会改变消息高度，必须在排版完成后再恢复一次位置。
        // 否则长公式/矩阵会把当前视口“顶”到上方。
        if (shouldStickBottom) {
            scrollChatToBottom();
            return;
        }

        if (requestedScrollTop !== null) {
            chat.scrollTop = Math.min(
                requestedScrollTop,
                Math.max(0, chat.scrollHeight - chat.clientHeight)
            );
            return;
        }

        chat.scrollTop = Math.min(
            oldScrollTop,
            Math.max(0, chat.scrollHeight - chat.clientHeight)
        );
    });
}


// -----------------------------
// 会话列表
// -----------------------------
function renderSessions() {
    const box = document.getElementById("sessions");
    if (!box) return;

    refreshUnnamedSessionNames();
    box.innerHTML = "";

    for (const session of sessions) {
        const isCurrent = (
            String(session.id) === String(currentId)
        );

        const div = document.createElement("div");
        div.className = isCurrent
            ? "session active"
            : "session";

        if (isCurrent) {
            div.setAttribute(
                "aria-current",
                "true"
            );
        }

        const span = document.createElement("span");
        span.innerText = session.name;
        span.title = session.name;

        span.onclick = () => {
            if (typingTimer) {
                forceCompleteTyping();
            }

            currentId = session.id;
            saveState();
            renderAll();
            animateMobileConversationSwitch();
        };

        span.ondblclick = () => {
            if (typingTimer) {
                forceCompleteTyping();
            }

            const name = prompt(
                "修改名称：",
                session.name
            );

            if (
                typeof name === "string"
                && name.trim()
            ) {
                session.name = name.trim();
                saveState();
                renderSessions();
                renderInfo();
            }
        };

        const del = document.createElement("button");
        del.className = "del";
        del.type = "button";
        del.textContent = "";
        del.title = "删除这个对话";
        del.setAttribute(
            "aria-label",
            "删除这个对话"
        );

        del.onclick = event => {
            event.stopPropagation();

            const confirmed = window.confirm(
                "确定删除这段对话吗？\n\n这段对话产生的学习统计会同步删除；已经加入错题本的题目仍会保留。"
            );

            if (!confirmed) {
                return;
            }

            if (typingTimer) {
                forceCompleteTyping();
            }

            removeLearningEventsForSession(
                session.id
            );

            busySessionIds.delete(
                sessionBusyKey(session.id)
            );

            sessions = sessions.filter(
                item => item.id !== session.id
            );

            if (currentId === session.id) {
                currentId = sessions.length
                    ? sessions[0].id
                    : null;
            }

            // 删除最后一个会话时保持空列表，不自动补一个“新对话”。
            // 下一次真正发送文字或上传图片时，send()/handleImageSelected()
            // 会按需调用 newChat() 创建会话。
            if (!sessions.length) {
                currentId = null;
            }

            saveState();
            renderAll();
        };

        div.appendChild(span);
        div.appendChild(del);
        box.appendChild(div);
    }
}


function uniqueTextList(list, limit = 6) {
    return [
        ...new Set(
            (Array.isArray(list) ? list : [])
                .filter(item => typeof item === "string" && item.trim())
                .map(item => item.trim())
        )
    ].slice(0, limit);
}

function normalizeKnowledgeGraphData(data) {
    if (!data || typeof data !== "object") {
        return null;
    }

    const nodes = Array.isArray(data.nodes)
        ? data.nodes
            .filter(node => node && typeof node === "object")
            .map(node => ({
                id: typeof node.id === "string" && node.id.trim()
                    ? node.id.trim()
                    : "",
                name: typeof node.name === "string" && node.name.trim()
                    ? node.name.trim()
                    : "",
                category: typeof node.category === "string" && node.category.trim()
                    ? node.category.trim()
                    : "未分类",
                prerequisites: uniqueTextList(node.prerequisites, 8),
                level: typeof node.level === "string"
                    ? node.level.trim()
                    : "",
                note: typeof node.note === "string"
                    ? node.note.trim()
                    : ""
            }))
            .filter(node => node.id && node.name)
        : [];

    return {
        version: Number.isFinite(data.version)
            ? data.version
            : 1,
        title: typeof data.title === "string" && data.title.trim()
            ? data.title.trim()
            : "离散数学知识图谱",
        description: typeof data.description === "string"
            ? data.description.trim()
            : "",
        nodes
    };
}

function readInitialKnowledgeGraphData() {
    const element = document.getElementById(
        "knowledgeGraphData"
    );

    if (!element) {
        return null;
    }

    try {
        return JSON.parse(
            element.textContent || "{}"
        );
    } catch (error) {
        console.warn(
            "知识图谱初始数据解析失败：",
            error
        );
        return null;
    }
}

async function ensureKnowledgeGraphData() {
    if (knowledgeGraphData) {
        return knowledgeGraphData;
    }

    if (knowledgeGraphLoading) {
        return null;
    }

    knowledgeGraphLoading = true;

    try {
        // 唯一数据源是 knowledge_graph.json。
        // Flask 在首页渲染时把同一份数据注入页面，
        // 无额外 fetch，也不会出现前后端两份图谱不同步。
        knowledgeGraphData = normalizeKnowledgeGraphData(
            readInitialKnowledgeGraphData()
        );

        if (
            !knowledgeGraphData
            || !knowledgeGraphData.nodes.length
        ) {
            throw new Error("知识图谱数据为空。");
        }

        return knowledgeGraphData;
    } catch (error) {
        console.warn("知识图谱加载失败：", error);
        knowledgeGraphData = null;
        throw error;
    } finally {
        knowledgeGraphLoading = false;
    }
}

function getKnowledgeGraphCategories() {
    if (!knowledgeGraphData) return [];

    return [
        ...new Set(
            knowledgeGraphData.nodes.map(
                node => node.category
            )
        )
    ].sort((a, b) => a.localeCompare(
        b,
        "zh-Hans-CN"
    ));
}

function getEffectiveSessionTeaching(session) {
    if (!session) return null;

    const current = normalizeTeaching(
        session.teaching
    );

    // 右侧信息必须跟“当前指向的题”走，而不是机械取时间上最新的一题。
    // 因此 A -> B -> “上一道题再讲一下”时，这里应重新读取 A 的教学快照。
    const activeCandidate = activeQuestionCandidateFromHistory(
        session
    );

    if (activeCandidate) {
        const own = candidateTeachingSnapshot(
            session,
            activeCandidate
        );

        if (own) {
            return own;
        }

        const learningQuestion = normalizeLearningQuestion(
            session.learningQuestion
        );

        if (
            learningQuestion
            && wrongQuestionFingerprint(learningQuestion.text)
                === wrongQuestionFingerprint(activeCandidate.text)
        ) {
            if (current) {
                return current;
            }

            return {
                category: learningQuestion.category || "待识别",
                related_categories: [],
                knowledge_points: learningQuestion.knowledgePoints,
                focus_points: learningQuestion.focusPoints,
                prerequisite_points: [],
                knowledge_path: learningQuestion.knowledgePoints,
                question_type: activeCandidate.role === "ai"
                    ? "练习题"
                    : "综合题",
                mode: activeCandidate.role === "ai"
                    ? "exercise"
                    : "hint",
                mode_label: activeCandidate.role === "ai"
                    ? "练习出题"
                    : "提示引导",
                confidence: "中",
                input_source: activeCandidate.source === "ocr"
                    ? "图片识题"
                    : "文本输入"
            };
        }
    }

    return current;
}


function getCurrentKnowledgeContext() {
    const session = getCurrent();
    const teaching = getEffectiveSessionTeaching(
        session
    );
    const learningQuestion = currentLearningQuestion(
        session,
        teaching
    );

    const focusPoints = uniqueTextList([
        ...(teaching?.focus_points || []),
        ...(learningQuestion?.focusPoints || [])
    ], 2);

    const knowledgePoints = uniqueTextList([
        ...(teaching?.knowledge_points || []),
        ...(learningQuestion?.knowledgePoints || [])
    ], 6);

    const prerequisitePoints = uniqueTextList(
        teaching?.prerequisite_points || [],
        6
    );

    const knowledgePath = uniqueTextList(
        teaching?.knowledge_path || [],
        10
    );

    return {
        category: teaching?.category
            || learningQuestion?.category
            || "",
        focusPoints,
        knowledgePoints,
        prerequisitePoints,
        knowledgePath
    };
}

function isHistorySystemMetaText(text) {
    const value = String(text || "")
        .replace(/\s+/g, "")
        .toLowerCase();

    if (!value) return true;

    const metaKeywords = [
        "错题本",
        "知识图谱",
        "图谱",
        "渲染",
        "滚轮",
        "滚动",
        "按钮",
        "会话",
        "对话栏",
        "输入框",
        "页面",
        "界面",
        "外观",
        "背景",
        "删除消息",
        "删除对话",
        "ocr扫描",
        "ocr识别",
        "github",
        "代码",
        "部署",
        "zeabur",
        "服务器",
        "模型生成",
        "ai生成",
        "功能",
        "bug"
    ];

    return metaKeywords.some(
        item => value.includes(item)
    );
}

function looksLikeFormalStudyQuestionForHistory(
    text,
    message = null
) {
    const value = sanitizeStoredWrongQuestionText(
        text
    ).trim();

    if (!value) {
        return false;
    }

    // 出题请求只负责生成下一道题，本身不进入“题目历史”。
    if (isExerciseRequestText(value)) {
        return false;
    }

    if (isHistorySystemMetaText(value)) {
        return false;
    }

    if (message?.source === "ocr") {
        return isRecordableOcrQuestionMessage(message);
    }

    if (/【(?:题目|练习题|题目文字)】/.test(value)) {
        return true;
    }

    if (countTopLevelQuestionParts(value) >= 1) {
        return true;
    }

    const compact = value
        .replace(/^[#>*\s]+/, "")
        .trim();

    if (
        /^(?:设|已知|给定|下列|若|对于|在.+中|求|证明|计算|判断|写出|列出|选择|填空|解答)/.test(
            compact
        )
    ) {
        return true;
    }

    // 概念型学习问题允许进入历史，但必须已经被 teaching.py
    // 明确识别成离散数学模块；系统功能问句不会因为一个问号就进来。
    const teaching = normalizeTeaching(
        message?.questionTeaching
        || message?.generatedTeaching
    );

    if (
        teaching
        && teaching.category
        && teaching.category !== "待识别"
        && /^(?:什么是|为什么|为何|如何|怎样)/.test(compact)
    ) {
        return true;
    }

    return false;
}


function collectConversationQuestionCandidates(session) {
    if (
        !session
        || !Array.isArray(session.messages)
    ) {
        return [];
    }

    const candidates = [];
    const seen = new Set();

    for (
        let index = 0;
        index < session.messages.length;
        index += 1
    ) {
        const message = session.messages[index];

        if (
            !message
            || typeof message.text !== "string"
        ) {
            continue;
        }

        let question = "";

        if (message.role === "user") {
            if (message.isRetestAnswer) {
                continue;
            }

            if (
                message.source !== "ocr"
                && isConversationControlOnly(
                    message.text
                )
            ) {
                continue;
            }

            question = extractQuestionOnlyFromMessage(
                message
            );

            if (
                !looksLikeFormalStudyQuestionForHistory(
                    question,
                    message
                )
            ) {
                continue;
            }
        } else if (message.role === "ai") {
            const trustedGenerated = sanitizeStoredWrongQuestionText(
                message.generatedQuestion || ""
            );

            if (trustedGenerated) {
                // generatedQuestion 是题目身份的唯一强标记。只要存在，
                // 就直接进入题目历史，保证后续 AI 能再次定位到自己出的题。
                message.generatedExercise = true;
                question = trustedGenerated;
            } else {
                // 兼容旧记录：仅在上一条用户明确要求“出题”时恢复 AI 生成题。
                question = recoverGeneratedQuestionFromAssistant(
                    session,
                    index,
                    message
                );

                if (
                    !question
                    || !looksLikeFormalStudyQuestionForHistory(
                        question,
                        message
                    )
                ) {
                    continue;
                }
            }
        } else {
            continue;
        }

        const fingerprint = wrongQuestionFingerprint(
            question
        );

        if (
            !fingerprint
            || seen.has(fingerprint)
        ) {
            continue;
        }

        seen.add(fingerprint);

        candidates.push({
            key: `${index}:${fingerprint}`,
            index,
            role: message.role,
            source: message.source || "",
            text: question
        });
    }

    return candidates;
}


function activeQuestionCandidateFromHistory(session) {
    if (
        !session
        || !Array.isArray(session.messages)
    ) {
        return null;
    }

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) {
        return null;
    }

    // 1. 如果最近一次“上一道题”已经被前端解析过，直接使用它记录的
    // 目标指纹。这样 AI 回复回来后不会又被最新题目的 teaching 覆盖。
    for (
        let index = session.messages.length - 1;
        index >= 0;
        index -= 1
    ) {
        const message = session.messages[index];

        if (!message || message.role !== "user") {
            continue;
        }

        if (
            isQuestionNavigationFollowUp(message.text)
            && message.targetQuestionFingerprint
        ) {
            const target = candidates.find(candidate => (
                questionCandidateFingerprint(candidate)
                === message.targetQuestionFingerprint
            ));

            if (target) {
                // 如果该导航之后已经出现真正的新题，新题应成为当前题。
                const newerQuestion = candidates.find(
                    candidate => candidate.index > index
                );

                if (!newerQuestion) {
                    return target;
                }
            }

            break;
        }

        // 最近用户消息若是真正的新题，就不再向前寻找旧导航命令。
        if (
            message.role === "user"
            && looksLikeActualLearningProblem(message)
        ) {
            break;
        }
    }

    // 2. 普通“继续/再讲一下”应保持当前 learningQuestion。
    const savedCandidate = currentQuestionCandidateFromLearningState(
        session
    );

    if (savedCandidate) {
        const latestCandidate = candidates[candidates.length - 1];

        // 旧版本可能没有把 AI 生成题写进 learningQuestion。恢复出一个
        // 时间上更新的真实题目后，应让它成为当前题，而不是继续锁死旧题。
        if (
            latestCandidate
            && latestCandidate.index > savedCandidate.index
        ) {
            return latestCandidate;
        }

        return savedCandidate;
    }

    // 3. 旧会话没有 learningQuestion 时，按历史命令做兼容恢复。
    const byIndex = new Map(
        candidates.map(candidate => [
            candidate.index,
            candidate
        ])
    );

    const history = [];
    let activePos = null;

    for (
        let index = 0;
        index < session.messages.length;
        index += 1
    ) {
        const message = session.messages[index];

        if (!message) continue;

        if (
            message.role === "user"
            && isQuestionNavigationFollowUp(
                message.text
            )
        ) {
            if (history.length) {
                const structural = structuralQuestionReference(
                    message.text
                );

                if (structural) {
                    const basePosition = activePos === null
                        ? history.length - 1
                        : activePos;
                    const resolvedPosition = resolveStructuralQuestionPosition(
                        structural,
                        history.length,
                        basePosition
                    );

                    if (resolvedPosition >= 0) {
                        activePos = resolvedPosition;
                    }
                }
            }

            continue;
        }

        const candidate = byIndex.get(index);

        if (!candidate) continue;

        history.push(candidate);
        activePos = history.length - 1;
    }

    if (
        activePos === null
        || !history[activePos]
    ) {
        return candidates[candidates.length - 1];
    }

    return history[activePos];
}


function candidateTeachingSnapshot(
    session,
    candidate
) {
    if (!session || !candidate) {
        return null;
    }

    const message = session.messages?.[
        candidate.index
    ];

    if (!message) {
        return null;
    }

    const own = normalizeTeaching(
        candidate.role === "ai"
            ? message.generatedTeaching
            : message.questionTeaching
    );

    if (own) {
        return own;
    }

    const saved = normalizeLearningQuestion(
        session.learningQuestion
    );

    if (
        saved
        && wrongQuestionFingerprint(saved.text)
            === wrongQuestionFingerprint(
                candidate.text
            )
    ) {
        return {
            category: saved.category || "待识别",
            related_categories: [],
            knowledge_points: saved.knowledgePoints,
            focus_points: saved.focusPoints,
            prerequisite_points: [],
            knowledge_path: saved.knowledgePoints,
            question_type: candidate.role === "ai"
                ? "练习题"
                : "综合题",
            difficulty: saved.difficulty || "",
            mode: candidate.role === "ai"
                ? "exercise"
                : "hint",
            mode_label: candidate.role === "ai"
                ? "练习出题"
                : "提示引导",
            confidence: "中",
            input_source: candidate.source === "ocr"
                ? "图片识题"
                : "文本输入"
        };
    }

    return null;
}


function applyQuestionCandidateAsCurrent(
    session,
    candidate,
    teachingOverride = null
) {
    if (!session || !candidate) {
        return false;
    }

    const message = session.messages?.[
        candidate.index
    ];

    if (!message) {
        return false;
    }

    const teaching = normalizeTeaching(
        teachingOverride
    ) || candidateTeachingSnapshot(
        session,
        candidate
    );

    if (teaching) {
        if (candidate.role === "ai") {
            message.generatedTeaching = teaching;
        } else {
            message.questionTeaching = teaching;
        }
    }

    session.teaching = teaching;

    session.learningQuestion = {
        text: candidate.text,
        knowledgePoints: (
            teaching?.knowledge_points || []
        ).slice(0, 4),
        focusPoints: (
            teaching?.focus_points || []
        ).slice(0, 2),
        category: teaching?.category || "",
        difficulty: teaching?.difficulty || "",
        source: candidate.role === "ai"
            ? "ai"
            : (
                candidate.source === "ocr"
                    ? "ocr"
                    : "text"
            ),
        referenceAnswer: String(
            message.generatedAnswer || ""
        ).trim().slice(0, 3000),
        sessionId: session.id,
        updatedAt: Date.now()
    };

    return Boolean(teaching);
}


async function analyzeSingleQuestionTeaching(
    question,
    key = "current"
) {
    const text = String(question || "").trim();
    if (!text) return null;

    try {
        const response = await fetch(
            "/analyze-questions",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    questions: [{
                        key,
                        text
                    }]
                })
            }
        );

        const payload = await response.json();

        if (!response.ok) {
            throw new Error(
                payload?.error
                || "题目知识识别失败。"
            );
        }

        return normalizeTeaching(
            payload?.results?.[0]?.teaching
        );
    } catch (error) {
        console.warn(
            "题目知识识别失败：",
            error
        );
        return null;
    }
}

async function ensureActiveQuestionAfterHistoryChange(
    session
) {
    if (!session) {
        return;
    }

    const candidate = activeQuestionCandidateFromHistory(
        session
    );

    if (!candidate) {
        session.teaching = null;
        session.learningQuestion = null;
        return;
    }

    const existingTeaching = normalizeTeaching(
        candidateTeachingSnapshot(session, candidate)
    );

    // 旧版本曾把无法命中的题目写成“离散数学综合”。这种快照不能继续沿用，
    // 必须重新走当前分类器；否则修好分类规则后右侧仍会显示旧的“综合”。
    if (
        existingTeaching
        && !isGenericTeachingCategory(existingTeaching.category)
        && applyQuestionCandidateAsCurrent(
            session,
            candidate,
            existingTeaching
        )
    ) {
        return;
    }

    try {
        const response = await fetch(
            "/analyze-questions",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    questions: [{
                        key: candidate.key,
                        text: candidate.text
                    }]
                })
            }
        );

        const payload = await response.json();

        if (!response.ok) {
            throw new Error(
                payload?.error
                || "题目知识识别失败。"
            );
        }

        const teaching = normalizeTeaching(
            payload?.results?.[0]?.teaching
        );

        if (!teaching) {
            return;
        }

        const message = session.messages?.[
            candidate.index
        ];

        if (message) {
            if (candidate.role === "ai") {
                message.generatedTeaching = teaching;
            } else {
                message.questionTeaching = teaching;
            }
        }

        applyQuestionCandidateAsCurrent(
            session,
            candidate,
            teaching
        );
    } catch (error) {
        console.warn(
            "删除题目后恢复上一题失败：",
            error
        );
    }
}


async function refreshConversationKnowledgeIndex(
    session = getCurrent()
) {
    if (!session) {
        return [];
    }

    const candidates = collectConversationQuestionCandidates(
        session
    );

    if (!candidates.length) {
        return [];
    }

    let payload = null;

    try {
        const response = await fetch(
            "/analyze-questions",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    questions: candidates.map(
                        item => ({
                            key: item.key,
                            text: item.text
                        })
                    )
                })
            }
        );

        payload = await response.json();

        if (!response.ok) {
            throw new Error(
                payload?.error
                || "历史题目知识识别失败。"
            );
        }
    } catch (error) {
        console.warn(
            "历史题目知识识别失败：",
            error
        );
        return candidates;
    }

    const results = new Map(
        (payload?.results || []).map(
            item => [
                String(item?.key || ""),
                normalizeTeaching(
                    item?.teaching
                )
            ]
        )
    );

    let latestTeaching = null;
    let latestCandidate = null;

    for (const candidate of candidates) {
        const message = session.messages[
            candidate.index
        ];

        if (!message) continue;

        const teaching = results.get(
            candidate.key
        );

        if (!teaching) {
            continue;
        }

        if (candidate.role === "ai") {
            message.generatedExercise = true;
            message.generatedQuestion = candidate.text;
            message.generatedTeaching = teaching;
        } else {
            message.questionTeaching = teaching;
        }

        latestTeaching = teaching;
        latestCandidate = candidate;
    }

    if (
        latestTeaching
        && latestCandidate
    ) {
        session.teaching = latestTeaching;

        const latestMessage = session.messages[
            latestCandidate.index
        ];

        session.learningQuestion = {
            text: latestCandidate.text,
            knowledgePoints: (
                latestTeaching.knowledge_points || []
            ).slice(0, 4),
            focusPoints: (
                latestTeaching.focus_points || []
            ).slice(0, 2),
            category: latestTeaching.category || "",
            difficulty: latestTeaching.difficulty || "",
            source: (
                latestCandidate.role === "ai"
                    ? "ai"
                    : (
                        latestCandidate.source === "ocr"
                            ? "ocr"
                            : "text"
                    )
            ),
            referenceAnswer: (
                latestMessage?.generatedAnswer || ""
            ),
            sessionId: session.id,
            updatedAt: Date.now()
        };
    }

    saveState();
    renderInfo();

    return candidates;
}


function getConversationKnowledgeContext() {
    const session = getCurrent();

    if (!session) {
        return {
            category: "",
            categories: [],
            focusPoints: [],
            knowledgePoints: [],
            prerequisitePoints: [],
            knowledgePath: [],
            questionCount: 0,
            scope: "conversation"
        };
    }

    const knowledgePoints = [];
    const prerequisitePoints = [];
    const knowledgePath = [];
    const categories = [];
    const questionFingerprints = new Set();

    let classifiedMessageCount = 0;

    const history = getConversationQuestionHistory(
        session
    );

    for (const item of history) {
        const teaching = normalizeTeaching(
            item.teaching
        );

        if (item.text) {
            questionFingerprints.add(
                wrongQuestionFingerprint(
                    item.text
                )
            );
        }

        if (
            !teaching
            || teaching.category === "待识别"
        ) {
            continue;
        }

        knowledgePoints.push(
            ...teaching.knowledge_points,
            ...teaching.focus_points
        );

        prerequisitePoints.push(
            ...teaching.prerequisite_points
        );

        knowledgePath.push(
            ...teaching.knowledge_path
        );

        if (teaching.category) {
            categories.push(
                teaching.category
            );
        }

        classifiedMessageCount += 1;
    }

    // 只有严格历史题一条都没有时，才使用旧学习数据兜底。
    if (
        history.length === 0
        && classifiedMessageCount === 0
    ) {
        const seenEvents = learningState.events.filter(
            event => (
                String(event.sessionId)
                    === String(session.id)
                && event.type === "seen"
            )
        );

        for (const event of seenEvents) {
            knowledgePoints.push(
                ...(event.points || [])
            );
        }

        const learningQuestion = normalizeLearningQuestion(
            session.learningQuestion
        );

        if (
            learningQuestion
            && looksLikeFormalStudyQuestionForHistory(
                learningQuestion.text
            )
        ) {
            knowledgePoints.push(
                ...learningQuestion.knowledgePoints,
                ...learningQuestion.focusPoints
            );

            if (learningQuestion.category) {
                categories.push(
                    learningQuestion.category
                );
            }

            if (learningQuestion.text) {
                questionFingerprints.add(
                    wrongQuestionFingerprint(
                        learningQuestion.text
                    )
                );
            }
        }
    }

    const uniqueKnowledge = uniqueTextList(
        knowledgePoints,
        40
    );

    for (const point of uniqueKnowledge) {
        const node = findKnowledgeGraphNodeByName(
            point
        );

        if (node?.category) {
            categories.push(
                node.category
            );
        }
    }

    const uniqueCategories = uniqueTextList(
        categories.filter(
            item => (
                item
                && item !== "待识别"
            )
        ),
        12
    );

    return {
        category: (
            uniqueCategories.length === 1
                ? uniqueCategories[0]
                : "全部"
        ),
        categories: uniqueCategories,
        focusPoints: [],
        knowledgePoints: uniqueKnowledge,
        prerequisitePoints: uniqueTextList(
            prerequisitePoints,
            24
        ),
        knowledgePath: uniqueTextList(
            knowledgePath,
            40
        ),
        questionCount: questionFingerprints.size,
        scope: "conversation"
    };
}


function getConversationQuestionHistory(
    session = getCurrent()
) {
    if (!session) {
        return [];
    }

    const candidates = collectConversationQuestionCandidates(
        session
    );

    return candidates.map(
        (candidate, order) => {
            const message = session.messages[
                candidate.index
            ];

            const teaching = normalizeTeaching(
                candidate.role === "ai"
                    ? message?.generatedTeaching
                    : message?.questionTeaching
            );

            return {
                ...candidate,
                order: order + 1,
                teaching,
                category: (
                    teaching?.category
                    && teaching.category !== "待识别"
                )
                    ? teaching.category
                    : "暂未识别",
                knowledgePoints: uniqueTextList(
                    teaching?.knowledge_points || [],
                    5
                )
            };
        }
    );
}

function getKnowledgeHistoryItemByMessageIndex(
    messageIndex,
    session = getCurrent()
) {
    const target = Number(messageIndex);

    if (!Number.isInteger(target)) {
        return null;
    }

    return getConversationQuestionHistory(
        session
    ).find(
        item => item.index === target
    ) || null;
}

function knowledgeContextFromHistoryItem(item) {
    if (!item) {
        return null;
    }

    const teaching = normalizeTeaching(
        item.teaching
    );

    if (!teaching) {
        return {
            category: item.category || "",
            categories: (
                item.category
                && item.category !== "暂未识别"
                    ? [item.category]
                    : []
            ),
            focusPoints: [],
            knowledgePoints: item.knowledgePoints || [],
            prerequisitePoints: [],
            knowledgePath: item.knowledgePoints || [],
            questionCount: 1,
            scope: "history",
            historyOrder: item.order,
            historyText: item.text
        };
    }

    return {
        category: teaching.category || "",
        categories: (
            teaching.category
            && teaching.category !== "待识别"
                ? [teaching.category]
                : []
        ),
        focusPoints: teaching.focus_points || [],
        knowledgePoints: teaching.knowledge_points || [],
        prerequisitePoints: teaching.prerequisite_points || [],
        knowledgePath: teaching.knowledge_path || [],
        questionCount: 1,
        scope: "history",
        historyOrder: item.order,
        historyText: item.text
    };
}

function knowledgeHistorySourceLabel(item) {
    if (!item) {
        return "题目";
    }

    if (item.role === "ai") {
        return "AI 出题";
    }

    if (item.source === "ocr") {
        return "图片识题";
    }

    return "手动输入";
}

function knowledgeHistoryPreview(text, limit = 78) {
    const value = String(text || "")
        .replace(/\s+/g, " ")
        .trim();

    if (value.length <= limit) {
        return value;
    }

    return value.slice(0, limit) + "…";
}



function getActiveKnowledgeContext() {
    if (
        knowledgeGraphScope === "history"
        && knowledgeGraphHistoryMessageIndex !== null
    ) {
        const item = getKnowledgeHistoryItemByMessageIndex(
            knowledgeGraphHistoryMessageIndex
        );

        const context = knowledgeContextFromHistoryItem(
            item
        );

        if (context) {
            return context;
        }
    }

    if (knowledgeGraphScope === "conversation") {
        return getConversationKnowledgeContext();
    }

    const current = getCurrentKnowledgeContext();

    return {
        ...current,
        categories: (
            current.category
                ? [current.category]
                : []
        ),
        questionCount: 1,
        scope: "current"
    };
}


function fillKnowledgeGraphCategoryOptions() {
    const select = document.getElementById(
        "knowledgeGraphCategory"
    );

    if (!select || !knowledgeGraphData) return;

    const baseCategories = getKnowledgeGraphCategories();

    const categories = (
        knowledgeGraphScope === "conversation"
            ? ["全部", ...baseCategories]
            : baseCategories
    );

    if (
        !knowledgeGraphFilter
        || !categories.includes(knowledgeGraphFilter)
    ) {
        knowledgeGraphFilter = (
            knowledgeGraphScope === "conversation"
                ? "全部"
                : (baseCategories[0] || "")
        );
    }

    select.innerHTML = "";

    for (const value of categories) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === knowledgeGraphFilter;
        select.appendChild(option);
    }
}


function findKnowledgeGraphNodeById(nodeId) {
    if (
        !knowledgeGraphData
        || !Array.isArray(knowledgeGraphData.nodes)
    ) {
        return null;
    }

    return knowledgeGraphData.nodes.find(
        node => node.id === nodeId
    ) || null;
}

function findKnowledgeGraphNodeByName(name) {
    if (
        !knowledgeGraphData
        || !Array.isArray(knowledgeGraphData.nodes)
    ) {
        return null;
    }

    return knowledgeGraphData.nodes.find(
        node => node.name === name
    ) || null;
}

function ensureKnowledgeGraphSelection(visibleNodes, context) {
    const ids = new Set(
        (Array.isArray(visibleNodes) ? visibleNodes : [])
            .map(node => node.id)
    );

    if (
        knowledgeGraphSelectedNodeId
        && ids.has(knowledgeGraphSelectedNodeId)
    ) {
        return;
    }

    const preferredNames = [
        ...(context?.focusPoints || []),
        ...(context?.knowledgePath || []),
        ...(context?.knowledgePoints || []),
        ...(context?.prerequisitePoints || [])
    ];

    for (const name of preferredNames) {
        const node = (visibleNodes || []).find(
            item => item.name === name
        );

        if (node) {
            knowledgeGraphSelectedNodeId = node.id;
            return;
        }
    }

    knowledgeGraphSelectedNodeId = visibleNodes?.[0]?.id || "";
}

function clampMobileGraphScale(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 1;
    return Math.max(0.35, Math.min(3, number));
}

function installMobileGraphInteraction(viewport, surface, stage, zoomLabel) {
    if (!viewport || !surface || !stage) return;

    const baseWidth = Math.max(1, Number(stage.dataset.baseWidth) || stage.scrollWidth || 1);
    const baseHeight = Math.max(1, Number(stage.dataset.baseHeight) || stage.scrollHeight || 1);
    const modal = document.getElementById("knowledgeGraphModal");
    const pointers = new Map();
    let fullscreenPan = null;
    let pinch = null;
    let suppressClickUntil = 0;

    const currentScale = () => (
        clampMobileGraphScale(viewport._kgScale || 1)
    );

    const updateLabel = scale => {
        if (zoomLabel) {
            zoomLabel.textContent = `${Math.round(scale * 100)}%`;
        }
    };

    const applyScale = (nextScale, anchor = null) => {
        const oldScale = currentScale();
        const scale = clampMobileGraphScale(nextScale);

        let contentX = null;
        let contentY = null;
        if (anchor) {
            contentX = (viewport.scrollLeft + anchor.x) / oldScale;
            contentY = (viewport.scrollTop + anchor.y) / oldScale;
        }

        viewport._kgScale = scale;
        surface.style.width = `${Math.ceil(baseWidth * scale)}px`;
        surface.style.height = `${Math.ceil(baseHeight * scale)}px`;
        stage.style.transform = `scale(${scale})`;
        updateLabel(scale);

        if (anchor && contentX !== null && contentY !== null) {
            viewport.scrollLeft = Math.max(0, contentX * scale - anchor.x);
            viewport.scrollTop = Math.max(0, contentY * scale - anchor.y);
        }

        return scale;
    };

    const fitGraph = () => {
        const availableWidth = Math.max(1, viewport.clientWidth - 24);
        const availableHeight = Math.max(1, viewport.clientHeight - 24);
        const scale = clampMobileGraphScale(
            Math.min(1, availableWidth / baseWidth, availableHeight / baseHeight)
        );
        applyScale(scale);
        requestAnimationFrame(() => {
            viewport.scrollLeft = Math.max(0, (surface.scrollWidth - viewport.clientWidth) / 2);
            viewport.scrollTop = Math.max(0, (surface.scrollHeight - viewport.clientHeight) / 2);
        });
    };

    viewport._kgSetScale = applyScale;
    viewport._kgFit = fitGraph;
    viewport._kgReset = () => {
        applyScale(1);
        viewport.scrollTop = 0;
    };

    applyScale(1);

    const viewportPoint = event => {
        const rect = viewport.getBoundingClientRect();
        return {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top
        };
    };

    const pointerDistance = (a, b) => Math.hypot(
        a.clientX - b.clientX,
        a.clientY - b.clientY
    );

    const pointerCenter = (a, b) => {
        const rect = viewport.getBoundingClientRect();
        return {
            x: (a.clientX + b.clientX) / 2 - rect.left,
            y: (a.clientY + b.clientY) / 2 - rect.top
        };
    };

    viewport.addEventListener("pointerdown", event => {
        if (event.pointerType === "mouse" && event.button !== 0) return;

        const fullscreen = Boolean(modal?.classList.contains("graph-fullscreen-view"));

        // 普通预览完全交给浏览器原生滚动：横向滚图、纵向滚页面。
        // 不再在 pointermove 中抢手势，Fennec/Android 上会明显顺滑很多。
        if (!fullscreen) return;

        pointers.set(event.pointerId, event);

        if (fullscreen) {
            try { viewport.setPointerCapture(event.pointerId); } catch (_error) {}

            if (pointers.size >= 2) {
                const [a, b] = [...pointers.values()].slice(0, 2);
                const center = pointerCenter(a, b);
                const scale = currentScale();
                pinch = {
                    distance: Math.max(1, pointerDistance(a, b)),
                    scale,
                    contentX: (viewport.scrollLeft + center.x) / scale,
                    contentY: (viewport.scrollTop + center.y) / scale
                };
                fullscreenPan = null;
                event.preventDefault();
                return;
            }

            fullscreenPan = {
                pointerId: event.pointerId,
                x: event.clientX,
                y: event.clientY,
                left: viewport.scrollLeft,
                top: viewport.scrollTop,
                moved: false
            };
            return;
        }

    }, { passive: false });

    viewport.addEventListener("pointermove", event => {
        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, event);

        const fullscreen = Boolean(modal?.classList.contains("graph-fullscreen-view"));

        if (fullscreen && pointers.size >= 2) {
            const [a, b] = [...pointers.values()].slice(0, 2);
            if (!pinch) {
                const center = pointerCenter(a, b);
                const scale = currentScale();
                pinch = {
                    distance: Math.max(1, pointerDistance(a, b)),
                    scale,
                    contentX: (viewport.scrollLeft + center.x) / scale,
                    contentY: (viewport.scrollTop + center.y) / scale
                };
            }

            const center = pointerCenter(a, b);
            const scale = clampMobileGraphScale(
                pinch.scale * pointerDistance(a, b) / pinch.distance
            );
            applyScale(scale);
            viewport.scrollLeft = Math.max(0, pinch.contentX * scale - center.x);
            viewport.scrollTop = Math.max(0, pinch.contentY * scale - center.y);
            suppressClickUntil = performance.now() + 300;
            event.preventDefault();
            return;
        }

        if (fullscreen && fullscreenPan?.pointerId === event.pointerId) {
            const dx = event.clientX - fullscreenPan.x;
            const dy = event.clientY - fullscreenPan.y;
            if (Math.abs(dx) + Math.abs(dy) > 4) {
                fullscreenPan.moved = true;
                suppressClickUntil = performance.now() + 300;
            }
            viewport.scrollLeft = fullscreenPan.left - dx;
            viewport.scrollTop = fullscreenPan.top - dy;
            event.preventDefault();
            return;
        }

    }, { passive: false });

    const finishPointer = event => {
        pointers.delete(event.pointerId);

        if (fullscreenPan?.pointerId === event.pointerId) {
            fullscreenPan = null;
        }

        if (pointers.size < 2) {
            pinch = null;
        }

        if (
            modal?.classList.contains("graph-fullscreen-view")
            && pointers.size === 1
        ) {
            const remaining = [...pointers.values()][0];
            fullscreenPan = {
                pointerId: remaining.pointerId,
                x: remaining.clientX,
                y: remaining.clientY,
                left: viewport.scrollLeft,
                top: viewport.scrollTop,
                moved: false
            };
        }
    };

    viewport.addEventListener("pointerup", finishPointer, { passive: true });
    viewport.addEventListener("pointercancel", finishPointer, { passive: true });

    viewport.addEventListener("click", event => {
        if (performance.now() < suppressClickUntil) {
            event.preventDefault();
            event.stopPropagation();
        }
    }, true);

    // 桌面调试/触控板也能 Ctrl+滚轮缩放完整图谱。
    viewport.addEventListener("wheel", event => {
        if (!modal?.classList.contains("graph-fullscreen-view") || !event.ctrlKey) {
            return;
        }
        const point = viewportPoint(event);
        const factor = event.deltaY < 0 ? 1.12 : 0.89;
        applyScale(currentScale() * factor, point);
        event.preventDefault();
    }, { passive: false });
}

function setKnowledgeGraphFullscreenView(enabled) {
    const modal = document.getElementById("knowledgeGraphModal");
    if (!modal) return;

    const next = Boolean(enabled);
    modal.classList.toggle("graph-fullscreen-view", next);

    const button = modal.querySelector(".kg-mobile-expand");
    if (button) {
        button.textContent = next ? "退出完整查看" : "完整查看";
        button.setAttribute(
            "aria-label",
            next ? "退出知识图谱完整查看" : "完整查看知识图谱"
        );
    }

    requestAnimationFrame(() => {
        const viewport = modal.querySelector(".kg-mobile-viewport");
        if (!viewport) return;

        if (next) {
            // 完整查看默认先把整张图放进屏幕；随后可双指缩放、单指拖动，
            // 或用底部 +/- / 适应按钮调整。
            viewport._kgFit?.();
        } else {
            // 回到普通预览时恢复 100%，预览只负责横向拖图，纵向手势交给页面。
            viewport._kgReset?.();
        }
    });
}

function toggleKnowledgeGraphFullscreenView() {
    const modal = document.getElementById("knowledgeGraphModal");
    if (!modal) return;
    setKnowledgeGraphFullscreenView(
        !modal.classList.contains("graph-fullscreen-view")
    );
}

function openKnowledgeGraph() {
    const modal = document.getElementById(
        "knowledgeGraphModal"
    );

    if (!modal) return;

    modal.classList.remove("hidden");
    setKnowledgeGraphFullscreenView(false);
    renderKnowledgeGraphLoading(
        "知识图谱加载中…"
    );

    ensureKnowledgeGraphData()
        .then(async () => {
            knowledgeGraphScope = "current";
            knowledgeGraphHistoryMessageIndex = null;
            knowledgeGraphSideMode = "detail";

            await refreshConversationKnowledgeIndex(
                getCurrent()
            );

            const context = getCurrentKnowledgeContext();
            const categories = getKnowledgeGraphCategories();

            if (
                context.category
                && categories.includes(context.category)
            ) {
                knowledgeGraphFilter = context.category;
                knowledgeGraphViewMode = "focus";
            } else if (
                !knowledgeGraphFilter
                || !categories.includes(knowledgeGraphFilter)
            ) {
                knowledgeGraphFilter = categories[0] || "";
                knowledgeGraphViewMode = "full";
            }

            fillKnowledgeGraphCategoryOptions();
            updateKnowledgeGraphScopeButton();
            updateKnowledgeGraphModeButton();
            renderKnowledgeGraph();
        })
        .catch(() => {
            renderKnowledgeGraphLoading(
                "知识图谱暂时加载失败，请稍后重试。"
            );
        });
}

function closeKnowledgeGraph() {
    const modal = document.getElementById(
        "knowledgeGraphModal"
    );

    if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("graph-fullscreen-view");
    }

    knowledgeGraphSideMode = "detail";
}

function renderKnowledgeGraphLoading(message) {
    const summary = document.getElementById(
        "knowledgeGraphSummary"
    );
    const canvas = document.getElementById(
        "knowledgeGraphCanvas"
    );
    const detailTitle = document.getElementById(
        "knowledgeGraphDetailTitle"
    );
    const detail = document.getElementById(
        "knowledgeGraphDetail"
    );

    if (summary) {
        summary.textContent = (
            "这里可以查看当前题目，也可以汇总本对话前面做过的题目。"
        );
    }

    if (canvas) {
        canvas.innerHTML = `<div class="kg-empty">${message}</div>`;
    }

    if (detailTitle) {
        detailTitle.textContent = "节点详情";
    }

    if (detail) {
        detail.textContent = (
            "点击左侧节点后，这里会显示相关知识和你的学习记录。"
        );
    }
}

function setKnowledgeGraphFilter(value) {
    const next = String(value || "").trim();

    if (!next) return;

    knowledgeGraphFilter = next;

    const context = getActiveKnowledgeContext();

    // 当前题目模式下切换别的模块，默认展开完整模块。
    // 本对话模式允许继续在某个模块内查看本对话涉及的知识。
    if (
        knowledgeGraphScope === "current"
        && next !== context.category
    ) {
        knowledgeGraphViewMode = "full";
    }

    updateKnowledgeGraphModeButton();
    renderKnowledgeGraph();
}

function updateKnowledgeGraphScopeButton() {
    const button = document.getElementById(
        "knowledgeGraphScopeBtn"
    );
    const legend = document.getElementById(
        "knowledgeGraphLegendRelated"
    );

    if (button) {
        if (knowledgeGraphScope === "conversation") {
            button.textContent = "只看当前题目";
            button.title = "切回当前最后一道题";
        } else if (knowledgeGraphScope === "history") {
            button.textContent = "回到当前题目";
            button.title = "退出历史题查看，回到当前最后一道题";
        } else {
            button.textContent = "查看本对话题目";
            button.title = "把本对话前面做过的题目一起汇总到图谱";
        }
    }

    if (legend) {
        if (knowledgeGraphScope === "conversation") {
            legend.textContent = "本对话相关";
        } else if (knowledgeGraphScope === "history") {
            legend.textContent = "历史题相关";
        } else {
            legend.textContent = "本题相关";
        }
    }
}


async function toggleKnowledgeGraphScope() {
    if (!knowledgeGraphData) return;

    const button = document.getElementById(
        "knowledgeGraphScopeBtn"
    );

    if (knowledgeGraphScope === "current") {
        if (button) {
            button.disabled = true;
            button.textContent = "正在整理本对话…";
        }

        await refreshConversationKnowledgeIndex(
            getCurrent()
        );

        knowledgeGraphScope = "conversation";
        knowledgeGraphHistoryMessageIndex = null;
        knowledgeGraphFilter = "全部";
        knowledgeGraphViewMode = "focus";
    } else {
        knowledgeGraphScope = "current";
        knowledgeGraphHistoryMessageIndex = null;

        const context = getCurrentKnowledgeContext();
        const categories = getKnowledgeGraphCategories();

        if (
            context.category
            && categories.includes(context.category)
        ) {
            knowledgeGraphFilter = context.category;
        }

        knowledgeGraphViewMode = "focus";
    }

    knowledgeGraphSelectedNodeId = "";

    fillKnowledgeGraphCategoryOptions();
    updateKnowledgeGraphScopeButton();
    updateKnowledgeGraphModeButton();
    renderKnowledgeGraph();

    if (button) {
        button.disabled = false;
    }
}



function focusKnowledgeGraphOnHistoryQuestion(
    messageIndex
) {
    const item = getKnowledgeHistoryItemByMessageIndex(
        messageIndex
    );

    if (!item) {
        window.alert(
            "这道历史题暂时无法定位，请重新整理历史记录。"
        );
        return;
    }

    knowledgeGraphScope = "history";
    knowledgeGraphHistoryMessageIndex = item.index;
    knowledgeGraphViewMode = "focus";
    knowledgeGraphSelectedNodeId = "";
    knowledgeGraphSideMode = "history";

    const category = item.teaching?.category || "";

    if (
        category
        && category !== "待识别"
        && getKnowledgeGraphCategories().includes(category)
    ) {
        knowledgeGraphFilter = category;
    }

    fillKnowledgeGraphCategoryOptions();
    updateKnowledgeGraphScopeButton();
    updateKnowledgeGraphModeButton();
    renderKnowledgeGraph();
}

function locateKnowledgeHistoryMessage(
    messageIndex
) {
    const targetIndex = Number(messageIndex);

    if (!Number.isInteger(targetIndex)) {
        return;
    }

    closeKnowledgeGraph();

    const chat = document.getElementById("chat");

    if (!chat) return;

    const findAndScroll = () => {
        const bubble = chat.querySelector(
            `[data-message-index="${targetIndex}"]`
        );

        if (!bubble) {
            return false;
        }

        bubble.scrollIntoView({
            behavior: "smooth",
            block: "center"
        });

        bubble.classList.add(
            "history-locate-flash"
        );

        setTimeout(() => {
            bubble.classList.remove(
                "history-locate-flash"
            );
        }, 1600);

        return true;
    };

    if (!findAndScroll()) {
        renderChat();

        setTimeout(() => {
            findAndScroll();
        }, 0);
    }
}

async function refreshKnowledgeHistoryPanel() {
    const session = getCurrent();

    if (!session) return;

    const button = document.querySelector(
        ".kg-history-refresh"
    );

    if (button) {
        button.disabled = true;
        button.textContent = "整理中…";
    }

    await refreshConversationKnowledgeIndex(
        session
    );

    if (
        knowledgeGraphScope === "history"
        && knowledgeGraphHistoryMessageIndex !== null
    ) {
        const stillExists = getKnowledgeHistoryItemByMessageIndex(
            knowledgeGraphHistoryMessageIndex
        );

        if (!stillExists) {
            knowledgeGraphScope = "current";
            knowledgeGraphHistoryMessageIndex = null;
        }
    }

    renderKnowledgeGraph();

    if (knowledgeGraphSideMode === "history") {
        renderKnowledgeGraphHistory();
    }
}


function updateKnowledgeGraphModeButton() {
    const button = document.getElementById(
        "knowledgeGraphFocusBtn"
    );

    if (!button) return;

    if (knowledgeGraphViewMode === "focus") {
        if (knowledgeGraphScope === "conversation") {
            button.textContent = "查看完整范围";
            button.title = "展开当前筛选范围的全部知识点";
        } else if (knowledgeGraphScope === "history") {
            button.textContent = "查看完整模块";
            button.title = "展开这道历史题所在模块的全部知识点";
        } else {
            button.textContent = "查看完整模块";
            button.title = "展开当前模块的全部知识点";
        }
    } else {
        if (knowledgeGraphScope === "conversation") {
            button.textContent = "聚焦本对话";
            button.title = "只显示本对话题目涉及的知识点";
        } else if (knowledgeGraphScope === "history") {
            button.textContent = "聚焦这道历史题";
            button.title = "只显示这道历史题直接相关的知识点";
        } else {
            button.textContent = "聚焦当前题目";
            button.title = "只显示与当前题目直接相关的知识点";
        }
    }
}


function focusKnowledgeGraphOnCurrent() {
    if (!knowledgeGraphData) return;

    if (knowledgeGraphScope === "conversation") {
        knowledgeGraphViewMode = (
            knowledgeGraphViewMode === "focus"
                ? "full"
                : "focus"
        );

        updateKnowledgeGraphModeButton();
        renderKnowledgeGraph();
        return;
    }

    const context = getActiveKnowledgeContext();
    const categories = getKnowledgeGraphCategories();

    if (knowledgeGraphViewMode === "focus") {
        knowledgeGraphViewMode = "full";
        updateKnowledgeGraphModeButton();
        renderKnowledgeGraph();
        return;
    }

    if (
        context.category
        && categories.includes(context.category)
    ) {
        knowledgeGraphFilter = context.category;
    }

    const currentNodeName = (
        context.knowledgePoints[0]
        || context.prerequisitePoints[0]
        || ""
    );

    if (currentNodeName) {
        const node = findKnowledgeGraphNodeByName(
            currentNodeName
        );

        if (node) {
            knowledgeGraphSelectedNodeId = node.id;
        }
    }

    knowledgeGraphViewMode = "focus";
    fillKnowledgeGraphCategoryOptions();
    updateKnowledgeGraphModeButton();
    renderKnowledgeGraph();
}



function knowledgeGraphNodeState(nodeName, context) {
    if (
        context?.focusPoints?.includes(nodeName)
        || context?.knowledgePoints?.includes(nodeName)
    ) {
        return {
            key: "current",
            label: (
                knowledgeGraphScope === "conversation"
                    ? "本对话相关"
                    : (
                        knowledgeGraphScope === "history"
                            ? "历史题相关"
                            : "本题相关"
                    )
            ),
            fill: "#5b21b6",
            stroke: "#c4b5fd",
            text: "#ffffff",
            badge: (
                knowledgeGraphScope === "history"
                    ? "历史题"
                    : "本题"
            )
        };
    }

    return {
        key: "neutral",
        label: "",
        fill: "#111827",
        stroke: "#475569",
        text: "#ffffff",
        badge: ""
    };
}


function splitKnowledgeGraphLabel(text, maxChars = 7) {
    const value = String(text || "").trim();

    if (!value) return [""];

    const lines = [];

    for (let index = 0; index < value.length; index += maxChars) {
        lines.push(
            value.slice(index, index + maxChars)
        );
    }

    return lines.slice(0, 2);
}

function createSvgElement(tag, attrs = {}) {
    const element = document.createElementNS(
        "http://www.w3.org/2000/svg",
        tag
    );

    for (const [key, value] of Object.entries(attrs)) {
        if (
            value !== undefined
            && value !== null
        ) {
            element.setAttribute(
                key,
                String(value)
            );
        }
    }

    return element;
}

function knowledgeGraphFocusedNodes(category, context) {
    const categoryNodes = knowledgeGraphVisibleNodes(
        category
    );

    if (!categoryNodes.length) {
        return [];
    }

    const byName = new Map(
        categoryNodes.map(node => [node.name, node])
    );

    const currentNames = uniqueTextList([
        ...(context?.focusPoints || []),
        ...(context?.knowledgePoints || []),
        ...(context?.prerequisitePoints || []),
        ...(context?.knowledgePath || [])
    ], 10)
        .filter(name => byName.has(name));

    if (!currentNames.length) {
        return categoryNodes;
    }

    const included = new Set(currentNames);

    // 所有当前相关节点补一层直接前置。
    for (const name of currentNames) {
        const node = byName.get(name);

        for (const prerequisite of node?.prerequisites || []) {
            if (byName.has(prerequisite)) {
                included.add(prerequisite);
            }
        }
    }

    // 当前“本题难点”再补一层直接后续，帮助学生知道掌握后会接到哪里。
    const focusNames = (
        context?.focusPoints?.length
            ? context.focusPoints
            : context?.knowledgePoints?.slice(0, 1) || []
    );

    for (const focusName of focusNames) {
        if (!byName.has(focusName)) continue;

        for (const node of categoryNodes) {
            if (node.prerequisites.includes(focusName)) {
                included.add(node.name);
            }
        }
    }

    return categoryNodes.filter(
        node => included.has(node.name)
    );
}

function knowledgeGraphVisibleNodes(category) {
    if (!knowledgeGraphData) return [];

    const allNodes = knowledgeGraphData.nodes;

    if (!category || category === "全部") {
        return allNodes.slice();
    }

    return allNodes.filter(
        node => node.category === category
    );
}

function computeKnowledgeGraphLevels(nodes) {
    const byName = new Map(
        nodes.map(node => [node.name, node])
    );
    const memo = new Map();
    const visiting = new Set();

    function depth(node) {
        if (memo.has(node.id)) {
            return memo.get(node.id);
        }

        if (visiting.has(node.id)) {
            return 0;
        }

        visiting.add(node.id);

        let value = 0;

        for (const prerequisite of node.prerequisites) {
            const previous = byName.get(prerequisite);

            if (previous) {
                value = Math.max(
                    value,
                    depth(previous) + 1
                );
            }
        }

        visiting.delete(node.id);
        memo.set(node.id, value);

        return value;
    }

    for (const node of nodes) {
        depth(node);
    }

    return memo;
}

function renderMobileKnowledgeGraphSection(container, nodes, title, description, context) {
    const section = document.createElement("div");
    section.className = "kg-section kg-mobile-section";

    const heading = document.createElement("div");
    heading.className = "kg-section-title";
    heading.textContent = title;
    section.appendChild(heading);

    if (description) {
        const desc = document.createElement("div");
        desc.className = "kg-section-desc";
        desc.textContent = description;
        section.appendChild(desc);
    }

    const expandButton = document.createElement("button");
    expandButton.type = "button";
    expandButton.className = "kg-mobile-expand";
    const graphModal = document.getElementById("knowledgeGraphModal");
    const isExpanded = graphModal?.classList.contains("graph-fullscreen-view");
    expandButton.textContent = isExpanded ? "退出完整查看" : "完整查看";
    expandButton.setAttribute(
        "aria-label",
        isExpanded ? "退出知识图谱完整查看" : "完整查看知识图谱"
    );
    expandButton.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        toggleKnowledgeGraphFullscreenView();
    });
    section.appendChild(expandButton);

    const zoomControls = document.createElement("div");
    zoomControls.className = "kg-mobile-zoom-controls";

    const zoomOut = document.createElement("button");
    zoomOut.type = "button";
    zoomOut.className = "kg-mobile-zoom-btn";
    zoomOut.textContent = "−";
    zoomOut.setAttribute("aria-label", "缩小图谱");

    const zoomLabel = document.createElement("span");
    zoomLabel.className = "kg-mobile-zoom-label";
    zoomLabel.textContent = "100%";

    const zoomIn = document.createElement("button");
    zoomIn.type = "button";
    zoomIn.className = "kg-mobile-zoom-btn";
    zoomIn.textContent = "+";
    zoomIn.setAttribute("aria-label", "放大图谱");

    const zoomFit = document.createElement("button");
    zoomFit.type = "button";
    zoomFit.className = "kg-mobile-zoom-fit";
    zoomFit.textContent = "适应";
    zoomFit.setAttribute("aria-label", "适应屏幕显示完整图谱");

    zoomControls.append(zoomOut, zoomLabel, zoomIn, zoomFit);
    section.appendChild(zoomControls);

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "kg-empty";
        empty.textContent = "这个分类下暂时没有可显示的节点。";
        section.appendChild(empty);
        container.appendChild(section);
        return;
    }

    const levels = computeKnowledgeGraphLevels(nodes);
    const orderedNodes = nodes.slice();
    const orderMap = new Map(
        orderedNodes.map((node, index) => [node.id, index])
    );
    const columns = new Map();

    for (const node of orderedNodes) {
        const level = levels.get(node.id) || 0;
        if (!columns.has(level)) columns.set(level, []);
        columns.get(level).push(node);
    }

    const columnKeys = [...columns.keys()].sort((a, b) => a - b);
    for (const key of columnKeys) {
        columns.get(key).sort(
            (a, b) => orderMap.get(a.id) - orderMap.get(b.id)
        );
    }

    // 手机端节点使用普通 HTML，SVG 只负责画线。
    // 这样避开部分安卓 WebView/浏览器 SVG <text> 不显示的问题。
    const viewportWidth = Math.max(
        280,
        (container.clientWidth || window.innerWidth || 360) - 36
    );
    const columnCount = Math.max(columnKeys.length, 1);
    const marginX = 12;
    const marginY = 14;
    const gapX = columnCount <= 2 ? 24 : 16;
    const gapY = 18;
    const fittedNodeWidth = Math.floor(
        (viewportWidth - marginX * 2 - gapX * Math.max(columnCount - 1, 0))
        / Math.min(columnCount, 3)
    );
    const nodeWidth = columnCount <= 3
        ? Math.max(92, Math.min(128, fittedNodeWidth))
        : 108;
    const nodeHeight = 64;
    const maxRows = Math.max(
        ...columnKeys.map(key => columns.get(key).length),
        1
    );
    const stageWidth = Math.max(
        viewportWidth,
        marginX * 2
        + columnCount * nodeWidth
        + Math.max(columnCount - 1, 0) * gapX
    );
    const stageHeight = (
        marginY * 2
        + maxRows * nodeHeight
        + Math.max(maxRows - 1, 0) * gapY
    );

    const viewport = document.createElement("div");
    viewport.className = "kg-mobile-viewport";

    const zoomSurface = document.createElement("div");
    zoomSurface.className = "kg-mobile-zoom-surface";
    zoomSurface.style.width = `${stageWidth}px`;
    zoomSurface.style.height = `${stageHeight}px`;

    const stage = document.createElement("div");
    stage.className = "kg-mobile-stage";
    stage.dataset.baseWidth = String(stageWidth);
    stage.dataset.baseHeight = String(stageHeight);
    stage.style.width = `${stageWidth}px`;
    stage.style.height = `${stageHeight}px`;

    const edgeSvg = createSvgElement("svg", {
        class: "kg-mobile-edge-layer",
        width: stageWidth,
        height: stageHeight,
        viewBox: `0 0 ${stageWidth} ${stageHeight}`,
        "aria-hidden": "true"
    });
    stage.appendChild(edgeSvg);

    const positions = new Map();
    for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
        const level = columnKeys[columnIndex];
        const group = columns.get(level);
        const x = marginX + columnIndex * (nodeWidth + gapX);
        const totalHeight = (
            group.length * nodeHeight
            + Math.max(group.length - 1, 0) * gapY
        );
        const startY = marginY + (stageHeight - marginY * 2 - totalHeight) / 2;

        for (let rowIndex = 0; rowIndex < group.length; rowIndex += 1) {
            const node = group[rowIndex];
            const y = startY + rowIndex * (nodeHeight + gapY);
            positions.set(node.id, { x, y });
        }
    }

    const byName = new Map(nodes.map(node => [node.name, node]));
    for (const node of orderedNodes) {
        const current = positions.get(node.id);
        if (!current) continue;

        for (const prerequisiteName of node.prerequisites || []) {
            const previousNode = byName.get(prerequisiteName);
            const previous = previousNode ? positions.get(previousNode.id) : null;
            if (!previous) continue;

            const x1 = previous.x + nodeWidth;
            const y1 = previous.y + nodeHeight / 2;
            const x2 = current.x;
            const y2 = current.y + nodeHeight / 2;
            const midX = (x1 + x2) / 2;

            const path = createSvgElement("path", {
                class: "kg-mobile-edge",
                d: `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`
            });
            edgeSvg.appendChild(path);
        }
    }

    for (const node of orderedNodes) {
        const position = positions.get(node.id);
        if (!position) continue;

        const state = knowledgeGraphNodeState(node.name, context);
        const button = document.createElement("button");
        button.type = "button";
        button.className = (
            "kg-mobile-node"
            + (node.id === knowledgeGraphSelectedNodeId ? " selected" : "")
        );
        button.style.left = `${position.x}px`;
        button.style.top = `${position.y}px`;
        button.style.width = `${nodeWidth}px`;
        button.style.height = `${nodeHeight}px`;
        button.style.background = state.fill;
        button.style.borderColor = state.stroke;
        button.setAttribute("aria-label", node.name);

        const name = document.createElement("span");
        name.className = "kg-mobile-node-name";
        name.textContent = node.name;
        button.appendChild(name);

        const badgeText = state.badge || node.level || "";
        if (badgeText) {
            const badge = document.createElement("span");
            badge.className = "kg-mobile-node-badge";
            badge.textContent = badgeText;
            button.appendChild(badge);
        }

        button.addEventListener("click", () => {
            selectKnowledgeGraphNode(node.id, button);
        });

        stage.appendChild(button);
    }

    zoomSurface.appendChild(stage);
    viewport.appendChild(zoomSurface);
    section.appendChild(viewport);
    container.appendChild(section);

    installMobileGraphInteraction(
        viewport,
        zoomSurface,
        stage,
        zoomLabel
    );

    zoomOut.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        const rect = viewport.getBoundingClientRect();
        viewport._kgSetScale?.(
            (viewport._kgScale || 1) / 1.2,
            { x: rect.width / 2, y: rect.height / 2 }
        );
    });

    zoomIn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        const rect = viewport.getBoundingClientRect();
        viewport._kgSetScale?.(
            (viewport._kgScale || 1) * 1.2,
            { x: rect.width / 2, y: rect.height / 2 }
        );
    });

    zoomFit.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        viewport._kgFit?.();
    });

    // 普通预览默认 100%。横向超出时可左右拖；上下滑动则由外层页面接管。
    requestAnimationFrame(() => {
        const overflow = Math.max(0, zoomSurface.scrollWidth - viewport.clientWidth);
        if (overflow > 0) viewport.scrollLeft = Math.min(overflow / 2, nodeWidth / 2);

        if (graphModal?.classList.contains("graph-fullscreen-view")) {
            viewport._kgFit?.();
        }
    });
}

function renderKnowledgeGraphSection(container, nodes, title, description, context) {
    const section = document.createElement("div");
    section.className = "kg-section";

    const heading = document.createElement("div");
    heading.className = "kg-section-title";
    heading.textContent = title;
    section.appendChild(heading);

    if (description) {
        const desc = document.createElement("div");
        desc.className = "kg-section-desc";
        desc.textContent = description;
        section.appendChild(desc);
    }

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "kg-empty";
        empty.textContent = "这个分类下暂时没有可显示的节点。";
        section.appendChild(empty);
        container.appendChild(section);
        return;
    }

    const levels = computeKnowledgeGraphLevels(nodes);
    const orderedNodes = nodes.slice();
    const orderMap = new Map(
        orderedNodes.map(
            (node, index) => [node.id, index]
        )
    );

    const columns = new Map();

    for (const node of orderedNodes) {
        const level = levels.get(node.id) || 0;
        if (!columns.has(level)) {
            columns.set(level, []);
        }
        columns.get(level).push(node);
    }

    const columnKeys = [...columns.keys()].sort((a, b) => a - b);

    for (const key of columnKeys) {
        columns.get(key).sort(
            (a, b) => (
                orderMap.get(a.id)
                - orderMap.get(b.id)
            )
        );
    }

    const mobileGraphLayout = isMobileAppShell();
    let nodeWidth = 132;
    let nodeHeight = 58;
    let horizontalGap = 74;
    let verticalGap = 26;
    let margin = 24;

    if (mobileGraphLayout) {
        const viewportWidth = Math.max(
            320,
            Math.min(Number(window.innerWidth) || 390, 760)
        );
        const columnCount = Math.max(columnKeys.length, 1);
        const usableWidth = Math.max(280, viewportWidth - 40);

        horizontalGap = columnCount <= 2 ? 26 : 18;
        margin = 12;

        const fittedWidth = Math.floor(
            (
                usableWidth
                - margin * 2
                - Math.max(columnCount - 1, 0) * horizontalGap
            ) / columnCount
        );

        // 手机优先把常见 2~3 列图谱完整放进卡片；列数再多时
        // 保持最低可读宽度，并只在图谱卡片内部横向滚动。
        nodeWidth = Math.max(88, Math.min(118, fittedWidth));
        nodeHeight = nodeWidth >= 108 ? 56 : 52;
        verticalGap = 22;
    }

    const maxRows = Math.max(
        ...columnKeys.map(
            key => columns.get(key).length
        ),
        1
    );

    const svgWidth = (
        margin * 2
        + columnKeys.length * nodeWidth
        + Math.max(columnKeys.length - 1, 0) * horizontalGap
    );

    const svgHeight = (
        margin * 2
        + maxRows * nodeHeight
        + Math.max(maxRows - 1, 0) * verticalGap
    );

    const svg = createSvgElement("svg", {
        class: "kg-svg",
        viewBox: `0 0 ${svgWidth} ${svgHeight}`,
        width: svgWidth,
        height: svgHeight,
        preserveAspectRatio: "xMinYMin meet"
    });

    const positions = new Map();

    for (let columnIndex = 0; columnIndex < columnKeys.length; columnIndex += 1) {
        const level = columnKeys[columnIndex];
        const group = columns.get(level);
        const x = margin + columnIndex * (nodeWidth + horizontalGap);
        const totalHeight = (
            group.length * nodeHeight
            + Math.max(group.length - 1, 0) * verticalGap
        );
        const startY = margin + (svgHeight - margin * 2 - totalHeight) / 2;

        for (let rowIndex = 0; rowIndex < group.length; rowIndex += 1) {
            const node = group[rowIndex];
            const y = startY + rowIndex * (nodeHeight + verticalGap);
            positions.set(node.id, { x, y });
        }
    }

    const byName = new Map(
        nodes.map(node => [node.name, node])
    );

    for (const node of orderedNodes) {
        const current = positions.get(node.id);

        if (!current) continue;

        for (const prerequisiteName of node.prerequisites) {
            const previousNode = byName.get(prerequisiteName);

            if (!previousNode) continue;

            const previous = positions.get(previousNode.id);

            if (!previous) continue;

            const x1 = previous.x + nodeWidth;
            const y1 = previous.y + nodeHeight / 2;
            const x2 = current.x;
            const y2 = current.y + nodeHeight / 2;
            const midX = (x1 + x2) / 2;

            const path = createSvgElement("path", {
                class: "kg-edge",
                d: `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`
            });

            svg.appendChild(path);
        }
    }

    for (const node of orderedNodes) {
        const position = positions.get(node.id);

        if (!position) continue;

        const state = knowledgeGraphNodeState(
            node.name,
            context
        );
        const group = createSvgElement("g", {
            class: (
                "kg-node-group"
                + (node.id === knowledgeGraphSelectedNodeId ? " selected" : "")
            ),
            transform: `translate(${position.x}, ${position.y})`
        });

        group.addEventListener(
            "click",
            () => {
                selectKnowledgeGraphNode(node.id, group);
            }
        );

        const rect = createSvgElement("rect", {
            x: 0,
            y: 0,
            width: nodeWidth,
            height: nodeHeight,
            rx: 12,
            fill: state.fill,
            stroke: state.stroke,
            "stroke-width": node.id === knowledgeGraphSelectedNodeId ? 3 : 2
        });

        group.appendChild(rect);

        const lines = splitKnowledgeGraphLabel(
            node.name
        );
        const graphIsLight = document.documentElement?.dataset?.appearanceTheme === "light"
            || document.body?.dataset?.appearanceTheme === "light";
        const text = createSvgElement("text", {
            class: "kg-node-label",
            x: nodeWidth / 2,
            y: 22,
            fill: graphIsLight ? "#0f172a" : "#f8fafc",
            "font-size": mobileGraphLayout ? 14 : 12,
            "font-weight": mobileGraphLayout ? 600 : 500,
            "text-anchor": "middle"
        });

        if (lines.length === 1) {
            const tspan = createSvgElement("tspan", {
                x: nodeWidth / 2,
                dy: 0
            });
            tspan.textContent = lines[0];
            text.appendChild(tspan);
        } else {
            lines.forEach((line, index) => {
                const tspan = createSvgElement("tspan", {
                    x: nodeWidth / 2,
                    dy: index === 0 ? 0 : 14
                });
                tspan.textContent = line;
                text.appendChild(tspan);
            });
        }

        group.appendChild(text);

        const nodeBadge = state.badge || node.level;

        if (nodeBadge) {
            const badge = createSvgElement("text", {
                class: "kg-node-badge",
                x: nodeWidth / 2,
                y: nodeHeight - 10,
                fill: graphIsLight ? "#475569" : "#cbd5e1",
                "font-size": mobileGraphLayout ? 11 : 10,
                "text-anchor": "middle"
            });
            badge.textContent = nodeBadge;
            group.appendChild(badge);
        }

        svg.appendChild(group);
    }

    section.appendChild(svg);
    container.appendChild(section);
}

function renderKnowledgeGraphSummary(context) {
    const summary = document.getElementById(
        "knowledgeGraphSummary"
    );

    if (!summary) return;

    summary.innerHTML = "";

    const addItem = (
        label,
        value,
        className = ""
    ) => {
        if (!value) return;

        const item = document.createElement("div");
        item.className = [
            "graph-summary-item",
            className
        ]
            .filter(Boolean)
            .join(" ");

        const labelNode = document.createElement("span");
        labelNode.className = "graph-summary-label";
        labelNode.textContent = label;

        const valueNode = document.createElement("span");
        valueNode.className = "graph-summary-value";
        valueNode.textContent = value;

        item.appendChild(labelNode);
        item.appendChild(valueNode);
        summary.appendChild(item);
    };

    if (knowledgeGraphScope === "conversation") {
        addItem(
            "查看范围",
            context.questionCount > 0
                ? `本对话 · ${context.questionCount} 道题`
                : "本对话"
        );

        if (context.categories?.length) {
            addItem(
                "涉及模块",
                context.categories.join("、")
            );
        }
    } else if (knowledgeGraphScope === "history") {
        addItem(
            "查看范围",
            `历史第 ${context.historyOrder || "?"} 题`
        );

        addItem(
            "所属模块",
            context.category || "暂未识别"
        );
    } else {
        addItem(
            "当前模块",
            context.category || knowledgeGraphFilter || "暂未识别"
        );
    }

    const related = uniqueTextList(
        context.knowledgePoints || [],
        12
    );

    if (related.length) {
        addItem(
            knowledgeGraphScope === "conversation"
                ? "本对话相关"
                : (
                    knowledgeGraphScope === "history"
                        ? "历史题相关"
                        : "本题相关"
                ),
            related.join("、")
        );
    } else {
        addItem(
            "当前视图",
            knowledgeGraphViewMode === "focus"
                ? (
                    knowledgeGraphScope === "conversation"
                        ? "本对话暂时没有可汇总的知识点"
                        : "与当前题目直接相关的知识"
                )
                : "完整范围"
        );
    }
}



function setKnowledgeGraphSideMode(mode) {
    knowledgeGraphSideMode = (
        mode === "history"
            ? "history"
            : "detail"
    );

    renderKnowledgeGraphSide();
}

function updateKnowledgeGraphSideTabs() {
    const detailTab = document.getElementById(
        "knowledgeGraphDetailTab"
    );
    const historyTab = document.getElementById(
        "knowledgeGraphHistoryTab"
    );

    if (detailTab) {
        detailTab.classList.toggle(
            "active",
            knowledgeGraphSideMode === "detail"
        );
    }

    if (historyTab) {
        historyTab.classList.toggle(
            "active",
            knowledgeGraphSideMode === "history"
        );

        const count = getConversationQuestionHistory(
            getCurrent()
        ).length;

        historyTab.textContent = count
            ? `题目历史 (${count})`
            : "题目历史";
    }
}

function renderKnowledgeGraphHistory() {
    const list = document.getElementById(
        "knowledgeGraphHistory"
    );

    if (!list) return;

    const history = getConversationQuestionHistory(
        getCurrent()
    );

    list.innerHTML = "";

    const head = document.createElement("div");
    head.className = "kg-history-head";

    const text = document.createElement("div");
    text.className = "kg-history-head-text";
    text.textContent = history.length
        ? `本对话识别到 ${history.length} 道题。`
        : "本对话暂时没有识别到题目。";

    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "kg-history-refresh";
    refresh.textContent = "重新整理";
    refresh.title = "重新从聊天记录逐题识别，不调用大模型";

    refresh.addEventListener(
        "click",
        refreshKnowledgeHistoryPanel
    );

    head.appendChild(text);
    head.appendChild(refresh);
    list.appendChild(head);

    if (!history.length) {
        const empty = document.createElement("div");
        empty.className = "graph-detail-empty";
        empty.textContent = (
            "如果刚刚才发送题目，可以等 AI 回复完成后再点“重新整理”。"
        );
        list.appendChild(empty);
        return;
    }

    for (const item of history) {
        const card = document.createElement("div");
        card.className = "kg-history-item";

        if (
            knowledgeGraphScope === "history"
            && item.index === knowledgeGraphHistoryMessageIndex
        ) {
            card.classList.add("active");
        }

        const top = document.createElement("div");
        top.className = "kg-history-item-top";

        const number = document.createElement("div");
        number.className = "kg-history-number";
        number.textContent = `第 ${item.order} 题`;

        const source = document.createElement("span");
        source.className = "kg-history-source";
        source.textContent = knowledgeHistorySourceLabel(
            item
        );

        top.appendChild(number);
        top.appendChild(source);

        const category = document.createElement("div");
        category.className = "kg-history-category";
        category.textContent = item.category;

        const preview = document.createElement("div");
        preview.className = "kg-history-preview ai-content";
        preview.innerHTML = markdownToHtml(
            prepareAiDisplayText(
                item.text
            )
        );

        const points = document.createElement("div");
        points.className = "kg-history-points";
        points.textContent = item.knowledgePoints.length
            ? item.knowledgePoints.join("、")
            : "知识点暂未识别";

        const actions = document.createElement("div");
        actions.className = "kg-history-actions";

        const graphButton = document.createElement("button");
        graphButton.type = "button";
        graphButton.textContent = "查看图谱";
        graphButton.addEventListener(
            "click",
            () => {
                focusKnowledgeGraphOnHistoryQuestion(
                    item.index
                );
            }
        );

        const locateButton = document.createElement("button");
        locateButton.type = "button";
        locateButton.className = "secondary";
        locateButton.textContent = "定位原题";
        locateButton.addEventListener(
            "click",
            () => {
                locateKnowledgeHistoryMessage(
                    item.index
                );
            }
        );

        actions.appendChild(graphButton);
        actions.appendChild(locateButton);

        card.appendChild(top);
        card.appendChild(category);
        card.appendChild(preview);
        card.appendChild(points);
        card.appendChild(actions);
        list.appendChild(card);
    }

    renderMath(list);
}

function selectKnowledgeGraphNode(nodeId, sourceElement = null) {
    knowledgeGraphSelectedNodeId = nodeId;
    knowledgeGraphSideMode = "detail";

    const canvas = document.getElementById("knowledgeGraphCanvas");
    if (canvas) {
        canvas.querySelectorAll(
            ".kg-mobile-node.selected, .kg-node-group.selected"
        ).forEach(element => element.classList.remove("selected"));
    }

    const selected = sourceElement?.closest?.(
        ".kg-mobile-node, .kg-node-group"
    );
    selected?.classList.add("selected");

    // 只刷新右侧/下方详情，不重建全部节点和连线。
    // 手机上点击节点时不会再出现整张图谱闪一下、卡一下。
    renderKnowledgeGraphSide();
}


function renderKnowledgeGraphSide() {
    updateKnowledgeGraphSideTabs();

    const detailWrap = document.getElementById(
        "knowledgeGraphDetailWrap"
    );
    const historyWrap = document.getElementById(
        "knowledgeGraphHistoryWrap"
    );

    if (detailWrap) {
        detailWrap.classList.toggle(
            "hidden",
            knowledgeGraphSideMode !== "detail"
        );
    }

    if (historyWrap) {
        historyWrap.classList.toggle(
            "hidden",
            knowledgeGraphSideMode !== "history"
        );
    }

    if (knowledgeGraphSideMode === "history") {
        renderKnowledgeGraphHistory();
    } else {
        renderKnowledgeGraphDetail();
    }
}


function renderKnowledgeGraphDetail() {
    const title = document.getElementById(
        "knowledgeGraphDetailTitle"
    );
    const detail = document.getElementById(
        "knowledgeGraphDetail"
    );

    if (!title || !detail || !knowledgeGraphData) return;

    const node = findKnowledgeGraphNodeById(
        knowledgeGraphSelectedNodeId
    );

    if (!node) {
        title.textContent = "节点详情";
        detail.innerHTML = (
            '<div class="graph-detail-empty">点击左侧知识点查看关系。</div>'
        );
        return;
    }

    const context = getActiveKnowledgeContext();
    const state = knowledgeGraphNodeState(
        node.name,
        context
    );

    const nextNodes = knowledgeGraphData.nodes
        .filter(item => item.prerequisites.includes(node.name))
        .map(item => item.name);

    title.textContent = node.name;
    detail.innerHTML = "";

    const subline = document.createElement("div");
    subline.className = "graph-detail-subline";

    const category = document.createElement("span");
    category.textContent = node.category;
    subline.appendChild(category);

    if (node.level) {
        const level = document.createElement("span");
        level.className = "graph-level-pill";
        level.textContent = node.level;
        subline.appendChild(level);
    }

    if (state.label) {
        const pill = document.createElement("span");
        pill.className = `graph-status-pill ${state.key}`;
        pill.textContent = state.label;
        subline.appendChild(pill);
    }

    detail.appendChild(subline);

    const addDetailField = (labelText, values, emptyText) => {
        const field = document.createElement("div");
        field.className = "graph-detail-field";

        const label = document.createElement("div");
        label.className = "graph-detail-field-label";
        label.textContent = labelText;

        const value = document.createElement("div");
        value.className = "graph-detail-field-value";
        value.textContent = values.length
            ? values.join("、")
            : emptyText;

        field.appendChild(label);
        field.appendChild(value);
        detail.appendChild(field);
    };

    addDetailField(
        "建议前置知识",
        node.prerequisites,
        "暂无建议前置"
    );

    addDetailField(
        "直接后续知识",
        nextNodes,
        "暂无直接后续"
    );

    if (node.note) {
        addDetailField(
            "说明",
            [node.note],
            ""
        );
    }
}



function renderKnowledgeGraph() {
    const modal = document.getElementById(
        "knowledgeGraphModal"
    );

    if (!modal || modal.classList.contains("hidden")) {
        return;
    }

    if (!knowledgeGraphData) {
        renderKnowledgeGraphLoading(
            "知识图谱加载中…"
        );
        return;
    }

    fillKnowledgeGraphCategoryOptions();
    updateKnowledgeGraphScopeButton();
    updateKnowledgeGraphModeButton();

    const context = getActiveKnowledgeContext();
    const canvas = document.getElementById(
        "knowledgeGraphCanvas"
    );

    if (!canvas) return;

    renderKnowledgeGraphSummary(context);
    knowledgeGraphPreparedPngPromise = null;
    knowledgeGraphPreparedPngKey = "";
    canvas.innerHTML = "";

    if (!knowledgeGraphData.nodes.length) {
        canvas.innerHTML = (
            '<div class="kg-empty">知识图谱目前还是空的。</div>'
        );
        renderKnowledgeGraphSide();
        return;
    }

    const fullNodes = knowledgeGraphVisibleNodes(
        knowledgeGraphFilter
    );

    const visibleNodes = (
        knowledgeGraphViewMode === "focus"
            ? knowledgeGraphFocusedNodes(
                knowledgeGraphFilter,
                context
            )
            : fullNodes
    );

    ensureKnowledgeGraphSelection(
        visibleNodes,
        context
    );

    const description = (
        knowledgeGraphViewMode === "focus"
            ? (
                knowledgeGraphScope === "conversation"
                    ? (
                        visibleNodes.length
                            ? `已汇总本对话前面题目，只显示 ${visibleNodes.length} 个相关知识点。`
                            : "本对话暂时没有可汇总的知识点。"
                    )
                    : (
                        knowledgeGraphScope === "history"
                            ? (
                                visibleNodes.length
                                    ? `正在查看历史第 ${context.historyOrder || "?"} 题，只显示 ${visibleNodes.length} 个相关知识点。`
                                    : "这道历史题暂时没有识别到可显示的知识点。"
                            )
                            : (
                                visibleNodes.length < fullNodes.length
                                    ? `已聚焦当前题目，只显示 ${visibleNodes.length} 个直接相关知识点。`
                                    : "当前没有可进一步收缩的题目上下文，显示当前模块。"
                            )
                    )
            )
            : (
                knowledgeGraphFilter === "全部"
                    ? `完整知识图谱，共 ${fullNodes.length} 个知识点。`
                    : `完整模块，共 ${fullNodes.length} 个知识点。`
            )
    );

    const mobileGraph = window.matchMedia?.("(max-width: 760px)")?.matches;

    if (mobileGraph) {
        renderMobileKnowledgeGraphSection(
            canvas,
            visibleNodes,
            knowledgeGraphFilter || "知识图谱",
            description,
            context
        );
    } else {
        renderKnowledgeGraphSection(
            canvas,
            visibleNodes,
            knowledgeGraphFilter || "知识图谱",
            description,
            context
        );
    }

    renderKnowledgeGraphSide();
    scheduleKnowledgeGraphPngPreparation();
}


// -----------------------------
// 右侧会话信息
// -----------------------------
function renderInfo() {
    const info = document.getElementById("info");
    if (!info) return;

    const session = getCurrent();

    if (!session) {
        info.innerText = "暂无对话";
        return;
    }

    const lines = [
        `当前对话：${session.name}`,
        `消息数：${session.messages.length}`
    ];

    const teaching = getEffectiveSessionTeaching(session);

    if (teaching) {
        lines.push(
            "",
            `学习内容：${getFriendlyCategory(teaching.category)}`
        );

        if (teaching.focus_points.length) {
            lines.push(
                `本题难点：${teaching.focus_points.join("、")}`
            );
        }

        if (teaching.knowledge_path.length >= 2) {
            lines.push(
                `知识脉络：${teaching.knowledge_path.join(" → ")}`
            );
        }
    }

    info.innerText = lines.join("\n");
}


// -----------------------------
// 移动端应用壳：对话抽屉 / 学习工具抽屉
// -----------------------------
function isMobileAppShell() {
    return window.matchMedia?.("(max-width: 1100px)")?.matches ?? false;
}

let mobileDrawerGestureFrame = 0;
let mobileDrawerGesturePending = null;
let mobileDrawerGestureElements = null;

function getMobileDrawerGestureElements() {
    const cached = mobileDrawerGestureElements;
    if (
        cached
        && cached.center?.isConnected
        && cached.left?.isConnected
        && cached.right?.isConnected
    ) {
        return cached;
    }

    mobileDrawerGestureElements = {
        left:document.querySelector(".left"),
        right:document.querySelector(".right"),
        backdrop:document.getElementById("mobileShellBackdrop"),
        center:document.querySelector(".center")
    };
    return mobileDrawerGestureElements;
}

function resetMobileDrawerGestureStyles() {
    if (mobileDrawerGestureFrame) {
        cancelAnimationFrame(mobileDrawerGestureFrame);
        mobileDrawerGestureFrame = 0;
    }
    mobileDrawerGesturePending = null;

    const { left, right, backdrop, center } = getMobileDrawerGestureElements();

    [left, right, backdrop, center].forEach(element => {
        if (!(element instanceof HTMLElement)) return;
        element.style.removeProperty("transform");
        element.style.removeProperty("opacity");
        element.style.removeProperty("pointer-events");
    });

    document.body.classList.remove("mobile-drawer-dragging");
}

function closeMobileShellDrawers() {
    document.body.classList.remove("mobile-left-open", "mobile-tools-open");
    resetMobileDrawerGestureStyles();
}

function openMobileShellDrawer(kind) {
    if (!isMobileAppShell()) return;

    resetMobileDrawerGestureStyles();
    document.body.classList.remove("mobile-left-open", "mobile-tools-open");
    document.body.classList.add(
        kind === "tools" ? "mobile-tools-open" : "mobile-left-open"
    );
}

function paintMobileDrawerDragProgress(kind, progress) {
    const p = Math.max(0, Math.min(1, Number(progress) || 0));
    const { left, right, backdrop, center } = getMobileDrawerGestureElements();

    document.body.classList.add("mobile-drawer-dragging");

    if (kind === "left" && left instanceof HTMLElement) {
        left.style.transform = `translate3d(${-104 + 104 * p}%,0,0)`;
    }
    if (kind === "tools" && right instanceof HTMLElement) {
        right.style.transform = `translate3d(${104 - 104 * p}%,0,0)`;
    }

    if (backdrop instanceof HTMLElement) {
        backdrop.style.opacity = String(p);
        backdrop.style.pointerEvents = "none";
    }

    if (center instanceof HTMLElement) {
        const direction = kind === "left" ? 1 : -1;
        const offset = direction * p * 8;
        center.style.transform = `translate3d(${offset}px,0,0)`;
    }
}

function setMobileDrawerDragProgress(kind, progress) {
    // touchmove 可能高于屏幕刷新率；每帧只提交一次 transform，避免主线程被
    // 连续 style 写入拖住。
    mobileDrawerGesturePending = { kind, progress };
    if (mobileDrawerGestureFrame) return;

    mobileDrawerGestureFrame = requestAnimationFrame(() => {
        mobileDrawerGestureFrame = 0;
        const pending = mobileDrawerGesturePending;
        mobileDrawerGesturePending = null;
        if (!pending) return;
        paintMobileDrawerDragProgress(pending.kind, pending.progress);
    });
}

function settleMobileDrawerGesture(kind, shouldOpen) {
    const body = document.body;

    body.classList.remove("mobile-drawer-dragging");
    body.classList.remove("mobile-left-open", "mobile-tools-open");
    if (shouldOpen) {
        body.classList.add(kind === "tools" ? "mobile-tools-open" : "mobile-left-open");
    }

    // 保留手指结束瞬间的 inline transform 一帧，再交还给 CSS transition，
    // 这样不会在 touchend 时突然跳一下。
    requestAnimationFrame(() => {
        requestAnimationFrame(resetMobileDrawerGestureStyles);
    });
}

function refreshMobileConversationTitle() {
    const title = document.getElementById("mobileConversationTitle");
    if (!title) return;

    const session = getCurrent();
    const name = typeof session?.name === "string" ? session.name.trim() : "";
    title.textContent = name || "离散数学助手";
}


function mobileSwipeBlockedTarget(target) {
    if (!(target instanceof Element)) return false;

    return Boolean(target.closest([
        "input",
        "textarea",
        "select",
        "button",
        "a",
        "[contenteditable='true']",
        "mjx-container",
        ".knowledge-graph-canvas",
        ".kg-history-preview",
        ".wrong-question",
        ".wrong-feedback-body",
        ".wrong-answer-body",
        ".wrong-solution-body",
        ".wrong-analysis-body"
    ].join(",")));
}

function mobileOverlayIsOpen() {
    return Boolean(
        document.querySelector(".modal:not(.hidden)")
        || document.querySelector("dialog[open]")
    );
}

function installMobileSwipeNavigation() {
    const center = document.querySelector(".center");
    const left = document.querySelector(".left");
    const right = document.querySelector(".right");
    const backdrop = document.getElementById("mobileShellBackdrop");
    if (!center) return;

    const startSlop = 9;
    const openThreshold = 0.30;
    const closeThreshold = 0.72;
    const fastVelocity = 0.48;

    let drag = null;

    const drawerWidth = kind => {
        const element = kind === "left" ? left : right;
        return Math.max(240, element?.getBoundingClientRect?.().width || window.innerWidth * 0.88);
    };

    const beginDrag = (event, source) => {
        if (!isMobileAppShell() || event.touches.length !== 1) {
            drag = null;
            return;
        }

        if (mobileOverlayIsOpen() || mobileSwipeBlockedTarget(event.target)) {
            drag = null;
            return;
        }

        const touch = event.touches[0];
        const leftOpen = document.body.classList.contains("mobile-left-open");
        const toolsOpen = document.body.classList.contains("mobile-tools-open");

        let kind = null;
        let opening = false;

        if (source === "left" || (source === "backdrop" && leftOpen)) {
            if (!leftOpen) return;
            kind = "left";
        } else if (source === "tools" || (source === "backdrop" && toolsOpen)) {
            if (!toolsOpen) return;
            kind = "tools";
        } else if (source === "center") {
            if (leftOpen || toolsOpen) return;
            opening = true;
        } else {
            return;
        }

        drag = {
            source,
            kind,
            opening,
            locked:false,
            cancelled:false,
            startX:touch.clientX,
            startY:touch.clientY,
            lastX:touch.clientX,
            lastTime:performance.now(),
            startTime:performance.now(),
            progress:opening ? 0 : 1,
            // 已知抽屉在 touchstart 时只读一次布局；主界面打开方向在第一次
            // 明确横向手势后再读一次，之后 touchmove 不再触发布局测量。
            width:kind ? drawerWidth(kind) : 0
        };
    };

    const moveDrag = event => {
        if (!drag || drag.cancelled || event.touches.length !== 1) return;

        const touch = event.touches[0];
        const dx = touch.clientX - drag.startX;
        const dy = touch.clientY - drag.startY;
        const absX = Math.abs(dx);
        const absY = Math.abs(dy);

        if (!drag.locked) {
            if (absX < startSlop && absY < startSlop) return;

            // 纵向意图优先交给页面滚动，不抢手势。
            if (absY > absX * 1.08) {
                drag.cancelled = true;
                drag = null;
                return;
            }

            if (absX <= absY * 1.08) return;

            if (drag.opening) {
                drag.kind = dx >= 0 ? "left" : "tools";
                drag.width = drawerWidth(drag.kind);
            } else {
                // 左抽屉只能向左收回，右抽屉只能向右收回。
                const closingDirection = drag.kind === "left" ? dx < 0 : dx > 0;
                if (!closingDirection) {
                    drag.cancelled = true;
                    drag = null;
                    return;
                }
            }

            drag.locked = true;
        }

        if (!drag.kind) return;
        event.preventDefault();

        const width = Math.max(1, drag.width || drawerWidth(drag.kind));
        let progress;

        if (drag.opening) {
            progress = Math.abs(dx) / width;
        } else if (drag.kind === "left") {
            progress = 1 + dx / width;
        } else {
            progress = 1 - dx / width;
        }

        drag.progress = Math.max(0, Math.min(1, progress));
        drag.lastX = touch.clientX;
        drag.lastTime = performance.now();
        setMobileDrawerDragProgress(drag.kind, drag.progress);
    };

    const endDrag = event => {
        if (!drag) return;

        const current = drag;
        drag = null;

        if (!current.locked || current.cancelled || !current.kind) {
            resetMobileDrawerGestureStyles();
            return;
        }

        const touch = event.changedTouches?.[0];
        const endX = touch?.clientX ?? current.lastX;
        const now = performance.now();
        const dt = Math.max(1, now - current.lastTime);
        const velocity = (endX - current.lastX) / dt;

        let shouldOpen;
        if (current.opening) {
            const fastOpen = current.kind === "left"
                ? velocity > fastVelocity
                : velocity < -fastVelocity;
            shouldOpen = current.progress >= openThreshold || fastOpen;
        } else {
            const fastClose = current.kind === "left"
                ? velocity < -fastVelocity
                : velocity > fastVelocity;
            shouldOpen = current.progress > closeThreshold && !fastClose;
        }

        settleMobileDrawerGesture(current.kind, shouldOpen);
    };

    const cancelDrag = () => {
        if (!drag) return;
        const current = drag;
        drag = null;
        if (current.kind) {
            settleMobileDrawerGesture(current.kind, !current.opening);
        } else {
            resetMobileDrawerGestureStyles();
        }
    };

    const bindInteractive = (element, source) => {
        if (!element) return;
        element.addEventListener("touchstart", event => beginDrag(event, source), { passive:true });
        element.addEventListener("touchmove", moveDrag, { passive:false });
        element.addEventListener("touchend", endDrag, { passive:true });
        element.addEventListener("touchcancel", cancelDrag, { passive:true });
    };

    bindInteractive(center, "center");
    bindInteractive(left, "left");
    bindInteractive(right, "tools");
    bindInteractive(backdrop, "backdrop");

    installMobileOverlaySwipeBack();
}

function getTopMobileGesturePage() {
    if (!isMobileAppShell()) return null;

    const graphModal = document.getElementById("knowledgeGraphModal");
    if (
        graphModal
        && !graphModal.classList.contains("hidden")
        && graphModal.classList.contains("graph-fullscreen-view")
    ) {
        return {
            overlay:graphModal,
            surface:graphModal.querySelector(".graph-modal-card") || graphModal,
            close:() => setKnowledgeGraphFullscreenView(false)
        };
    }

    const dialog = document.querySelector("dialog[open]");
    if (dialog instanceof HTMLDialogElement) {
        return {
            overlay:dialog,
            surface:dialog,
            close:() => dialog.close()
        };
    }

    const closers = new Map([
        ["appearanceBackgroundViewer", closeAppearanceBackgroundViewer],
        ["wrongSafeModal", closeWrongSafePreview],
        ["wrongQuestionPickerModal", closeWrongQuestionPicker],
        ["wrongEditModal", closeWrongEdit],
        ["wrongBookModal", closeWrongBook],
        ["learningReviewModal", closeLearningReview],
        ["accountModal", closeAccountModal],
        ["knowledgeGraphModal", closeKnowledgeGraph],
        ["appearanceModal", closeAppearance]
    ]);

    const visible = [...document.querySelectorAll(".modal:not(.hidden)")].reverse();
    for (const modal of visible) {
        const close = closers.get(modal.id);
        if (typeof close !== "function") continue;
        return {
            overlay:modal,
            surface:modal.querySelector(".modal-card") || modal,
            close
        };
    }

    return null;
}

function installMobileOverlaySwipeBack() {
    const edgeWidth = 34;
    const startSlop = 8;
    const completeDistance = 92;
    const fastVelocity = 0.52;
    let swipe = null;
    let swipeFrame = 0;
    let swipeVisual = null;

    const cancelSwipeFrame = () => {
        if (swipeFrame) {
            cancelAnimationFrame(swipeFrame);
            swipeFrame = 0;
        }
        swipeVisual = null;
    };

    const scheduleSwipeVisual = (surface, distance) => {
        swipeVisual = { surface, distance };
        if (swipeFrame) return;

        swipeFrame = requestAnimationFrame(() => {
            swipeFrame = 0;
            const visual = swipeVisual;
            swipeVisual = null;
            if (!(visual?.surface instanceof HTMLElement)) return;
            visual.surface.style.transition = "none";
            visual.surface.style.transform = `translate3d(${visual.distance}px,0,0)`;
        });
    };

    document.addEventListener("touchstart", event => {
        if (!isMobileAppShell() || event.touches.length !== 1) {
            swipe = null;
            return;
        }

        const page = getTopMobileGesturePage();
        if (!page) {
            swipe = null;
            return;
        }

        const touch = event.touches[0];
        if (touch.clientX > edgeWidth) {
            swipe = null;
            return;
        }

        // 如果刚打开页面就立刻滑回，先停掉进入动画，避免两个 transform 打架。
        try {
            page.surface.getAnimations?.().forEach(animation => animation.cancel());
        } catch (_error) {}

        swipe = {
            page,
            startX:touch.clientX,
            startY:touch.clientY,
            lastX:touch.clientX,
            lastTime:performance.now(),
            locked:false,
            progress:0,
            width:Math.max(1, page.surface.getBoundingClientRect().width || window.innerWidth)
        };
    }, { passive:true, capture:true });

    document.addEventListener("touchmove", event => {
        if (!swipe || event.touches.length !== 1) return;

        const touch = event.touches[0];
        const dx = touch.clientX - swipe.startX;
        const dy = touch.clientY - swipe.startY;

        if (!swipe.locked) {
            if (Math.abs(dx) < startSlop && Math.abs(dy) < startSlop) return;
            if (dx <= 0 || Math.abs(dy) > Math.abs(dx) * 0.95) {
                swipe = null;
                return;
            }
            swipe.locked = true;
        }

        event.preventDefault();

        const width = swipe.width;
        const distance = Math.max(0, Math.min(width, dx));
        const progress = Math.max(0, Math.min(1, distance / width));
        swipe.progress = progress;
        swipe.lastX = touch.clientX;
        swipe.lastTime = performance.now();

        // 只做合成层 transform，不在拖动过程中改整屏背景色/透明度，
        // 避免 Fennec 上每帧触发大面积重绘。
        scheduleSwipeVisual(swipe.page.surface, distance);
    }, { passive:false, capture:true });

    const finish = event => {
        if (!swipe) return;
        const current = swipe;
        swipe = null;

        const surface = current.page.surface;
        const overlay = current.page.overlay;

        if (!(surface instanceof HTMLElement) || !current.locked) {
            cancelSwipeFrame();
            if (surface instanceof HTMLElement) {
                surface.style.removeProperty("transition");
                surface.style.removeProperty("transform");
            }
            return;
        }

        const touch = event.changedTouches?.[0];
        const endX = touch?.clientX ?? current.lastX;
        const dt = Math.max(1, performance.now() - current.lastTime);
        const velocity = (endX - current.lastX) / dt;
        cancelSwipeFrame();
        const width = current.width;
        const distance = current.progress * width;
        surface.style.transition = "none";
        surface.style.transform = `translate3d(${distance}px,0,0)`;
        const shouldClose = distance >= completeDistance
            || current.progress >= 0.24
            || velocity > fastVelocity;

        surface.style.removeProperty("transition");

        if (shouldClose) {
            const animation = surface.animate(
                [
                    { transform:`translate3d(${distance}px,0,0)` },
                    { transform:"translate3d(100%,0,0)" }
                ],
                {
                    duration:Math.max(110, 190 - Math.min(70, velocity * 45)),
                    easing:"cubic-bezier(.22,1,.36,1)",
                    fill:"forwards"
                }
            );
            animation.finished.catch(() => {}).then(() => {
                surface.style.removeProperty("transform");
                current.page.close();
            });
        } else {
            const animation = surface.animate(
                [
                    { transform:`translate3d(${distance}px,0,0)` },
                    { transform:"translate3d(0,0,0)" }
                ],
                {
                    duration:180,
                    easing:"cubic-bezier(.22,1,.36,1)"
                }
            );
            animation.finished.catch(() => {}).then(() => {
                surface.style.removeProperty("transform");
            });
        }
    };

    document.addEventListener("touchend", finish, { passive:true, capture:true });
    document.addEventListener("touchcancel", finish, { passive:true, capture:true });
}

function animateMobileConversationSwitch() {
    if (!isMobileAppShell()) return;
    const chat = document.getElementById("chat");
    if (!(chat instanceof HTMLElement) || typeof chat.animate !== "function") return;

    chat.animate(
        [
            { opacity:0.72, transform:"translate3d(0,7px,0)" },
            { opacity:1, transform:"translate3d(0,0,0)" }
        ],
        {
            duration:210,
            easing:"cubic-bezier(.22,1,.36,1)"
        }
    );
}

function initMobileAppShell() {
    const navBtn = document.getElementById("mobileNavBtn");
    const toolsBtn = document.getElementById("mobileToolsBtn");
    const navClose = document.getElementById("mobileNavClose");
    const toolsClose = document.getElementById("mobileToolsClose");
    const backdrop = document.getElementById("mobileShellBackdrop");
    const sessionsBox = document.getElementById("sessions");
    const newChatBtn = document.querySelector(".left > .btn:not(.appearance-entry)");

    navBtn?.addEventListener("click", () => openMobileShellDrawer("left"));
    toolsBtn?.addEventListener("click", () => openMobileShellDrawer("tools"));
    navClose?.addEventListener("click", closeMobileShellDrawers);
    toolsClose?.addEventListener("click", closeMobileShellDrawers);
    backdrop?.addEventListener("click", closeMobileShellDrawers);

    sessionsBox?.addEventListener("click", event => {
        if (event.target.closest(".session span")) {
            closeMobileShellDrawers();
        }
    });

    newChatBtn?.addEventListener("click", () => {
        window.setTimeout(closeMobileShellDrawers, 0);
    });

    [
        "appearanceBtn",
        "markWrongBtn",
        "wrongBookBtn",
        "knowledgeGraphBtn",
        "learningReviewBtn"
    ].forEach(id => {
        document.getElementById(id)?.addEventListener("click", () => {
            window.setTimeout(closeMobileShellDrawers, 0);
        });
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            closeMobileShellDrawers();
        }
    });

    const media = window.matchMedia?.("(max-width: 1100px)");
    media?.addEventListener?.("change", event => {
        if (!event.matches) {
            closeMobileShellDrawers();
        }
    });

    refreshMobileConversationTitle();
}


// -----------------------------
// 移动端可视视口：修复软键盘遮住输入框
// -----------------------------
let mobileViewportSyncRaf = 0;

function syncMobileVisualViewport() {
    if (mobileViewportSyncRaf) {
        cancelAnimationFrame(mobileViewportSyncRaf);
    }

    mobileViewportSyncRaf = requestAnimationFrame(() => {
        mobileViewportSyncRaf = 0;

        const root = document.documentElement;
        if (!root) return;

        if (!isMobileAppShell()) {
            root.style.removeProperty("--app-visible-height");
            document.body?.classList.remove("mobile-keyboard-open");
            return;
        }

        const viewport = window.visualViewport;
        const visibleHeight = Math.max(
            320,
            Math.round(viewport?.height || window.innerHeight || 0)
        );
        root.style.setProperty(
            "--app-visible-height",
            `${visibleHeight}px`
        );

        const layoutHeight = Math.max(
            visibleHeight,
            Math.round(window.innerHeight || visibleHeight)
        );
        const viewportTop = Math.max(
            0,
            Math.round(viewport?.offsetTop || 0)
        );
        const keyboardInset = Math.max(
            0,
            layoutHeight - visibleHeight - viewportTop
        );
        const keyboardOpen = keyboardInset > 110;

        document.body?.classList.toggle(
            "mobile-keyboard-open",
            keyboardOpen
        );

        if (keyboardOpen) {
            const text = document.getElementById("text");
            const chat = document.getElementById("chat");
            if (text && document.activeElement === text && chat) {
                chat.scrollTop = chat.scrollHeight;
            }
        }
    });
}

function installMobileVisualViewportFix() {
    syncMobileVisualViewport();

    window.addEventListener(
        "resize",
        syncMobileVisualViewport,
        { passive:true }
    );
    window.addEventListener(
        "orientationchange",
        () => window.setTimeout(syncMobileVisualViewport, 80),
        { passive:true }
    );

    const viewport = window.visualViewport;
    viewport?.addEventListener(
        "resize",
        syncMobileVisualViewport,
        { passive:true }
    );
    viewport?.addEventListener(
        "scroll",
        syncMobileVisualViewport,
        { passive:true }
    );

    const text = document.getElementById("text");
    if (text) {
        text.addEventListener("focus", () => {
            // 安卓键盘动画并非一次完成；几个轻量同步点覆盖首轮打开键盘。
            syncMobileVisualViewport();
            [60, 160, 320].forEach(delay => {
                window.setTimeout(syncMobileVisualViewport, delay);
            });
        });
        text.addEventListener("blur", () => {
            [0, 120].forEach(delay => {
                window.setTimeout(syncMobileVisualViewport, delay);
            });
        });
    }
}

// -----------------------------
// Android / 浏览器“返回”键：
// 历史保护必须由真实用户交互建立，避免 Firefox/Fennec 把启动阶段脚本
// 创建的 history 条目当作“未交互历史”跳过。
// -----------------------------
const MOBILE_HISTORY_ROOT = "__dm_tutor_mobile_root_v3";
const MOBILE_HISTORY_STEP = "__dm_tutor_mobile_guard_step_v3";
let mobileBackGuardInstalled = false;
let mobileBackExitUntil = 0;
let mobileBackAllowExit = false;
let mobileKeyboardFocusGraceUntil = 0;
let mobileBackUserActivated = false;

function mobileHistoryStateObject() {
    const value = history.state;
    return value && typeof value === "object" && !Array.isArray(value)
        ? { ...value }
        : {};
}

function mobileHistoryGuardStep() {
    const step = Number(history.state?.[MOBILE_HISTORY_STEP]);
    return Number.isFinite(step) ? step : 0;
}

function ensureMobileBackHistoryStack(fromUserGesture = false) {
    if (!isMobileAppShell() || mobileBackAllowExit) return;

    try {
        let state = mobileHistoryStateObject();
        let step = mobileHistoryGuardStep();

        // 页面加载阶段只给“当前真实页面”做 root 标记，不新增历史项。
        // 新增 guard 必须等真实 pointer/touch/keydown 交互后再做。
        if (!state[MOBILE_HISTORY_ROOT] && !step) {
            const root = {
                ...state,
                [MOBILE_HISTORY_ROOT]: true,
                [MOBILE_HISTORY_STEP]: 0
            };
            history.replaceState(root, "", location.href);
            state = root;
            step = 0;
        }

        if (!fromUserGesture && !mobileBackUserActivated) {
            return;
        }

        if (fromUserGesture) {
            mobileBackUserActivated = true;
        }

        // 在同一次真实用户操作里补足两层保护。这样打开抽屉、弹窗、
        // 图谱完整查看后，Android 返回首先只会回到同一文档并触发 popstate。
        if (step < 1) {
            history.pushState(
                {
                    ...state,
                    [MOBILE_HISTORY_ROOT]: true,
                    [MOBILE_HISTORY_STEP]: 1
                },
                "",
                location.href
            );
            state = mobileHistoryStateObject();
            step = 1;
        }

        if (step < 2) {
            history.pushState(
                {
                    ...state,
                    [MOBILE_HISTORY_ROOT]: true,
                    [MOBILE_HISTORY_STEP]: 2
                },
                "",
                location.href
            );
        }
    } catch (error) {
        console.warn("移动端返回保护建立失败：", error);
    }
}

function markMobileKeyboardFocusGrace() {
    mobileKeyboardFocusGraceUntil = Date.now() + 700;
}

function mobileKeyboardLikelyActive() {
    const active = document.activeElement;
    const activeEditable = active instanceof HTMLElement && (
        active.matches("input, textarea, select")
        || active.isContentEditable
    );

    if (activeEditable) return true;
    if (Date.now() < mobileKeyboardFocusGraceUntil) return true;

    const viewport = window.visualViewport;
    if (!viewport) return false;

    const hiddenHeight = Math.max(
        0,
        window.innerHeight - viewport.height - Math.max(0, viewport.offsetTop || 0)
    );
    return hiddenHeight > 120;
}

function dismissMobileKeyboardForBack() {
    if (!mobileKeyboardLikelyActive()) return false;

    const active = document.activeElement;
    if (active instanceof HTMLElement && typeof active.blur === "function") {
        active.blur();
    }

    mobileKeyboardFocusGraceUntil = 0;
    syncMobileVisualViewport();
    window.setTimeout(syncMobileVisualViewport, 80);
    window.setTimeout(syncMobileVisualViewport, 220);
    return true;
}

function closeTopMobileLayerForBack() {
    if (dismissMobileKeyboardForBack()) {
        return true;
    }

    const graphModal = document.getElementById("knowledgeGraphModal");
    if (
        graphModal
        && !graphModal.classList.contains("hidden")
        && graphModal.classList.contains("graph-fullscreen-view")
    ) {
        setKnowledgeGraphFullscreenView(false);
        return true;
    }

    const openDialog = document.querySelector("dialog[open]");
    if (openDialog && typeof openDialog.close === "function") {
        openDialog.close();
        return true;
    }

    const modalClosers = [
        ["appearanceBackgroundViewer", closeAppearanceBackgroundViewer],
        ["wrongSafeModal", closeWrongSafePreview],
        ["wrongQuestionPickerModal", closeWrongQuestionPicker],
        ["wrongEditModal", closeWrongEdit],
        ["wrongBookModal", closeWrongBook],
        ["learningReviewModal", closeLearningReview],
        ["knowledgeGraphModal", closeKnowledgeGraph],
        ["appearanceModal", closeAppearance]
    ];

    for (const [id, close] of modalClosers) {
        const modal = document.getElementById(id);
        if (modal && !modal.classList.contains("hidden")) {
            close();
            return true;
        }
    }

    if (
        document.body.classList.contains("mobile-left-open")
        || document.body.classList.contains("mobile-tools-open")
    ) {
        closeMobileShellDrawers();
        return true;
    }

    return false;
}

function installMobileBackGuard() {
    if (mobileBackGuardInstalled) return;
    mobileBackGuardInstalled = true;

    if (isMobileAppShell()) {
        // 这里只标 root，不在启动阶段 push guard。
        ensureMobileBackHistoryStack(false);
    }

    // 关键修复：在真实用户操作的同步事件里建立 history guard。
    // Fennec/Firefox Android 可能不把页面启动阶段自动塞入的 history
    // 当成可由系统 Back 正常遍历的用户导航；这里让 guard 与用户操作绑定。
    const armFromUserGesture = () => {
        if (!isMobileAppShell() || mobileBackAllowExit) return;
        ensureMobileBackHistoryStack(true);
    };

    document.addEventListener("pointerdown", armFromUserGesture, {
        capture: true,
        passive: true
    });
    document.addEventListener("touchstart", armFromUserGesture, {
        capture: true,
        passive: true
    });
    document.addEventListener("click", armFromUserGesture, {
        capture: true,
        passive: true
    });
    document.addEventListener("keydown", armFromUserGesture, {
        capture: true
    });

    document.addEventListener("focusin", event => {
        if (!(event.target instanceof Element)) return;
        if (event.target.matches("input, textarea, select, [contenteditable='true']")) {
            mobileKeyboardFocusGraceUntil = Date.now() + 60 * 60 * 1000;
            armFromUserGesture();
        }
    });
    document.addEventListener("focusout", event => {
        if (!(event.target instanceof Element)) return;
        if (event.target.matches("input, textarea, select, [contenteditable='true']")) {
            markMobileKeyboardFocusGrace();
        }
    });

    window.addEventListener("popstate", () => {
        if (!isMobileAppShell() || mobileBackAllowExit) return;

        // Back 已经先退到同页的较低 guard。先处理 UI，再决定是否补回顶层。
        // 不能一进 popstate 就 pushState，否则“第二次返回退出”会被刚补回的
        // guard 再挡一次。
        if (closeTopMobileLayerForBack()) {
            mobileBackExitUntil = 0;
            if (mobileBackUserActivated) {
                ensureMobileBackHistoryStack(true);
            }
            return;
        }

        const now = Date.now();
        if (now < mobileBackExitUntil) {
            mobileBackExitUntil = 0;
            mobileBackAllowExit = true;

            // 此时通常位于 step1；跨过剩余 guard + 本页 root，回到浏览器
            // 原来的上一页。若只剩 root，则退一层即可。
            const step = mobileHistoryGuardStep();
            const delta = -(Math.max(0, step) + 1);
            window.setTimeout(() => {
                try {
                    history.go(delta);
                } catch (_error) {
                    history.back();
                }
            }, 0);
            return;
        }

        mobileBackExitUntil = now + 1800;
        showCopyToast("再按一次返回退出");
        if (mobileBackUserActivated) {
            ensureMobileBackHistoryStack(true);
        }
    });

    // beforeunload 在现代移动浏览器里不能作为可靠的 Android Back 拦截器，
    // 因此不再依赖它。真正的保护来自“用户交互时建立的同页 history”。

    window.addEventListener("pageshow", () => {
        if (isMobileAppShell() && !mobileBackAllowExit) {
            mobileBackExitUntil = 0;
            ensureMobileBackHistoryStack(false);
            syncMobileVisualViewport();
        }
    });

    const media = window.matchMedia?.("(max-width: 1100px)");
    media?.addEventListener?.("change", event => {
        if (event.matches) {
            mobileBackAllowExit = false;
            mobileBackExitUntil = 0;
            ensureMobileBackHistoryStack(false);
            syncMobileVisualViewport();
        }
    });
}

// -----------------------------
// 全刷新
// -----------------------------
function renderAll() {
    renderSessions();
    renderChat();
    renderInfo();
    renderLearningSummary();
    renderKnowledgeGraph();
    refreshInputAvailability();
    refreshMobileConversationTitle();
}


function removeDeprecatedCopyControls() {
    [
        "infoCopyBtn",
        "learningSummaryCopyBtn",
        "learningReviewCopy",
        "knowledgeGraphSideCopyBtn",
        "wrongCopyBtn"
    ].forEach(id => {
        document.getElementById(id)?.remove();
    });
}

// -----------------------------
// 初始化
// -----------------------------
document.addEventListener(
    "DOMContentLoaded",
    () => {
        removeDeprecatedCopyControls();
        initAppearanceSystem();
        installRichSelectionCopy();
        initMobileAppShell();
        installMobileVisualViewportFix();
        // Fennec/Android 的系统返回键行为交给浏览器本身，不再污染 history。
        // 页面内返回与切换统一交给手势和显式按钮。
        installMobileSwipeNavigation();

        const input = document.getElementById("text");
        const chat = document.getElementById("chat");
        const imageBtn = document.getElementById("imageBtn");
        const imageInput = document.getElementById("imageInput");
        const markWrongBtn = document.getElementById("markWrongBtn");
        const wrongBookBtn = document.getElementById("wrongBookBtn");
        const learningReviewBtn = document.getElementById("learningReviewBtn");
        const learningReviewClose = document.getElementById("learningReviewClose");
        const learningReviewModal = document.getElementById("learningReviewModal");
        const wrongBookClose = document.getElementById("wrongBookClose");
        const wrongBookModal = document.getElementById("wrongBookModal");
        const wrongBookSearchBox = document.getElementById("wrongBookSearch");
        const wrongBookSearchClear = document.getElementById("wrongBookSearchClear");
        const wrongBookSortBox = document.getElementById("wrongBookSort");
        const wrongPdfBtn = document.getElementById("wrongPdfBtn");
        const wrongClearCompletedBtn = document.getElementById("wrongClearCompletedBtn");
        const wrongEditClose = document.getElementById("wrongEditClose");
        const wrongEditCancel = document.getElementById("wrongEditCancel");
        const wrongEditSave = document.getElementById("wrongEditSave");
        const wrongEditModal = document.getElementById("wrongEditModal");
        const wrongQuestionPickerClose = document.getElementById("wrongQuestionPickerClose");
        const wrongQuestionPickerCancel = document.getElementById("wrongQuestionPickerCancel");
        const wrongQuestionPickerConfirm = document.getElementById("wrongQuestionPickerConfirm");
        const wrongQuestionPickerModal = document.getElementById("wrongQuestionPickerModal");
        const wrongSafeClose = document.getElementById("wrongSafeClose");
        const wrongSafeCancel = document.getElementById("wrongSafeCancel");
        const wrongSafeConfirm = document.getElementById("wrongSafeConfirm");
        const wrongSafeModal = document.getElementById("wrongSafeModal");
        const knowledgeGraphBtn = document.getElementById("knowledgeGraphBtn");
        const knowledgeGraphClose = document.getElementById("knowledgeGraphClose");
        const knowledgeGraphModal = document.getElementById("knowledgeGraphModal");
        const knowledgeGraphCategory = document.getElementById("knowledgeGraphCategory");
        const knowledgeGraphScopeBtn = document.getElementById("knowledgeGraphScopeBtn");
        const knowledgeGraphFocusBtn = document.getElementById("knowledgeGraphFocusBtn");
        const knowledgeGraphCopyBtn = document.getElementById("knowledgeGraphCopyBtn");
        const knowledgeGraphDetailTab = document.getElementById("knowledgeGraphDetailTab");
        const knowledgeGraphHistoryTab = document.getElementById("knowledgeGraphHistoryTab");
        const wrongFilterButtons = document.querySelectorAll(
            "[data-wrong-filter]"
        );

        if (chat) {
            chat.addEventListener(
                "scroll",
                handleChatScrollWhileTyping,
                { passive: true }
            );

            chat.addEventListener(
                "wheel",
                handleChatWheelWhileTyping,
                { passive: true }
            );

            chat.addEventListener(
                "pointerdown",
                handleChatPointerWhileTyping,
                { passive: true }
            );

            chat.addEventListener(
                "touchstart",
                handleChatTouchWhileTyping,
                { passive: true }
            );
        }

        if (input) {
            input.addEventListener(
                "keydown",
                event => {
                    if (
                        event.key === "Enter"
                        && !event.shiftKey
                    ) {
                        event.preventDefault();
                        send();
                    }
                }
            );
        }

        if (imageBtn) {
            imageBtn.addEventListener(
                "click",
                openImagePicker
            );
        }

        const ocrCancelBtn = document.getElementById("ocrCancelBtn");
        if (ocrCancelBtn) {
            ocrCancelBtn.addEventListener(
                "click",
                cancelImageRecognition
            );
        }

        if (imageInput) {
            imageInput.addEventListener(
                "change",
                handleImageSelected
            );
        }

        if (markWrongBtn) {
            markWrongBtn.addEventListener(
                "click",
                manualMarkCurrentWrong
            );
        }

        if (wrongBookBtn) {
            wrongBookBtn.addEventListener(
                "click",
                openWrongBook
            );
        }

        if (learningReviewBtn) {
            learningReviewBtn.addEventListener(
                "click",
                openLearningReview
            );
        }

        if (learningReviewClose) {
            learningReviewClose.addEventListener(
                "click",
                closeLearningReview
            );
        }


        if (learningReviewModal) {
            learningReviewModal.addEventListener(
                "click",
                event => {
                    if (event.target === learningReviewModal) {
                        closeLearningReview();
                    }
                }
            );
        }

        if (wrongBookClose) {
            wrongBookClose.addEventListener(
                "click",
                closeWrongBook
            );
        }

        if (wrongBookModal) {
            wrongBookModal.addEventListener(
                "click",
                event => {
                    if (event.target === wrongBookModal) {
                        closeWrongBook();
                    }
                }
            );
        }

        if (wrongBookSearchBox) {
            const syncWrongBookSearchClear = () => {
                if (!wrongBookSearchClear) {
                    return;
                }

                wrongBookSearchClear.classList.toggle(
                    "hidden",
                    !wrongBookSearchBox.value
                );
            };

            wrongBookSearchBox.addEventListener(
                "input",
                event => {
                    setWrongBookSearch(event.target.value);
                    syncWrongBookSearchClear();
                }
            );

            if (wrongBookSearchClear) {
                wrongBookSearchClear.addEventListener(
                    "click",
                    () => {
                        wrongBookSearchBox.value = "";
                        setWrongBookSearch("");
                        syncWrongBookSearchClear();
                        wrongBookSearchBox.focus();
                    }
                );
            }

            syncWrongBookSearchClear();
        }

        if (wrongBookSortBox) {
            wrongBookSortBox.addEventListener(
                "change",
                event => setWrongBookSort(event.target.value)
            );
        }

        if (wrongPdfBtn) {
            wrongPdfBtn.addEventListener(
                "click",
                exportWrongBookPdf
            );
        }

        if (wrongClearCompletedBtn) {
            wrongClearCompletedBtn.addEventListener(
                "click",
                clearCompletedWrongQuestions
            );
        }

        if (wrongEditClose) {
            wrongEditClose.addEventListener(
                "click",
                closeWrongEdit
            );
        }

        if (wrongEditCancel) {
            wrongEditCancel.addEventListener(
                "click",
                closeWrongEdit
            );
        }

        if (wrongEditSave) {
            wrongEditSave.addEventListener(
                "click",
                saveWrongEdit
            );
        }

        if (wrongEditModal) {
            wrongEditModal.addEventListener(
                "click",
                event => {
                    if (event.target === wrongEditModal) {
                        closeWrongEdit();
                    }
                }
            );
        }

        if (wrongQuestionPickerClose) {
            wrongQuestionPickerClose.addEventListener(
                "click",
                closeWrongQuestionPicker
            );
        }

        if (wrongQuestionPickerCancel) {
            wrongQuestionPickerCancel.addEventListener(
                "click",
                closeWrongQuestionPicker
            );
        }

        if (wrongQuestionPickerConfirm) {
            wrongQuestionPickerConfirm.addEventListener(
                "click",
                confirmWrongQuestionPicker
            );
        }

        if (wrongQuestionPickerModal) {
            wrongQuestionPickerModal.addEventListener(
                "click",
                event => {
                    if (event.target === wrongQuestionPickerModal) {
                        closeWrongQuestionPicker();
                    }
                }
            );
        }

        if (wrongSafeClose) {
            wrongSafeClose.addEventListener(
                "click",
                closeWrongSafePreview
            );
        }

        if (wrongSafeCancel) {
            wrongSafeCancel.addEventListener(
                "click",
                closeWrongSafePreview
            );
        }

        if (wrongSafeConfirm) {
            wrongSafeConfirm.addEventListener(
                "click",
                confirmWrongSafePreview
            );
        }

        if (wrongSafeModal) {
            wrongSafeModal.addEventListener(
                "click",
                event => {
                    if (event.target === wrongSafeModal) {
                        closeWrongSafePreview();
                    }
                }
            );
        }

        if (knowledgeGraphBtn) {
            knowledgeGraphBtn.addEventListener(
                "click",
                openKnowledgeGraph
            );
        }

        if (knowledgeGraphClose) {
            knowledgeGraphClose.addEventListener(
                "click",
                closeKnowledgeGraph
            );
        }

        if (knowledgeGraphModal) {
            knowledgeGraphModal.addEventListener(
                "click",
                event => {
                    if (event.target === knowledgeGraphModal) {
                        closeKnowledgeGraph();
                    }
                }
            );
        }

        if (knowledgeGraphCategory) {
            knowledgeGraphCategory.addEventListener(
                "change",
                event => setKnowledgeGraphFilter(event.target.value)
            );
        }

        if (knowledgeGraphScopeBtn) {
            knowledgeGraphScopeBtn.addEventListener(
                "click",
                toggleKnowledgeGraphScope
            );
        }

        if (knowledgeGraphDetailTab) {
            knowledgeGraphDetailTab.addEventListener(
                "click",
                () => {
                    setKnowledgeGraphSideMode(
                        "detail"
                    );
                }
            );
        }

        if (knowledgeGraphHistoryTab) {
            knowledgeGraphHistoryTab.addEventListener(
                "click",
                () => {
                    setKnowledgeGraphSideMode(
                        "history"
                    );
                }
            );
        }

        if (knowledgeGraphFocusBtn) {
            knowledgeGraphFocusBtn.addEventListener(
                "click",
                focusKnowledgeGraphOnCurrent
            );
        }

        if (knowledgeGraphCopyBtn) {
            knowledgeGraphCopyBtn.addEventListener(
                "click",
                copyKnowledgeGraphVisual
            );
        }

        for (const button of wrongFilterButtons) {
            button.addEventListener(
                "click",
                () => {
                    setWrongBookFilter(
                        button.getAttribute("data-wrong-filter")
                    );
                }
            );
        }

        loadLearningState();

        const restored = loadState();

        if (!restored) {
            const id = makeSessionId();

            sessions.push({
                id,
                name: "新对话",
                messages: [],
                teaching: null,
                learningQuestion: null,
                retest: null
            });

            currentId = id;
            saveState();
        }

        renderAll();
        refreshInputAvailability();
        initAccountSystem();

        // 兼容旧会话：如果之前 AI 出过题但没有保存 generatedQuestion /
        // generatedTeaching，启动后自动恢复最近真实题目并补分类。
        const activeSession = getCurrent();

        if (activeSession) {
            ensureActiveQuestionAfterHistoryChange(
                activeSession
            ).then(() => {
                saveState();
                renderInfo();
                renderLearningSummary();
            });
        }
    }
);
