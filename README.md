# 南网采购平台 - 数据爬取系统

自动爬取中国南方电网采购平台 (www.bidding.csg.cn) 的采购公告，支持 Web 管理界面、数据导出和企业微信推送。

## 功能特性

- 🕷️ **智能爬取**：支持按类别（工程/服务）、发布单位筛选，仅爬取最近 N 天数据
- 🛡️ **防封保护**：请求间随机延时 3-6 秒，翻页间隔 5-8 秒
- 📊 **Web 管理界面**：爬取设置、数据浏览、筛选、分页
- 📥 **Excel 导出**：一键导出查询结果
- 📱 **微信推送**：自动推送新公告到企业微信群
- ⏰ **定时执行**：每天自动爬取（默认 12:00）
- 💾 **SQLite 存储**：自动去重，持久化存储

## 安装与运行

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器引擎
```bash
playwright install chromium
```

### 3. 启动系统
```bash
python app.py
```

浏览器访问 http://localhost:5000

### 4. 配置（在 Web 界面操作）
- 选择爬取类别（工程/服务）
- 设置发布单位筛选（可选）
- 填写企业微信 Webhook Key（可选）
- 设置定时执行时间

## 项目结构

```
├── app.py          # Flask 应用入口
├── scraper.py      # 爬虫核心 (Playwright)
├── storage.py      # SQLite 数据存储
├── notifier.py     # 企业微信推送
├── scheduler.py    # 定时调度
├── templates/      # 前端页面
├── static/         # CSS + JS
└── data/           # 数据库文件
```
