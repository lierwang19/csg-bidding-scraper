"""
SQLite 数据存储模块
- announcements 表：存储爬取到的公告
- companies 表：存储出现过的公司名称，用于模糊搜索
- settings 表：存储配置信息
"""
import sqlite3
import os
from datetime import datetime, timedelta

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "announcements.db")


def get_connection():
    """获取数据库连接"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            company TEXT,
            category TEXT,
            announcement_type TEXT,
            publish_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_date ON announcements(publish_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_category ON announcements(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_company ON announcements(company)")

    conn.commit()
    conn.close()


def save_announcements(items):
    """
    批量保存公告，返回新增条数。
    items: list of dict, 每个 dict 包含 title, url, company, category, announcement_type, publish_date
    """
    conn = get_connection()
    cursor = conn.cursor()
    new_count = 0

    for item in items:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO announcements (title, url, company, category, announcement_type, publish_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item.get("title", ""),
                item.get("url", ""),
                item.get("company", ""),
                item.get("category", ""),
                item.get("announcement_type", ""),
                item.get("publish_date", ""),
            ))
            if cursor.rowcount > 0:
                new_count += 1

                # 同时将公司名存入 companies 表
                company = item.get("company", "").strip()
                if company:
                    cursor.execute("INSERT OR IGNORE INTO companies (name) VALUES (?)", (company,))
        except sqlite3.Error:
            continue

    conn.commit()
    conn.close()
    return new_count


def query_announcements(page=1, page_size=20, category=None, company=None,
                        date_from=None, date_to=None, keyword=None):
    """
    分页查询公告
    返回 (items, total_count)
    """
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if company:
        conditions.append("company LIKE ?")
        params.append(f"%{company}%")
    if date_from:
        conditions.append("publish_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("publish_date <= ?")
        params.append(date_to)
    if keyword:
        conditions.append("title LIKE ?")
        params.append(f"%{keyword}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # 总数
    cursor.execute(f"SELECT COUNT(*) FROM announcements WHERE {where_clause}", params)
    total = cursor.fetchone()[0]

    # 分页数据
    offset = (page - 1) * page_size
    cursor.execute(f"""
        SELECT * FROM announcements
        WHERE {where_clause}
        ORDER BY publish_date DESC, id DESC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return items, total


def search_companies(keyword=""):
    """模糊搜索公司名称"""
    conn = get_connection()
    cursor = conn.cursor()
    if keyword:
        cursor.execute("SELECT name FROM companies WHERE name LIKE ? ORDER BY name LIMIT 20",
                        (f"%{keyword}%",))
    else:
        cursor.execute("SELECT name FROM companies ORDER BY name")
    results = [row["name"] for row in cursor.fetchall()]
    conn.close()
    return results


def get_setting(key, default=None):
    """读取配置"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default


def save_setting(key, value):
    """保存配置"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_new_announcements_since(since_date):
    """获取某日期之后的新公告（用于推送）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM announcements
        WHERE publish_date >= ?
        ORDER BY publish_date DESC, id DESC
    """, (since_date,))
    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return items


# 启动时初始化
init_db()
