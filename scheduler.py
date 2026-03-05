"""
定时调度模块
使用 APScheduler 实现每天定时爬取并推送
支持多来源（bidding.csg.cn / ecsg.com.cn）
"""
import logging
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import storage
import scraper
import scraper_ecsg
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
    if len(scrape_status["progress"]) > 100:
        scrape_status["progress"] = scrape_status["progress"][-100:]


def run_scrape_job(categories=None, company=None, sources=None):
    """执行一次爬取任务（支持多来源）"""
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

        if sources is None:
            sources_setting = storage.get_setting("scrape_sources", "bidding.csg.cn,ecsg.com.cn")
            sources = [s.strip() for s in sources_setting.split(",") if s.strip()]

        max_pages = int(storage.get_setting("max_pages", "5"))
        days = int(storage.get_setting("scrape_days", "3"))

        _progress_callback(f"开始爬取 - 来源: {sources}, 类别: {categories}, 公司: {company or '全部'}, 天数: {days}")

        all_items = []

        # bidding.csg.cn
        if "bidding.csg.cn" in sources:
            _progress_callback("━━━ 开始爬取 南网供应链(bidding.csg.cn) ━━━")
            try:
                items = scraper.run_scraper(
                    categories=categories,
                    company=company or None,
                    max_pages=max_pages,
                    days=days,
                    progress_callback=_progress_callback
                )
                all_items.extend(items)
            except Exception as e:
                logger.error(f"bidding.csg.cn 爬取失败: {e}", exc_info=True)
                _progress_callback(f"❌ bidding.csg.cn 爬取失败: {str(e)[:100]}")

        # ecsg.com.cn
        if "ecsg.com.cn" in sources:
            _progress_callback("━━━ 开始爬取 电子交易平台(ecsg.com.cn) ━━━")
            try:
                items = scraper_ecsg.run_scraper(
                    categories=categories,
                    company=company or None,
                    max_pages=max_pages,
                    days=days,
                    progress_callback=_progress_callback
                )
                all_items.extend(items)
            except Exception as e:
                logger.error(f"ecsg.com.cn 爬取失败: {e}", exc_info=True)
                _progress_callback(f"❌ ecsg.com.cn 爬取失败: {str(e)[:100]}")

        # 按标题关键词过滤
        title_keywords_str = storage.get_setting("title_keywords", "")
        if title_keywords_str.strip():
            keywords = [kw.strip() for kw in title_keywords_str.split(",") if kw.strip()]
            if keywords:
                before_count = len(all_items)
                all_items = [
                    item for item in all_items
                    if not any(kw in item.get("title", "") for kw in keywords)
                ]
                filtered_count = before_count - len(all_items)
                _progress_callback(f"关键词过滤：{before_count} → {len(all_items)} 条（过滤掉 {filtered_count} 条）")
                _progress_callback(f"过滤关键词: {', '.join(keywords)}")

        # 清空旧数据并存入新数据（在新数据准备好后才清空，避免查询时看到空数据）
        storage.clear_announcements()
        _progress_callback("已清空旧数据")

        # 存入数据库
        new_count = storage.save_announcements(all_items)
        _progress_callback(f"入库完成：共 {len(all_items)} 条，新增 {new_count} 条")

        # 推送微信
        webhook_key = storage.get_setting("webhook_key", "")
        if webhook_key and new_count > 0:
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            new_announcements = storage.get_new_announcements_since(since)
            success, msg = notifier.send_wechat_message(webhook_key, new_announcements)
            _progress_callback(f"微信推送: {msg}")
        elif not webhook_key:
            _progress_callback("未配置 Webhook Key，跳过微信推送")

        result = {
            "success": True,
            "total": len(all_items),
            "new_count": new_count,
            "message": f"爬取完成，共 {len(all_items)} 条，新增 {new_count} 条"
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
        "progress": scrape_status["progress"][-30:],
        "schedule_hour": int(storage.get_setting("schedule_hour", "12")),
        "schedule_minute": int(storage.get_setting("schedule_minute", "0")),
    }
