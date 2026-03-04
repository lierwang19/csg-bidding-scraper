"""
定时调度模块
使用 APScheduler 实现每天定时爬取并推送
"""
import logging
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import storage
import scraper
import notifier

logger = logging.getLogger(__name__)

_scheduler = None
_scheduler_lock = threading.Lock()

# 爬取状态
scrape_status = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "progress": []
}


def _progress_callback(msg):
    """记录爬取进度"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    scrape_status["progress"].append(f"[{timestamp}] {msg}")
    # 只保留最近 50 条进度
    if len(scrape_status["progress"]) > 50:
        scrape_status["progress"] = scrape_status["progress"][-50:]


def run_scrape_job(categories=None, company=None):
    """执行一次爬取任务"""
    if scrape_status["running"]:
        logger.warning("爬取任务正在执行中，跳过本次")
        return {"success": False, "message": "爬取任务正在执行中"}

    scrape_status["running"] = True
    scrape_status["progress"] = []

    try:
        # 读取配置
        if categories is None:
            cats_setting = storage.get_setting("categories", "工程,服务")
            categories = [c.strip() for c in cats_setting.split(",") if c.strip()]

        if company is None:
            company = storage.get_setting("filter_company", "")

        max_pages = int(storage.get_setting("max_pages", "5"))
        days = int(storage.get_setting("scrape_days", "3"))

        _progress_callback(f"开始爬取 - 类别: {categories}, 公司: {company or '全部'}, 天数: {days}")

        # 执行爬取
        items = scraper.run_scraper(
            categories=categories,
            company=company or None,
            max_pages=max_pages,
            days=days,
            progress_callback=_progress_callback
        )

        # 存入数据库
        new_count = storage.save_announcements(items)
        _progress_callback(f"入库完成：共 {len(items)} 条，新增 {new_count} 条")

        # 推送微信
        webhook_key = storage.get_setting("webhook_key", "")
        if webhook_key and new_count > 0:
            # 只推送新公告
            today = datetime.now().strftime("%Y-%m-%d")
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            new_announcements = storage.get_new_announcements_since(since)
            success, msg = notifier.send_wechat_message(webhook_key, new_announcements)
            _progress_callback(f"微信推送: {msg}")
        elif not webhook_key:
            _progress_callback("未配置 Webhook Key，跳过微信推送")

        result = {
            "success": True,
            "total": len(items),
            "new_count": new_count,
            "message": f"爬取完成，共 {len(items)} 条，新增 {new_count} 条"
        }
        scrape_status["last_result"] = result
        scrape_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        storage.save_setting("last_run", scrape_status["last_run"])

        return result

    except Exception as e:
        error_msg = f"爬取任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        _progress_callback(f"❌ {error_msg}")
        scrape_status["last_result"] = {"success": False, "message": error_msg}
        return scrape_status["last_result"]

    finally:
        scrape_status["running"] = False


def start_scheduler():
    """启动定时调度器"""
    global _scheduler

    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            return

        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        hour = int(storage.get_setting("schedule_hour", "12"))
        minute = int(storage.get_setting("schedule_minute", "0"))

        _scheduler.add_job(
            run_scrape_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_scrape",
            replace_existing=True,
            name="每日定时爬取"
        )

        _scheduler.start()
        logger.info(f"定时任务已启动：每天 {hour:02d}:{minute:02d} 执行")


def update_schedule(hour, minute):
    """更新定时任务时间"""
    global _scheduler

    storage.save_setting("schedule_hour", str(hour))
    storage.save_setting("schedule_minute", str(minute))

    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            _scheduler.reschedule_job(
                "daily_scrape",
                trigger=CronTrigger(hour=hour, minute=minute)
            )
            logger.info(f"定时任务已更新为：每天 {hour:02d}:{minute:02d}")


def get_status():
    """获取当前状态"""
    return {
        "running": scrape_status["running"],
        "last_run": scrape_status["last_run"] or storage.get_setting("last_run", "从未执行"),
        "last_result": scrape_status["last_result"],
        "progress": scrape_status["progress"][-20:],
        "schedule_hour": int(storage.get_setting("schedule_hour", "12")),
        "schedule_minute": int(storage.get_setting("schedule_minute", "0")),
    }
