/**
 * 南网采购平台 - 前端交互逻辑
 */

// ======== 全局状态 ========
let currentPage = 1;
let currentPageSize = 20;
let statusTimer = null;

// ======== 初始化 ========
document.addEventListener("DOMContentLoaded", () => {
    initTimePicker();
    loadSettings().then(() => {
        setDefaultDateFilter();
        loadData();
    });
    // 启动状态轮询（始终轮询，以便检测定时任务启动）
    refreshStatus();
    startStatusPolling(POLL_SLOW);

    // 公司名搜索自动完成
    const companyInput = document.getElementById("companyFilter");
    let searchTimeout = null;
    companyInput.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchCompanies(companyInput.value), 300);
    });
    companyInput.addEventListener("focus", () => {
        if (companyInput.value) searchCompanies(companyInput.value);
    });
    document.addEventListener("click", (e) => {
        if (!e.target.closest(".autocomplete-wrapper")) {
            document.getElementById("companyList").classList.remove("show");
        }
    });

    // 关键词回车搜索
    document.getElementById("filterKeyword").addEventListener("keydown", (e) => {
        if (e.key === "Enter") loadData();
    });
});

// ======== Tab 切换 ========
function switchTab(tab) {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-content").forEach(el => {
        el.classList.toggle("active", el.id === `tab-${tab}`);
    });

    if (tab === "data") loadData();
}

// ======== 时间选择器初始化 ========
function initTimePicker() {
    const hourSelect = document.getElementById("scheduleHour");
    const minuteSelect = document.getElementById("scheduleMinute");

    for (let h = 0; h < 24; h++) {
        const opt = document.createElement("option");
        opt.value = h;
        opt.textContent = h.toString().padStart(2, "0");
        if (h === 12) opt.selected = true;
        hourSelect.appendChild(opt);
    }

    for (let m = 0; m < 60; m += 5) {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m.toString().padStart(2, "0");
        if (m === 0) opt.selected = true;
        minuteSelect.appendChild(opt);
    }
}

// ======== 设置管理 ========
async function loadSettings() {
    try {
        const resp = await fetch("/api/settings");
        const data = await resp.json();

        // 来源
        const sources = (data.scrape_sources || "bidding.csg.cn,ecsg.com.cn").split(",");
        document.getElementById("src-bidding").checked = sources.includes("bidding.csg.cn");
        document.getElementById("src-ecsg").checked = sources.includes("ecsg.com.cn");

        // 类别
        const cats = (data.categories || "工程,服务").split(",");
        document.getElementById("cat-engineering").checked = cats.includes("工程");
        document.getElementById("cat-service").checked = cats.includes("服务");
        const goodsEl = document.getElementById("cat-goods");
        if (goodsEl) goodsEl.checked = cats.includes("货物");

        // 公司
        document.getElementById("companyFilter").value = data.filter_company || "";

        // 标题关键词
        document.getElementById("titleKeywords").value = data.title_keywords || "";

        // 天数
        document.getElementById("scrapeDays").value = data.scrape_days || 3;

        // 最大页数
        document.getElementById("maxPages").value = data.max_pages || 5;

        // 定时
        document.getElementById("scheduleHour").value = data.schedule_hour || 12;
        document.getElementById("scheduleMinute").value = data.schedule_minute || 0;

        // 自动导出
        document.getElementById("autoExport").checked = data.auto_export || false;
        document.getElementById("exportDir").value = data.export_dir || "./data/exports";
    } catch (e) {
        console.error("加载设置失败:", e);
    }
}

async function saveSettings() {
    const categories = [];
    if (document.getElementById("cat-engineering").checked) categories.push("工程");
    if (document.getElementById("cat-service").checked) categories.push("服务");
    const goodsEl = document.getElementById("cat-goods");
    if (goodsEl && goodsEl.checked) categories.push("货物");

    const sources = [];
    if (document.getElementById("src-bidding").checked) sources.push("bidding.csg.cn");
    if (document.getElementById("src-ecsg").checked) sources.push("ecsg.com.cn");

    const settings = {
        categories: categories.join(","),
        scrape_sources: sources.join(","),
        filter_company: document.getElementById("companyFilter").value,
        title_keywords: document.getElementById("titleKeywords").value,
        scrape_days: parseInt(document.getElementById("scrapeDays").value),
        max_pages: parseInt(document.getElementById("maxPages").value),
        schedule_hour: parseInt(document.getElementById("scheduleHour").value),
        schedule_minute: parseInt(document.getElementById("scheduleMinute").value),
        auto_export: document.getElementById("autoExport").checked,
        export_dir: document.getElementById("exportDir").value,
    };

    try {
        const resp = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(settings),
        });
        const data = await resp.json();
        showToast(data.success ? "success" : "error", data.message || "保存失败");
    } catch (e) {
        showToast("error", "保存设置失败: " + e.message);
    }
}

