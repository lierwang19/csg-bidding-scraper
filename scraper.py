"""
爬虫核心模块
使用 Playwright 无头浏览器访问南网采购平台搜索页，解析公告列表。
- 只爬取最近 3 天的公告
- 请求间加入随机延时，避免 IP 封禁
"""
import asyncio
import random
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bidding.csg.cn"
SEARCH_URL = f"{BASE_URL}/dbsearch.jspx"
CHANNEL_ID = 309

# 安全间隔配置（秒）
MIN_DELAY = 3   # 最小等待
MAX_DELAY = 6   # 最大等待
PAGE_DELAY = 5  # 翻页间隔


async def _safe_delay(min_s=MIN_DELAY, max_s=MAX_DELAY):
    """随机延时，模拟人类行为"""
    delay = random.uniform(min_s, max_s)
    logger.info(f"等待 {delay:.1f} 秒...")
    await asyncio.sleep(delay)


async def scrape_announcements(categories=None, company=None, max_pages=5,
                                days=3, progress_callback=None):
    """
    爬取公告列表

    Args:
        categories: list, 如 ["工程", "服务"]
        company: str, 公司名称筛选（可选）
        max_pages: int, 每个类别最多翻页数
        days: int, 只爬取最近 N 天的数据
        progress_callback: callable, 进度回调 (message: str)

    Returns:
        list of dict, 每个 dict 包含公告信息
    """
    from playwright.async_api import async_playwright

    if categories is None:
        categories = ["工程", "服务"]

    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_items = []

    def log_progress(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        for cat in categories:
            log_progress(f"开始爬取【{cat}】类公告...")

            for page_no in range(1, max_pages + 1):
                # 构建 URL
                url = f"{SEARCH_URL}?channelId={CHANNEL_ID}&types={cat}&pageNo={page_no}"
                if company:
                    url += f"&org={company}"

                log_progress(f"  正在请求第 {page_no} 页: {url}")

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await _safe_delay()

                    # 等待搜索结果加载
                    try:
                        await page.wait_for_selector(".listinfo, .searchresult, .result-list, table",
                                                     timeout=10000)
                    except Exception:
                        pass  # 可能页面结构不同，继续尝试解析

                    html = await page.content()
                    items, should_stop = _parse_search_results(html, cat, cutoff_date)

                    log_progress(f"  第 {page_no} 页解析到 {len(items)} 条公告")
                    all_items.extend(items)

                    if should_stop:
                        log_progress(f"  已到达 {days} 天前的数据，停止翻页")
                        break

                    # 检查是否有下一页
                    if not _has_next_page(html, page_no):
                        log_progress(f"  没有更多页面了")
                        break

                    # 翻页间隔
                    await _safe_delay(PAGE_DELAY, PAGE_DELAY + 3)

                except Exception as e:
                    logger.error(f"  爬取第 {page_no} 页出错: {e}")
                    log_progress(f"  ⚠ 第 {page_no} 页爬取失败: {str(e)[:100]}")
                    await _safe_delay(8, 12)  # 出错时等久一点
                    continue

            # 切换类别间也要等待
            if cat != categories[-1]:
                log_progress(f"【{cat}】爬取完成，等待后继续...")
                await _safe_delay(5, 10)

        await browser.close()

    log_progress(f"爬取完成！共获取 {len(all_items)} 条公告")
    return all_items


def _parse_search_results(html, category, cutoff_date):
    """
    解析搜索结果页 HTML

    Returns:
        (items: list[dict], should_stop: bool)
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    should_stop = False

    # 尝试多种选择器来匹配搜索结果
    # 方式 1: 常见的列表项结构
    result_items = soup.select(".listinfo li, .searchresult li, .result-list li, "
                               ".news-list li, .list-item, .neirong li")

    if not result_items:
        # 方式 2: 表格结构
        result_items = soup.select("table tbody tr, table tr")

    if not result_items:
        # 方式 3: 通用的 div 列表
        result_items = soup.select(".clearfix li, #result li, .content li")

    # 方式 4: 直接查找包含日期格式的链接区域
    if not result_items:
        # 查找所有包含日期的文本节点附近的链接
        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if href and title and ".jhtml" in href and len(title) > 10:
                # 在链接附近查找日期
                parent = link.find_parent(["li", "tr", "div", "dd"])
                if parent:
                    date_text = _extract_date(parent.get_text())
                    company_text = _extract_company(parent)

                    full_url = href if href.startswith("http") else urljoin(BASE_URL, href)
                    ann_type = _extract_announcement_type(parent.get_text())

                    item = {
                        "title": title,
                        "url": full_url,
                        "company": company_text,
                        "category": category,
                        "announcement_type": ann_type,
                        "publish_date": date_text
                    }
                    items.append(item)

                    if date_text and date_text < cutoff_date:
                        should_stop = True
        return items, should_stop

    for el in result_items:
        try:
            # 提取标题和链接
            link = el.find("a", href=True)
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")

            if not title or len(title) < 5:
                continue

            # 跳过非公告链接
            if not href or (".jhtml" not in href and "/zbgg/" not in href
                            and "/fzbgg/" not in href and "/zbcg/" not in href):
                continue

            full_url = href if href.startswith("http") else urljoin(BASE_URL, href)

            # 提取日期
            date_text = _extract_date(el.get_text())

            # 提取公司/发布单位
            company_text = _extract_company(el)

            # 提取公告类型
            ann_type = _extract_announcement_type(el.get_text())

            item = {
                "title": title,
                "url": full_url,
                "company": company_text,
                "category": category,
                "announcement_type": ann_type,
                "publish_date": date_text
            }
            items.append(item)

            # 检查日期是否超过截止日期
            if date_text and date_text < cutoff_date:
                should_stop = True

        except Exception as e:
            logger.debug(f"解析单条公告出错: {e}")
            continue

    return items, should_stop


def _extract_date(text):
    """从文本中提取 YYYY-MM-DD 格式的日期"""
    import re
    match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    return match.group(1) if match else ""


def _extract_company(element):
    """尝试从元素中提取发布单位"""
    text = element.get_text()

    # 查找 span 或特定 class 中的公司名
    for span in element.find_all(["span", "td", "em"]):
        span_text = span.get_text(strip=True)
        if "电网" in span_text or "供电" in span_text or "电力" in span_text:
            return span_text

    # 从整体文本中查找公司特征词
    import re
    company_patterns = [
        r'([\u4e00-\u9fa5]*?(?:电网|供电|电力|能源)[\u4e00-\u9fa5]*?(?:公司|局|中心))',
    ]
    for pattern in company_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return ""


def _extract_announcement_type(text):
    """提取公告类型"""
    types = ["招标公告", "非招标公告", "竞争性谈判", "询价公告", "中标公告",
             "中标候选人公示", "结果公告", "变更公告", "资格预审"]
    for t in types:
        if t in text:
            return t
    return ""


def _has_next_page(html, current_page):
    """检查是否有下一页"""
    soup = BeautifulSoup(html, "lxml")

    # 查找分页控件
    pagination = soup.select(".pagination, .page, .pager, .pages, .fenye")
    if pagination:
        text = pagination[0].get_text()
        # 查找"下一页"链接
        next_link = soup.find("a", string=lambda s: s and ("下一页" in s or ">" in s))
        if next_link:
            return True

    # 查找页码链接
    page_links = soup.find_all("a", href=True)
    for link in page_links:
        href = link.get("href", "")
        if f"pageNo={current_page + 1}" in href:
            return True

    return current_page < 3  # 保守策略：默认尝试前 3 页


def run_scraper(categories=None, company=None, max_pages=5, days=3,
                progress_callback=None):
    """同步入口，方便外部调用"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            scrape_announcements(categories, company, max_pages, days, progress_callback)
        )
    finally:
        loop.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    results = run_scraper(categories=["工程"], max_pages=2, days=3)
    for r in results:
        print(f"[{r['publish_date']}] [{r['category']}] {r['title']}")
        print(f"  链接: {r['url']}")
        print(f"  单位: {r['company']}")
        print()
