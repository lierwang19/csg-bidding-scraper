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

    if scheduler.scrape_status["running"]:
        return jsonify({"success": False, "message": "爬取任务正在执行中，请稍后再试"})

    # 在后台线程执行爬取
    def do_scrape():
        scheduler.run_scrape_job(categories=categories, company=company or None)

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

    items, total = storage.query_announcements(
        page=page,
        page_size=page_size,
        category=category or None,
        company=company or None,
        date_from=date_from or None,
        date_to=date_to or None,
        keyword=keyword or None,
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

    items, _ = storage.query_announcements(
        page=1,
        page_size=10000,
        category=category or None,
        company=company or None,
        date_from=date_from or None,
        date_to=date_to or None,
        keyword=keyword or None,
    )

    # 生成 Excel
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "采购公告"

    # 表头样式
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")

    headers = ["序号", "标题", "发布单位", "类别", "公告类型", "发布日期", "链接"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row_idx, item in enumerate(items, 2):
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        ws.cell(row=row_idx, column=2, value=item["title"])
        ws.cell(row=row_idx, column=3, value=item.get("company", ""))
        ws.cell(row=row_idx, column=4, value=item.get("category", ""))
        ws.cell(row=row_idx, column=5, value=item.get("announcement_type", ""))
        ws.cell(row=row_idx, column=6, value=item.get("publish_date", ""))
        ws.cell(row=row_idx, column=7, value=item.get("url", ""))

    # 设置列宽
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 15
    ws.column_dimensions["G"].width = 50

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

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
            "webhook_key": storage.get_setting("webhook_key", ""),
            "categories": storage.get_setting("categories", "工程,服务"),
            "filter_company": storage.get_setting("filter_company", ""),
            "schedule_hour": int(storage.get_setting("schedule_hour", "12")),
            "schedule_minute": int(storage.get_setting("schedule_minute", "0")),
            "max_pages": int(storage.get_setting("max_pages", "5")),
            "scrape_days": int(storage.get_setting("scrape_days", "3")),
        })

    data = request.get_json() or {}

    if "webhook_key" in data:
        storage.save_setting("webhook_key", data["webhook_key"])
    if "categories" in data:
        storage.save_setting("categories", data["categories"])
    if "filter_company" in data:
        storage.save_setting("filter_company", data["filter_company"])
    if "max_pages" in data:
        storage.save_setting("max_pages", str(data["max_pages"]))
    if "scrape_days" in data:
        storage.save_setting("scrape_days", str(data["scrape_days"]))

    if "schedule_hour" in data or "schedule_minute" in data:
        hour = int(data.get("schedule_hour", storage.get_setting("schedule_hour", "12")))
        minute = int(data.get("schedule_minute", storage.get_setting("schedule_minute", "0")))
        scheduler.update_schedule(hour, minute)

    return jsonify({"success": True, "message": "设置已保存"})


# ======== 启动 ========

if __name__ == "__main__":
    logger.info("🚀 南网采购平台爬取系统启动中...")
    scheduler.start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=False)