// ======== 爬取控制 ========
async function startScrape() {
    const categories = [];
    if (document.getElementById("cat-engineering").checked) categories.push("工程");
    if (document.getElementById("cat-service").checked) categories.push("服务");
    const goodsEl = document.getElementById("cat-goods");
    if (goodsEl && goodsEl.checked) categories.push("货物");

    const sources = [];
    if (document.getElementById("src-bidding").checked) sources.push("bidding.csg.cn");
    if (document.getElementById("src-ecsg").checked) sources.push("ecsg.com.cn");

    const company = document.getElementById("companyFilter").value;

    if (categories.length === 0) {
        showToast("error", "请至少选择一个类别");
        return;
    }
    if (sources.length === 0) {
        showToast("error", "请至少选择一个爬取来源");
        return;
    }

    const btn = document.getElementById("btnScrapeNow");
    btn.disabled = true;
    btn.innerHTML = "⏳ 爬取中...";

    try {
        // 先保存设置
        await saveSettings();

        const resp = await fetch("/api/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ categories, company, sources }),
        });
        const data = await resp.json();

        if (data.success) {
            showToast("success", "爬取任务已启动，请关注运行状态");
            startStatusPolling();
        } else {
            showToast("error", data.message);
            btn.disabled = false;
            btn.innerHTML = "🚀 立即爬取";
        }
    } catch (e) {
        showToast("error", "启动爬取失败: " + e.message);
        btn.disabled = false;
        btn.innerHTML = "🚀 立即爬取";
    }
}

// ======== 状态轮询 ========
// 始终保持轮询（慢速 5s），爬取运行中切换为快速轮询（2s）
const POLL_FAST = 2000;  // 运行中：每 2 秒
const POLL_SLOW = 5000;  // 空闲时：每 5 秒

function startStatusPolling(interval) {
    if (statusTimer) clearInterval(statusTimer);
    statusTimer = setInterval(refreshStatus, interval || POLL_SLOW);
}

async function refreshStatus() {
    try {
        const resp = await fetch("/api/status");
        const data = await resp.json();

        const runningEl = document.getElementById("runningStatus");
        const statusDot = document.querySelector(".status-dot");
        const statusText = document.querySelector(".status-text");
        const btn = document.getElementById("btnScrapeNow");

        if (data.running) {
            runningEl.textContent = "🔄 正在爬取...";
            runningEl.style.color = "var(--accent-orange)";
            statusDot.classList.add("running");
            statusText.textContent = "爬取中";
            btn.disabled = true;
            btn.innerHTML = "⏳ 爬取中...";

            // 切换到快速轮询
            startStatusPolling(POLL_FAST);
        } else {
            runningEl.textContent = "✅ 空闲";
            runningEl.style.color = "var(--accent-green)";
            statusDot.classList.remove("running");
            statusText.textContent = "就绪";
            btn.disabled = false;
            btn.innerHTML = "🚀 立即爬取";

            // 切换回慢速轮询（保持轮询以检测定时任务启动）
            startStatusPolling(POLL_SLOW);
        }

        document.getElementById("lastRunTime").textContent = data.last_run || "从未执行";

        const resultEl = document.getElementById("lastResult");
        if (data.last_result) {
            resultEl.textContent = data.last_result.message || "-";
            resultEl.style.color = data.last_result.success ? "var(--accent-green)" : "var(--accent-red)";
        }

        const logEl = document.getElementById("progressLog");
        if (data.progress && data.progress.length > 0) {
            logEl.innerHTML = data.progress.map(line => {
                let cls = "log-line";
                if (line.includes("❌") || line.includes("失败") || line.includes("⚠")) cls += " error";
                if (line.includes("完成") || line.includes("━━━")) cls += " success";
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            }).join("");
            logEl.scrollTop = logEl.scrollHeight;
        }
    } catch (e) {
        console.error("获取状态失败:", e);
    }
}

