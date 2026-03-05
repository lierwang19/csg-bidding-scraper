"""
Flask 应用入口
提供 Web UI 和 API 接口
"""
import os
import io
import json
import logging
import threading
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file

import storage
import scheduler
import exporter

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ======== 页面路由 ========

@app.route("/")
def index():
    return render_template("index.html")


# ======== API 路由 ========

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """手动触发爬取"""
    data = request.get_json() or {}
    categories = data.get("categories", ["工程", "服务"])
    company = data.get("company", "")
    sources = data.get("sources", None)

    if scheduler.scrape_status["running"]:
        return jsonify({"success": False, "message": "爬取任务正在执行中，请稍后再试"})

    def do_scrape():
        scheduler.run_scrape_job(
            categories=categories,
            company=company or None,
            sources=sources
        )

    thread = threading.Thread(target=do_scrape, daemon=True)
    thread.start()

    return jsonify({"success": True, "message": "爬取任务已启动"})


@app.route("/api/status")
def api_status():
    """获取爬取状态"""
    return jsonify(scheduler.get_status())


@app.route("/api/announcements")
def api_announcements():
    """查询公告列表"""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)
    category = request.args.get("category", "")
    company = request.args.get("company", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    keyword = request.args.get("keyword", "")
    source = request.args.get("source", "")

    items, total = storage.query_announcements(
        page=page,
        page_size=page_size,
        category=category or None,
        company=company or None,
        date_from=date_from or None,
        date_to=date_to or None,
        keyword=keyword or None,
        source=source or None,
    )

    return jsonify({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    })


@app.route("/api/companies")
def api_companies():
    """搜索公司列表"""
    q = request.args.get("q", "")
    results = storage.search_companies(q)
    return jsonify(results)


@app.route("/api/export")
def api_export():
    """导出 Excel"""
    category = request.args.get("category", "")
    company = request.args.get("company", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    keyword = request.args.get("keyword", "")
    source = request.args.get("source", "")

    items, _ = storage.query_announcements(
        page=1,
        page_size=10000,
        category=category or None,
        company=company or None,
        date_from=date_from or None,
        date_to=date_to or None,
        keyword=keyword or None,
        source=source or None,
    )

    output = exporter.generate_excel(items)

    filename = f"采购公告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """读取/保存设置"""
    if request.method == "GET":
        return jsonify({
            "categories": storage.get_setting("categories", "工程,服务"),
            "filter_company": storage.get_setting("filter_company", ""),
            "schedule_hour": int(storage.get_setting("schedule_hour", "12")),
            "schedule_minute": int(storage.get_setting("schedule_minute", "0")),
            "max_pages": int(storage.get_setting("max_pages", "5")),
            "scrape_days": int(storage.get_setting("scrape_days", "3")),
            "scrape_sources": storage.get_setting("scrape_sources", "bidding.csg.cn,ecsg.com.cn"),
            "auto_export": storage.get_setting("auto_export", "false") == "true",
            "export_dir": storage.get_setting("export_dir", "./data/exports"),
        })

    data = request.get_json() or {}

    if "categories" in data:
        storage.save_setting("categories", data["categories"])
    if "filter_company" in data:
        storage.save_setting("filter_company", data["filter_company"])
    if "max_pages" in data:
        storage.save_setting("max_pages", str(data["max_pages"]))
    if "scrape_days" in data:
        storage.save_setting("scrape_days", str(data["scrape_days"]))
    if "scrape_sources" in data:
        storage.save_setting("scrape_sources", data["scrape_sources"])
    if "auto_export" in data:
        storage.save_setting("auto_export", "true" if data["auto_export"] else "false")
    if "export_dir" in data:
        storage.save_setting("export_dir", data["export_dir"])

    if "schedule_hour" in data or "schedule_minute" in data:
        hour = int(data.get("schedule_hour", storage.get_setting("schedule_hour", "12")))
        minute = int(data.get("schedule_minute", storage.get_setting("schedule_minute", "0")))
        scheduler.update_schedule(hour, minute)

    return jsonify({"success": True, "message": "设置已保存"})


@app.route("/api/browse_dirs")
def api_browse_dirs():
    """浏览服务器目录结构，用于文件夹选择器"""
    path = request.args.get("path", "")

    # 默认起始路径
    import platform
    def _default_path():
        if platform.system() in ("Darwin", "Windows"):
            return os.path.expanduser("~/Desktop")
        return "/app/data"

    if not path:
        path = _default_path()

    path = os.path.abspath(path)

    # 路径不存在时回退到默认路径
    if not os.path.isdir(path):
        path = _default_path()
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return jsonify({"success": False, "message": f"目录不存在: {path}"})

    dirs = []
    try:
        for name in sorted(os.listdir(path)):
            if name.startswith("."):
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full):
                dirs.append(name)
    except PermissionError:
        return jsonify({"success": False, "message": f"无权限访问: {path}"})

    parent = os.path.dirname(path)

    return jsonify({
        "success": True,
        "current": path,
        "parent": parent if parent != path else None,
        "dirs": dirs,
    })


# ======== 启动 ========

if __name__ == "__main__":
    logger.info("🚀 南网采购平台爬取系统启动中...")
    scheduler.start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=False)
