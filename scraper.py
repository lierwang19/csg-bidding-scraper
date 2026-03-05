"""
爬虫核心模块 — 南网供应链统一服务平台 (bidding.csg.cn)
- 爬取招标公告和非招标公告（过滤掉公示公告）
- 进入详情页提取：标包/标的、预计采购金额、招标人、招标方式、报名时间、投标截止时间
"""
import asyncio
import random
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bidding.csg.cn"
SEARCH_URL = f"{BASE_URL}/dbsearch.jspx"
CHANNEL_ID = 309

SOURCE_NAME = "南网供应链(bidding.csg.cn)"

# 硬编码排除关键词 — 标题中包含这些词的公告在爬取时自动跳过
EXCLUDE_KEYWORDS = ["分包", "施工招标", "监理"]

# 安全间隔
MIN_DELAY = 3
MAX_DELAY = 6


async def _safe_delay(min_s=MIN_DELAY, max_s=MAX_DELAY):
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


async def scrape_announcements(categories=None, company=None, max_pages=5,
                                days=3, progress_callback=None):
    from playwright.async_api import async_playwright

    if categories is None:
        categories = ["工程", "服务"]

    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_items = []

    def log(msg):
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
            log(f"开始爬取【{cat}】类公告...")

            for page_no in range(1, max_pages + 1):
                org_param = company if company else ""
                url = (f"{SEARCH_URL}?pageNo={page_no}&channelId={CHANNEL_ID}"
                       f"&q=&org={org_param}&types={cat}")

                log(f"  正在请求第 {page_no} 页: {url}")

                try:
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    await _safe_delay()

                    try:
                        await page.wait_for_selector(".List2 li", timeout=15000)
                    except Exception:
                        pass

                    html = await page.content()
                    items, should_stop = _parse_search_results(html, cat, cutoff_date)

                    log(f"  第 {page_no} 页解析到 {len(items)} 条公告（已过滤公示公告）")

                    # 访问每条的详情页
                    for idx, item in enumerate(items):
                        detail_url = item.get("url", "")
                        if detail_url:
                            log(f"    [{idx+1}/{len(items)}] 获取详情: {item['title'][:30]}...")
                            try:
                                detail = await _scrape_detail_page(page, detail_url)
                                item.update(detail)
                                # 简要日志
                                amt = detail.get("estimated_amount", "")
                                tenderer = detail.get("tenderer", "")
                                if amt or tenderer:
                                    log(f"      → 招标人: {tenderer[:20] if tenderer else '-'} | 金额: {amt or '-'}")
                            except Exception as e:
                                logger.warning(f"    获取详情失败: {e}")
                            await _safe_delay(3, 6)

                    all_items.extend(items)

                    if should_stop:
                        log(f"  已到达 {days} 天前的数据，停止翻页")
                        break

                    if not _has_next_page(html, page_no):
                        log(f"  没有更多页面了")
                        break

                    await _safe_delay(5, 8)

                except Exception as e:
                    logger.error(f"  爬取第 {page_no} 页出错: {e}")
                    log(f"  ⚠ 第 {page_no} 页爬取失败: {str(e)[:100]}")
                    await _safe_delay(8, 12)
                    continue

            if cat != categories[-1]:
                log(f"【{cat}】爬取完成，等待后继续...")
                await _safe_delay(5, 10)

        await browser.close()

    log(f"[bidding.csg.cn] 爬取完成！共获取 {len(all_items)} 条公告")
    return all_items