// ======== 公司搜索 ========
async function searchCompanies(keyword) {
    const listEl = document.getElementById("companyList");

    if (!keyword || keyword.length < 1) {
        listEl.classList.remove("show");
        return;
    }

    try {
        const resp = await fetch(`/api/companies?q=${encodeURIComponent(keyword)}`);
        const companies = await resp.json();

        if (companies.length === 0) {
            listEl.classList.remove("show");
            return;
        }

        listEl.innerHTML = companies.map(name =>
            `<div class="autocomplete-item" onclick="selectCompany('${escapeHtml(name)}')">${escapeHtml(name)}</div>`
        ).join("");
        listEl.classList.add("show");
    } catch (e) {
        console.error("搜索公司失败:", e);
    }
}

function selectCompany(name) {
    document.getElementById("companyFilter").value = name;
    document.getElementById("companyList").classList.remove("show");
}

// ======== 数据查询 ========
async function loadData(page) {
    if (page) currentPage = page;

    const params = new URLSearchParams({
        page: currentPage,
        page_size: currentPageSize,
    });

    const category = document.getElementById("filterCategory").value;
    const company = document.getElementById("filterCompany")?.value || "";
    const dateFrom = _mmddToFull(document.getElementById("filterDateFrom").value);
    const dateTo = _mmddToFull(document.getElementById("filterDateTo").value);
    const keyword = document.getElementById("filterKeyword").value;
    const source = document.getElementById("filterSource")?.value || "";

    if (category) params.set("category", category);
    if (company) params.set("company", company);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (keyword) params.set("keyword", keyword);
    if (source) params.set("source", source);

    try {
        const resp = await fetch(`/api/announcements?${params}`);
        const data = await resp.json();

        renderTable(data.items, data.page, data.page_size);
        renderPagination(data.page, data.total_pages, data.total);
        document.getElementById("totalCount").textContent = `${data.total} 条`;
    } catch (e) {
        console.error("加载数据失败:", e);
    }
}

function renderTable(items, page, pageSize) {
    const tbody = document.getElementById("dataBody");

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="12" class="empty-state">暂无数据，请先执行爬取</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map((item, idx) => {
        const num = (page - 1) * pageSize + idx + 1;
        const catClass = item.category === "工程" ? "tag-engineering" :
            item.category === "货物" ? "tag-goods" : "tag-service";
        const sourceShort = (item.source || "").includes("ecsg") ? "电子交易" : "供应链";

        return `
            <tr>
                <td>${num}</td>
                <td>
                    <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener"
                       title="${escapeHtml(item.title)}">
                        ${escapeHtml(item.title)}
                    </a>
                </td>
                <td>${escapeHtml(item.announcement_type || "-")}</td>
                <td>${escapeHtml(item.tenderer || item.company || "-")}</td>
                <td title="${escapeHtml(item.bid_packages || "")}">${escapeHtml(truncate(item.bid_packages, 20) || "-")}</td>
                <td>${escapeHtml(item.estimated_amount || "-")}</td>
                <td>${escapeHtml(item.bidding_method || "-")}</td>
                <td>${escapeHtml(item.reg_end_time || "-")}</td>
                <td>${escapeHtml(item.bid_deadline || "-")}</td>
                <td><span class="tag ${catClass}">${escapeHtml(item.category || "-")}</span></td>
                <td><span class="tag tag-source">${escapeHtml(sourceShort)}</span></td>
                <td>${escapeHtml(item.publish_date || "-")}</td>
            </tr>
        `;
    }).join("");
}

function renderPagination(page, totalPages, total) {
    const el = document.getElementById("pagination");

    if (totalPages <= 1) {
        el.innerHTML = "";
        return;
    }

    let html = "";

    html += `<button class="page-btn" ${page <= 1 ? "disabled" : ""} onclick="loadData(${page - 1})">‹</button>`;

    const range = getPageRange(page, totalPages);
    if (range[0] > 1) {
        html += `<button class="page-btn" onclick="loadData(1)">1</button>`;
        if (range[0] > 2) html += `<span class="page-info">...</span>`;
    }

    for (let p = range[0]; p <= range[1]; p++) {
        html += `<button class="page-btn ${p === page ? "active" : ""}" onclick="loadData(${p})">${p}</button>`;
    }

    if (range[1] < totalPages) {
        if (range[1] < totalPages - 1) html += `<span class="page-info">...</span>`;
        html += `<button class="page-btn" onclick="loadData(${totalPages})">${totalPages}</button>`;
    }

    html += `<button class="page-btn" ${page >= totalPages ? "disabled" : ""} onclick="loadData(${page + 1})">›</button>`;
    html += `<span class="page-info">共 ${total} 条</span>`;

    el.innerHTML = html;
}

