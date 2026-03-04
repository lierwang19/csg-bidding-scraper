"""
企业微信群机器人 Webhook 推送模块
"""
import requests
import logging

logger = logging.getLogger(__name__)

WEBHOOK_URL_TEMPLATE = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={}"
MAX_CONTENT_LENGTH = 3800  # markdown 消息体限制 4096，留些余量


def send_wechat_message(webhook_key, announcements):
    """
    通过企业微信 Webhook 发送公告汇总消息
    announcements: list of dict
    返回 (success: bool, message: str)
    """
    if not webhook_key:
        return False, "未配置 Webhook Key"

    if not announcements:
        return True, "没有新公告需要推送"

    url = WEBHOOK_URL_TEMPLATE.format(webhook_key)

    # 按类别分组
    by_category = {}
    for a in announcements:
        cat = a.get("category", "其他")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(a)

    # 构建消息分段
    segments = []
    current_segment = f"📢 **南网采购公告更新**\n> 共 {len(announcements)} 条新公告\n\n"

    for cat, items in by_category.items():
        section = f"### 【{cat}】共 {len(items)} 条\n"
        for item in items:
            title = item.get("title", "无标题")
            link = item.get("url", "")
            company = item.get("company", "")
            date = item.get("publish_date", "")
            line = f"- [{title}]({link})\n  {company} | {date}\n"

            if len(current_segment + section + line) > MAX_CONTENT_LENGTH:
                segments.append(current_segment + section)
                current_segment = f"📢 **南网采购公告更新（续）**\n\n"
                section = ""

            section += line

        current_segment += section

    segments.append(current_segment)

    # 逐段发送
    success = True
    for i, content in enumerate(segments):
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content.strip()
            }
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"微信推送失败 (段{i+1}): {data}")
                success = False
        except Exception as e:
            logger.error(f"微信推送异常 (段{i+1}): {e}")
            success = False

    msg = f"推送完成，共 {len(segments)} 段" if success else "部分推送失败"
    return success, msg