def _parse_search_results(html, category, cutoff_date):
    """
    解析搜索结果页
    HTML 结构:
    <div class="List2"><ul>
      <li>
        <span class="Right">
          <a class="Black14">招标公告</a> | <span class="Black14 Gray">2026-03-05</span>
        </span>
        <span class="Blue">南方电网公司</span> | <a href="/zbgg/xxx.jhtml">标题</a>
      </li>
    </ul></div>
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    should_stop = False

    result_items = soup.select(".List2 li")
    if not result_items:
        result_items = [li for li in soup.select("li")
                        if li.find("a", href=lambda h: h and ".jhtml" in h)]

    for el in result_items:
        try:
            # 公告类型（a.Black14 元素）
            type_link = el.select_one("a.Black14")
            ann_type = type_link.get_text(strip=True) if type_link else ""

            # ★ 过滤公示公告
            if "公示" in ann_type or "公共" in ann_type:
                continue

            # 日期
            date_span = el.select_one("span.Gray, span.Black14.Gray")
            date_text = date_span.get_text(strip=True) if date_span else ""

            # 公司
            company_span = el.select_one("span.Blue, a.Blue")
            company_text = company_span.get_text(strip=True) if company_span else ""

            # 标题和链接 — 找 .jhtml 链接但排除 type_link
            title = ""
            full_url = ""
            for link in el.find_all("a", href=True):
                href = link.get("href", "")
                link_text = link.get_text(strip=True)
                if link == type_link or link == company_span:
                    continue
                if ".jhtml" in href and link_text and len(link_text) > 5:
                    title = link_text
                    full_url = href if href.startswith("http") else urljoin(BASE_URL, href)
                    break

            if not title:
                continue

            # ★ 硬编码关键词排除
            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue

            # 规范化采购类型：只保留 "招标公告" 或 "非招标公告"
            if "非招标" in ann_type:
                ann_type = "非招标公告"
            elif "招标" in ann_type:
                ann_type = "招标公告"

            item = {
                "title": title,
                "url": full_url,
                "company": company_text,
                "category": category,
                "announcement_type": ann_type,
                "publish_date": date_text,
                "source": SOURCE_NAME,
            }
            items.append(item)

            if date_text and date_text < cutoff_date:
                should_stop = True

        except Exception as e:
            logger.debug(f"解析单条公告出错: {e}")
            continue

    return items, should_stop


async def _scrape_detail_page(page, url):
    """
    访问详情页，提取字段:
    - 招标人: 从正文 regex（支持 招标人/采购人/采 购 人）
    - 招标方式: 从正文关键词（含 公开谈判采购 等）
    - 标包/标的 + 预计采购金额: 从 "标的清单" HTML 表格
    - 采购文件获取开始/结束时间: 支持多种日期格式
    - 响应/投标文件递交截止时间: 支持多种格式
    """
    result = {
        "bid_packages": "",
        "estimated_amount": "",
        "tenderer": "",
        "bidding_method": "",
        "reg_start_time": "",
        "reg_end_time": "",
        "bid_deadline": "",
    }

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        # 使用无分隔符的 get_text()，避免 HTML 标签导致
        # "获取开始" / "时间：" / "2026年0" / "3" 被拆到不同行
        text = soup.get_text()

        # === 提取完整标题（列表页标题可能被截断）===
        full_title = ""
        # 优先从 h1/h2 取标题
        for tag in ["h1", "h2"]:
            h = soup.find(tag)
            if h:
                t = h.get_text(strip=True)
                if len(t) > 5:
                    full_title = t
                    break
        # 其次从 <title> 取
        if not full_title and soup.title:
            t = soup.title.get_text(strip=True)
            # 去掉网站名后缀（如 "xxx - 南方电网供应链统一服务平台"）
            for suffix in [" - 南方电网", "-南方电网", "_南方电网"]:
                if suffix in t:
                    t = t[:t.index(suffix)]
                    break
            if len(t) > 5:
                full_title = t.strip()
        if full_title:
            result["title"] = full_title

        # === 招标人/采购人 ===
        # 支持: "招标人为 xxx", "采购人： xxx", "采 购 人 ： xxx"
        for pat in [
            r'招\s*标\s*人\s*[为是]?\s*[：:]\s*(.+?)(?:\s*[，。,\n])',
            r'采\s*购\s*人\s*[为是]?\s*[：:]\s*(.+?)(?:\s*[，。,\n])',
            r'项\s*目\s*业\s*主\s*[：:]\s*(.+?)(?:\s*[，。,\n])',
            r'招标人[为是]\s+(.+?)(?:\s*[，。,\n])',
            r'采购人[为是]\s+(.+?)(?:\s*[，。,\n])',
        ]:
            m = re.search(pat, text)
            if m:
                val = m.group(1).strip()
                if 2 < len(val) < 50:
                    result["tenderer"] = val
                    break

        # === 招标方式 ===
        for method in ["公开招标", "邀请招标", "公开询比采购", "竞争性谈判",
                        "单一来源采购", "单一来源", "竞争性磋商", "询价采购",
                        "框架招标", "公开框架招标", "公开比选",
                        "公开谈判采购", "公开谈判", "询比采购"]:
            if method in text:
                result["bidding_method"] = method
                break

        # === 标的清单表格 → 标包/标的 + 预计采购金额 ===
        _extract_from_table(soup, result)

        # 如果表格没提取到金额，用正文 regex 兜底
        if not result["estimated_amount"]:
            for pat in [
                r'(?:合计)?(?:预计)?采购(?:总)?金额[：:（(]?\s*([\d,\.]+)\s*万元',
                r'采购预算[：:（(]?\s*([\d,\.]+)\s*万元',
                r'控制价[：:（(]?\s*([\d,\.]+)\s*万元',
                r'概算金额[：:（(]?\s*([\d,\.]+)\s*万元',
            ]:
                m = re.search(pat, text)
                if m:
                    result["estimated_amount"] = f"{m.group(1)}万元"
                    break

        # === 时间提取 ===
        # 灵活的日期模式:
        #   2026年03月04日17时00分00秒  (标准，有前导零)
        #   2026年3月5日 23时59分59秒   (无前导零，有空格)
        #   2026年3月24日9时0分          (无秒)
        #   2026 年 2 月 28 日 17 时 0 分 (字符间有空格)
        FLEX_DATE = r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}\s*时\s*\d{1,2}\s*分(?:\s*\d{1,2}\s*秒)?'

        # === 采购文件获取开始时间 ===
        m = re.search(r'获取开始时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["reg_start_time"] = _normalize_datetime(m.group(1))

        # === 采购文件获取结束时间 ===
        m = re.search(r'获取结束时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["reg_end_time"] = _normalize_datetime(m.group(1))

        # 兜底: "自 xxxx年x月x日 至 xxxx年x月x日" 格式
        if not result["reg_start_time"]:
            m = re.search(
                r'自\s*(' + FLEX_DATE + r')\s*(?:至|到|—|-|~)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_start_time"] = _normalize_datetime(m.group(1))
                result["reg_end_time"] = _normalize_datetime(m.group(2))

        # 兜底: "获取时间: xxx 至 xxx"
        if not result["reg_start_time"]:
            m = re.search(
                r'(?:获取|报名)时间\s*[：:]\s*(' + FLEX_DATE + r')\s*(?:至|到|—|-|~)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_start_time"] = _normalize_datetime(m.group(1))
                result["reg_end_time"] = _normalize_datetime(m.group(2))

        # === 响应/投标文件递交截止时间 ===
        m = re.search(r'(?:响应|投标)文件递交截止时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["bid_deadline"] = _normalize_datetime(m.group(1))

        if not result["bid_deadline"]:
            m = re.search(r'递交截止时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
            if m:
                result["bid_deadline"] = _normalize_datetime(m.group(1))

        # 兜底: "截止时间为xxxx年x月x日x时x分"
        if not result["bid_deadline"]:
            m = re.search(r'截止时间[为是]?\s*(' + FLEX_DATE + ')', text)
            if m:
                result["bid_deadline"] = _normalize_datetime(m.group(1))

    except Exception as e:
        logger.warning(f"详情页解析失败 {url}: {e}")

    return result


def _extract_from_table(soup, result):
    """
    从 标的清单 表格中提取 标包/标的 和 预计采购金额。
    表头变体:
      预计采购金额（万元）/ 概算金额（万元）/ 最高投标限价（万元）
      标的名称 / 标段名称 / 标包名称
    """
    tables = soup.find_all("table")
    target_table = None
    amount_col = -1
    name_col = -1
    package_col = -1

    for table in tables:
        # 收集表头
        headers = table.find_all("th")
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = first_row.find_all("td")

        header_texts = [h.get_text(strip=True) for h in headers]
        if len(header_texts) < 3:
            continue

        # 重置每个表的列索引
        t_amount_col = -1
        t_name_col = -1
        t_package_col = -1

        for idx, ht in enumerate(header_texts):
            # 金额列: 匹配任何含"万元"的表头
            if "万元" in ht and t_amount_col < 0:
                t_amount_col = idx
            # 标的名称
            if ("标的" in ht and "名称" in ht) or ht == "标的":
                t_name_col = idx
            # 标段/标包名称
            if "标段" in ht or "标包" in ht:
                t_package_col = idx

        if t_amount_col >= 0:
            target_table = table
            amount_col = t_amount_col
            name_col = t_name_col
            package_col = t_package_col
            break

    if not target_table:
        return

    rows = target_table.find_all("tr")
    packages = []
    total_amount = 0.0
    amount_texts = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        # 提取标包名称
        pkg_name = ""
        if package_col >= 0 and package_col < len(cells):
            pkg_name = cells[package_col].get_text(strip=True)
        elif name_col >= 0 and name_col < len(cells):
            pkg_name = cells[name_col].get_text(strip=True)

        if pkg_name and pkg_name not in ("/", "-", "—", ""):
            packages.append(pkg_name)

        # 提取金额
        if amount_col >= 0 and amount_col < len(cells):
            amount_text = cells[amount_col].get_text(strip=True)
            amount_text = amount_text.replace(",", "").replace("，", "").strip()
            if amount_text in ("/", "-", "—", ""):
                continue
            try:
                amt = float(amount_text)
                total_amount += amt
                amount_texts.append(amount_text)
            except ValueError:
                pass

    if packages:
        result["bid_packages"] = "；".join(packages[:10])

    if total_amount > 0:
        if len(amount_texts) == 1:
            result["estimated_amount"] = f"{amount_texts[0]}万元"
        else:
            result["estimated_amount"] = f"{total_amount:.4f}万元"


def _normalize_datetime(s):
    """
    将各种中文日期格式转为 'YYYY-MM-DD HH:MM:SS'
    输入示例:
      '2026年03月04日17时00分00秒'
      '2026年3月5日 23时59分59秒'
      '2026 年 2 月 28 日 17 时 0 分'
    """
    if not s:
        return ""
    # 先去掉所有空格
    s = re.sub(r'\s+', '', s)
    # 用 regex 提取数字部分
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时(\d{1,2})分(?:(\d{1,2})秒)?', s)
    if m:
        year, month, day = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        hour, minute = m.group(4).zfill(2), m.group(5).zfill(2)
        second = m.group(6).zfill(2) if m.group(6) else "00"
        return f"{year}-{month}-{day} {hour}:{minute}:{second}"
    # 如果格式不匹配，简单替换
    s = s.replace("年", "-").replace("月", "-").replace("日", " ").replace("时", ":").replace("分", ":").replace("秒", "")
    return s.strip().rstrip(":")


def _has_next_page(html, current_page):
    soup = BeautifulSoup(html, "lxml")

    next_link = soup.find("a", string=lambda s: s and "下一页" in s)
    if next_link:
        return True

    page_links = soup.find_all("a", href=True)
    for link in page_links:
        href = link.get("href", "")
        if f"pageNo={current_page + 1}" in href:
            return True

    return current_page < 3


def run_scraper(categories=None, company=None, max_pages=5, days=3,
                progress_callback=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            scrape_announcements(categories, company, max_pages, days, progress_callback)
        )
    finally:
        loop.close()