function getPageRange(current, total) {
    const delta = 2;
    let start = Math.max(1, current - delta);
    let end = Math.min(total, current + delta);

    if (end - start < delta * 2) {
        if (start === 1) end = Math.min(total, start + delta * 2);
        else start = Math.max(1, end - delta * 2);
    }

    return [start, end];
}

// ======== 导出 Excel ========
function exportExcel() {
    const params = new URLSearchParams();
    const category = document.getElementById("filterCategory").value;
    const company = document.getElementById("filterCompany")?.value || "";
    const dateFrom = _mmddToFull(document.getElementById("filterDateFrom").value);
    const dateTo = _mmddToFull(document.getElementById("filterDateTo").value);
    const keyword = document.getElementById("filterKeyword").value;
    const source = document.getElementById("filterSource")?.value || "";

    if (category) params.set("category", category);
    if (company) params.set("company", company);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (keyword) params.set("keyword", keyword);
    if (source) params.set("source", source);

    window.location.href = `/api/export?${params}`;
    showToast("success", "正在导出 Excel...");
}

// ======== Toast 消息 ========
function showToast(type, message) {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ======== 工具函数 ========
function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function truncate(str, maxLen) {
    if (!str) return "";
    return str.length > maxLen ? str.substring(0, maxLen) + "..." : str;
}

/**
 * 将 MM-DD 格式转换为 YYYY-MM-DD（使用当前年份）
 */
function _mmddToFull(val) {
    if (!val) return "";
    val = val.trim();
    // 已经是 YYYY-MM-DD 格式
    if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
    // MM-DD 格式
    if (/^\d{1,2}-\d{1,2}$/.test(val)) {
        const year = new Date().getFullYear();
        const parts = val.split("-");
        return `${year}-${parts[0].padStart(2, "0")}-${parts[1].padStart(2, "0")}`;
    }
    return val;
}

/**
 * 根据爬取天数设置默认日期过滤范围
 */
function setDefaultDateFilter() {
    const days = parseInt(document.getElementById("scrapeDays").value) || 3;
    const now = new Date();
    const from = new Date(now);
    from.setDate(now.getDate() - days);

    const toStr = `${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const fromStr = `${String(from.getMonth() + 1).padStart(2, "0")}-${String(from.getDate()).padStart(2, "0")}`;

    document.getElementById("filterDateFrom").value = fromStr;
    document.getElementById("filterDateTo").value = toStr;
}

// ======== 文件夹选择器 ========
let _folderPickerCurrentPath = "";

function openFolderPicker() {
    document.getElementById("folderPickerModal").classList.add("show");
    // 从当前导出目录开始浏览
    const currentDir = document.getElementById("exportDir").value;
    browseTo(currentDir || "");
}

function closeFolderPicker() {
    document.getElementById("folderPickerModal").classList.remove("show");
}

async function browseTo(path) {
    const listEl = document.getElementById("folderList");
    const pathEl = document.getElementById("folderCurrentPath");
    listEl.innerHTML = '<p class="log-placeholder">加载中...</p>';

    try {
        const params = path ? `?path=${encodeURIComponent(path)}` : "";
        const resp = await fetch(`/api/browse_dirs${params}`);
        const data = await resp.json();

        if (!data.success) {
            listEl.innerHTML = `<p class="log-placeholder">❌ ${escapeHtml(data.message)}</p>`;
            return;
        }

        _folderPickerCurrentPath = data.current;
        pathEl.textContent = data.current;

        let html = "";

        // 返回上级目录
        if (data.parent) {
            html += `<div class="folder-item folder-parent" onclick="browseTo('${escapeHtml(data.parent)}')">
                ⬆️ 返回上级目录
            </div>`;
        }

        if (data.dirs.length === 0) {
            html += '<p class="log-placeholder">此目录下没有子文件夹</p>';
        } else {
            for (const dir of data.dirs) {
                const fullPath = data.current + "/" + dir;
                html += `<div class="folder-item" onclick="browseTo('${escapeHtml(fullPath)}')">
                    📁 ${escapeHtml(dir)}
                </div>`;
            }
        }

        listEl.innerHTML = html;
    } catch (e) {
        listEl.innerHTML = `<p class="log-placeholder">❌ 加载失败: ${escapeHtml(e.message)}</p>`;
    }
}

function selectFolder() {
    if (_folderPickerCurrentPath) {
        document.getElementById("exportDir").value = _folderPickerCurrentPath;
    }
    closeFolderPicker();
}
