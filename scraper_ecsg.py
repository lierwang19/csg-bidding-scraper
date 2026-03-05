"""
爬虫模块 — 南方电网电子采购交易平台 (ecsg.com.cn)
底层使用 POST API: queryGatewayNoticeListPagination
payload: {"projectLevel1ClassifyId":"1","noticeType":"1","pageNo":1,"pageSize":20,...}

类别映射:
  projectLevel1ClassifyId: 1=工程, 2=货物, 3=服务
  noticeType: 1=招标公告, 2=非招标公告
"""
import asyncio
import random
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://ecsg.com.cn"
API_URL = f"{BASE_URL}/api/tender/tendermanage/gatewayNoticeQueryController/queryGatewayNoticeListPagination"
SOURCE_NAME = "电子交易平台(ecsg.com.cn)"

# 硬编码排除关键词 — 标题中包含这些词的公告在爬取时自动跳过
EXCLUDE_KEYWORDS = ["分包", "施工招标", "监理"]

# 类别映射
CATEGORY_MAP = {
    "工程": "1",
    "货物": "2",
    "服务": "3",
}

NOTICE_TYPES = {
    "招标公告": "1",
    "非招标公告": "2",
}

MIN_DELAY = 3
MAX_DELAY = 6


async def _safe_delay(min_s=MIN_DELAY, max_s=MAX_DELAY):
    await asyncio.sleep(random.uniform(min_s, max_s))


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

        # 先访问首页获取必要 cookies
        try:
            await page.goto(f"{BASE_URL}/cms/NoticeList.html?id=1-1&typeid=4&word=&seacrhDate=",
                            wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[ecsg] 首页加载失败: {e}")

        for cat in categories:
            classify_id = CATEGORY_MAP.get(cat, "")
            if not classify_id:
                continue

            for type_name, type_id in NOTICE_TYPES.items():
                log(f"[ecsg] 开始爬取【{cat} - {type_name}】...")

                for page_no in range(1, max_pages + 1):
                    log(f"  正在请求第 {page_no} 页 (API)...")

                    try:
                        # 使用 page.evaluate 发送 POST 请求
                        payload = {
                            "projectLevel1ClassifyId": classify_id,
                            "noticeType": type_id,
                            "noticeTitle": "",
                            "publishTime": "",
                            "organizationInfoName": company or "",
                            "pageNo": page_no,
                            "pageSize": 20,
                        }

                        response_data = await page.evaluate("""
                            async (payload) => {
                                try {
                                    const resp = await fetch('%s', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify(payload)
                                    });
                                    return await resp.json();
                                } catch (e) {
                                    return {error: e.message};
                                }
                            }
                        """ % API_URL, payload)

                        await _safe_delay()

                        if not response_data or "error" in response_data:
                            log(f"  ⚠ API 请求失败: {response_data.get('error', '未知错误')}")
                            break

                        # 解析 API 返回的数据
                        items, should_stop = _parse_api_response(
                            response_data, cat, type_name, cutoff_date
                        )

                        log(f"  第 {page_no} 页解析到 {len(items)} 条公告")

                        # 获取详情页
                        for idx, item in enumerate(items):
                            detail_url = item.get("url", "")
                            if detail_url:
                                log(f"    [{idx+1}/{len(items)}] 获取详情: {item['title'][:30]}...")
                                try:
                                    detail = await _scrape_detail_page(page, detail_url)
                                    item.update(detail)
                                    amt = detail.get("estimated_amount", "")
                                    tenderer = detail.get("tenderer", "")
                                    if amt or tenderer:
                                        log(f"      → 招标人: {tenderer[:20] if tenderer else '-'} | 金额: {amt or '-'}")
                                except Exception as e:
                                    logger.warning(f"    获取详情失败: {e}")
                                await _safe_delay(3, 6)

                        all_items.extend(items)

                        if should_stop:
                            log(f"  已到达 {days} 天前，停止翻页")
                            break

                        # 检查是否还有下一页
                        total_records = 0
                        try:
                            data_obj = response_data.get("data", response_data)
                            if isinstance(data_obj, dict):
                                total_records = int(data_obj.get("total", data_obj.get("totalCount", 0)))
                        except (ValueError, TypeError):
                            pass

                        if total_records and page_no * 20 >= total_records:
                            log(f"  已到达最后一页（共 {total_records} 条）")
                            break

                        if len(items) == 0:
                            log(f"  没有更多数据")
                            break

                        await _safe_delay(3, 5)

                    except Exception as e:
                        logger.error(f"  爬取第 {page_no} 页出错: {e}")
                        log(f"  ⚠ 第 {page_no} 页失败: {str(e)[:100]}")
                        await _safe_delay(5, 8)
                        continue

                await _safe_delay(2, 4)

            if cat != categories[-1]:
                log(f"[ecsg]【{cat}】爬取完成，等待后继续...")
                await _safe_delay(3, 6)

        await browser.close()

    log(f"[ecsg.com.cn] 爬取完成！共获取 {len(all_items)} 条公告")
    return all_items


def _parse_api_response(response_data, category, type_name, cutoff_date):
    """
    解析 API 返回的 JSON 数据
    预期结构不确定，尝试多种可能的 JSON 路径
    """
    items = []
    should_stop = False

    # 尝试多种 JSON 路径
    records = []
    data = response_data

    if isinstance(data, dict):
        # 可能的路径: data.records, data.data.records, data.list, data.rows
        for path in ["records", "data", "list", "rows", "content"]:
            val = data.get(path)
            if isinstance(val, list):
                records = val
                break
            elif isinstance(val, dict):
                for subpath in ["records", "list", "rows", "content"]:
                    subval = val.get(subpath)
                    if isinstance(subval, list):
                        records = subval
                        break
                if records:
                    break

    if not records:
        logger.warning(f"[ecsg] API返回结构未知: {str(data)[:300]}")
        return items, should_stop

    for record in records:
        try:
            # 尝试提取字段 — 猜测常见键名
            title = (record.get("noticeTitle") or record.get("title") or
                     record.get("noticeName") or record.get("name") or "")
            if not title:
                continue

            # ★ 硬编码关键词排除
            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue

            # 详情链接
            object_id = (record.get("objectId") or record.get("id") or
                         record.get("noticeId") or "")
            if object_id:
                detail_url = f"{BASE_URL}/cms/NoticeDetail.html?objectId={object_id}&objectType=1&typeid=4"
            else:
                detail_url = ""

            # 发布单位
            company = (record.get("organizationInfoName") or
                       record.get("publisherName") or
                       record.get("orgName") or
                       record.get("company") or "")

            # 发布日期 — API 返回的是 epoch 毫秒 (如 1772696418000)
            raw_date = (record.get("publishTime") or
                        record.get("publishDate") or
                        record.get("createTime") or "")
            date_text = ""
            if isinstance(raw_date, (int, float)) and raw_date > 1000000000:
                # epoch 毫秒 → 日期字符串
                ts = raw_date / 1000 if raw_date > 1e12 else raw_date
                date_text = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            elif isinstance(raw_date, str) and raw_date:
                date_text = raw_date[:10] if len(raw_date) > 10 else raw_date

            if date_text and date_text < cutoff_date:
                should_stop = True

            item = {
                "title": title.strip(),
                "url": detail_url,
                "company": company.strip(),
                "category": category,
                "announcement_type": type_name,
                "publish_date": date_text,
                "source": SOURCE_NAME,
            }
            items.append(item)

        except Exception as e:
            logger.debug(f"[ecsg] 解析记录出错: {e}")
            continue

    return items, should_stop


async def _scrape_detail_page(page, url):
    """
    提取 ecsg.com.cn 详情页字段。
    ecsg 页面特点:
    - 日期有大量空格: "2026 年 03 月 05 日 09时00分00秒"
    - 金额标签变体: "预计采购金额"、"项目预估金额"、"人民币xxx万元"
    - 招标人: "招标人：xxx" 或 "招标人为xxx"
    - 表格存储标的物/标包及金额信息
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

    # 灵活日期: 匹配 "2026 年 03 月 05 日 09时00分00秒" 等各种格式
    FLEX_DATE = r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}\s*时\s*\d{1,2}\s*分(?:\s*\d{1,2}\s*秒)?'

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()

        # === 招标人/采购人 ===
        for pat in [
            r'招\s*标\s*人\s*[为是]?\s*[：:]\s*(.+?)(?:\s*[，。,])',
            r'招标人[为是]\s*(.+?)(?:\s*[，。,])',
            r'采\s*购\s*人\s*[为是]?\s*[：:]\s*(.+?)(?:\s*[，。,])',
            r'采购人[为是]\s*(.+?)(?:\s*[，。,])',
            r'项\s*目\s*业\s*主\s*[：:]\s*(.+?)(?:\s*[，。,])',
            r'项\s*目\s*单\s*位\s*[：:]\s*(.+?)(?:\s*[，。,])',
        ]:
            m = re.search(pat, text)
            if m:
                val = m.group(1).strip()
                if 2 < len(val) < 50:
                    result["tenderer"] = val
                    break

        # === 招标方式/采购方式 ===
        for method in ["公开招标", "邀请招标", "公开询比采购", "竞争性谈判",
                        "单一来源采购", "单一来源", "竞争性磋商", "询价采购",
                        "框架招标", "公开框架招标", "公开比选",
                        "公开谈判采购", "公开谈判", "询比采购",
                        "公开询价"]:
            if method in text:
                result["bidding_method"] = method
                break

        # === 标的清单表格 → 标包/标的 + 金额 ===
        _extract_from_table(soup, result)

        # === 金额兜底 regex ===
        if not result["estimated_amount"]:
            for pat in [
                r'(?:合计)?(?:预计)?采购(?:总)?金额[：:（(]?\s*(?:人民币)?\s*([\d,\.]+)\s*万元',
                r'项目预估金额[：:（(]?\s*(?:人民币)?\s*([\d,\.]+)\s*万元',
                r'采购预算[：:（(]?\s*([\d,\.]+)\s*万元',
                r'控制价[：:（(]?\s*([\d,\.]+)\s*万元',
                r'概算金额[：:（(]?\s*([\d,\.]+)\s*万元',
                r'人民币\s*([\d,\.]+)\s*万元',
            ]:
                m = re.search(pat, text)
                if m:
                    result["estimated_amount"] = f"{m.group(1)}万元"
                    break

        # === 采购文件获取时间 ===
        # 格式1: "获取开始时间：xxxx" + "获取结束时间：xxxx"
        m = re.search(r'获取开始时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["reg_start_time"] = _normalize_datetime(m.group(1))
        m = re.search(r'获取结束时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["reg_end_time"] = _normalize_datetime(m.group(1))

        # 格式2: "报名及采购文件获取时间：xxxx至xxxx"
        if not result["reg_start_time"]:
            m = re.search(
                r'(?:报名及)?(?:采购|招标)?文件获取时间\s*[：:]\s*(' + FLEX_DATE + r')\s*(?:至|到|—|-|~)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_start_time"] = _normalize_datetime(m.group(1))
                result["reg_end_time"] = _normalize_datetime(m.group(2))

        # 格式3: "获取时间：xxxx 至 xxxx" 或 "获取时间：xxxx 到 xxxx"
        if not result["reg_start_time"]:
            m = re.search(
                r'获取时间\s*[：:]\s*(' + FLEX_DATE + r')\s*(?:至|到|—|-|~)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_start_time"] = _normalize_datetime(m.group(1))
                result["reg_end_time"] = _normalize_datetime(m.group(2))

        # 格式4: "自 xxxx 至 xxxx"
        if not result["reg_start_time"]:
            m = re.search(
                r'自\s*(' + FLEX_DATE + r')\s*(?:至|到|—|-|~)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_start_time"] = _normalize_datetime(m.group(1))
                result["reg_end_time"] = _normalize_datetime(m.group(2))

        # 格式5: "招标文件获取时间：公告发布之日起至 xxxx" (只有结束时间)
        if not result["reg_end_time"]:
            m = re.search(
                r'(?:文件)?获取时间\s*[：:]\s*(?:公告发布之日起)?(?:至|到)\s*(' + FLEX_DATE + ')',
                text)
            if m:
                result["reg_end_time"] = _normalize_datetime(m.group(1))

        # === 投标/响应文件递交截止时间 ===
        m = re.search(r'(?:响应|投标)文件递交截止时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
        if m:
            result["bid_deadline"] = _normalize_datetime(m.group(1))

        if not result["bid_deadline"]:
            m = re.search(r'递交截止时间\s*[：:]\s*(' + FLEX_DATE + ')', text)
            if m:
                result["bid_deadline"] = _normalize_datetime(m.group(1))

        if not result["bid_deadline"]:
            m = re.search(r'截止时间[为是]?\s*[：:]?\s*(' + FLEX_DATE + ')', text)
            if m:
                result["bid_deadline"] = _normalize_datetime(m.group(1))

    except Exception as e:
        logger.warning(f"[ecsg] 详情页解析失败 {url}: {e}")

    return result


def _extract_from_table(soup, result):
    """从 ecsg 标的物/标包表格中提取标包名称和金额"""
    tables = soup.find_all("table")
    target_table = None
    amount_col = -1
    name_col = -1

    for table in tables:
        headers = table.find_all("th")
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = first_row.find_all("td")

        header_texts = [h.get_text(strip=True) for h in headers]
        if len(header_texts) < 2:
            continue

        t_amount_col = -1
        t_name_col = -1

        for idx, ht in enumerate(header_texts):
            if "万元" in ht and t_amount_col < 0:
                t_amount_col = idx
            if ("名称" in ht and ("标" in ht or "项目" in ht)) or ht in ("标的", "标包", "标段"):
                t_name_col = idx

        if t_amount_col >= 0 or t_name_col >= 0:
            target_table = table
            amount_col = t_amount_col
            name_col = t_name_col
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

        pkg_name = ""
        if name_col >= 0 and name_col < len(cells):
            pkg_name = cells[name_col].get_text(strip=True)

        if pkg_name and pkg_name not in ("/", "-", "—", ""):
            packages.append(pkg_name)

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
            result["estimated_amount"] = f"{total_amount:.2f}万元"


def _normalize_datetime(s):
    """
    将各种中文日期格式转为 'YYYY-MM-DD HH:MM:SS'
    支持: '2026 年 03 月 05 日 09时00分00秒', '2026年3月5日 23时59分'
    """
    if not s:
        return ""
    s = re.sub(r'\s+', '', s)
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时(\d{1,2})分(?:(\d{1,2})秒)?', s)
    if m:
        year, month, day = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        hour, minute = m.group(4).zfill(2), m.group(5).zfill(2)
        second = m.group(6).zfill(2) if m.group(6) else "00"
        return f"{year}-{month}-{day} {hour}:{minute}:{second}"
    s = s.replace("年", "-").replace("月", "-").replace("日", " ").replace("时", ":").replace("分", ":").replace("秒", "")
    return s.strip().rstrip(":")


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
