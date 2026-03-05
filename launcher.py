"""
Windows 启动器
- 设置 Playwright 浏览器路径
- 启动 Flask 应用
- 自动打开默认浏览器
- 系统托盘图标（最小化到托盘，右键退出）
"""
import os
import sys
import time
import threading
import webbrowser
import logging

# ====== 路径设置 ======
# PyInstaller 打包后 sys._MEIPASS 指向临时解压目录
# 但我们使用 --onedir 模式，所以用可执行文件所在目录
if getattr(sys, 'frozen', False):
    # 打包后运行
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 开发模式
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 设置工作目录为应用所在目录
os.chdir(BASE_DIR)

# Playwright 浏览器路径：打包后放在 browsers/ 子目录
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(BASE_DIR, "browsers")

# 数据目录放在应用目录下的 data/
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 日志配置
LOG_FILE = os.path.join(DATA_DIR, "app.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("launcher")

PORT = 5000
URL = f"http://localhost:{PORT}"


def open_browser():
    """延迟打开浏览器，等待 Flask 启动"""
    for _ in range(30):
        time.sleep(1)
        try:
            import urllib.request
            urllib.request.urlopen(URL, timeout=2)
            webbrowser.open(URL)
            logger.info(f"已打开浏览器: {URL}")
            return
        except Exception:
            continue
    logger.warning("等待 Flask 启动超时")


def run_tray_icon():
    """运行系统托盘图标"""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        logger.warning("pystray 或 Pillow 未安装，跳过托盘图标")
        return

    def on_open(icon, item):
        webbrowser.open(URL)

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    # 创建简单的图标图像（蓝色方块带白色 "南" 字）
    icon_path = os.path.join(BASE_DIR, "app.ico")
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        # 如果没有图标文件，创建一个简单的蓝色图标
        image = Image.new("RGB", (64, 64), color=(43, 87, 154))

    menu = pystray.Menu(
        pystray.MenuItem("打开浏览器", on_open, default=True),
        pystray.MenuItem("退出", on_exit),
    )

    icon = pystray.Icon("csg-scraper", image, "南网采购助手", menu)

    # 双击托盘图标打开浏览器
    logger.info("系统托盘图标已启动")
    icon.run()


def main():
    logger.info("=" * 50)
    logger.info("南网采购助手启动中...")
    logger.info(f"应用目录: {BASE_DIR}")
    logger.info(f"数据目录: {DATA_DIR}")
    logger.info(f"浏览器路径: {os.environ.get('PLAYWRIGHT_BROWSERS_PATH')}")
    logger.info("=" * 50)

    # 后台线程：打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()

    # 后台线程：系统托盘
    threading.Thread(target=run_tray_icon, daemon=True).start()

    # 启动 Flask 应用（主线程）
    import app as flask_app
    flask_app.app.run(host="127.0.0.1", port=PORT, debug=False)


if __name__ == "__main__":
    main()
