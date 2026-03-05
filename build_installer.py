"""
一键构建 Windows 安装包

用法:
    python build_installer.py                # 完整构建（PyInstaller + Inno Setup）
    python build_installer.py --pyinstaller  # 仅 PyInstaller 打包
    python build_installer.py --inno         # 仅 Inno Setup 编译（需已有 dist/）

前提条件:
    1. pip install pyinstaller pystray Pillow   (打包工具和托盘依赖)
    2. 已安装 Playwright 并下载了 Chromium: python -m playwright install chromium
    3. (可选) 安装 Inno Setup 6.x: https://jrsoftware.org/isinfo.php
"""
import os
import sys
import glob
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_NAME = "南网采购助手"
DIST_DIR = os.path.join(BASE_DIR, "dist", APP_NAME)


def find_playwright_browsers():
    """查找 Playwright 浏览器安装路径"""
    # 优先使用环境变量
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if env_path and os.path.isdir(env_path):
        return env_path

    # 默认位置
    default_path = os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")
    if os.path.isdir(default_path):
        return default_path

    raise FileNotFoundError(
        "找不到 Playwright 浏览器！\n"
        "请先运行: python -m playwright install chromium"
    )


def find_playwright_driver():
    """查找 Playwright driver 目录（含 node + cli.js）"""
    import playwright
    pw_dir = os.path.dirname(playwright.__file__)
    driver_dir = os.path.join(pw_dir, "driver")
    if os.path.isdir(driver_dir):
        return driver_dir
    raise FileNotFoundError(f"找不到 Playwright driver: {driver_dir}")


def find_inno_setup():
    """查找 Inno Setup 编译器"""
    possible = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    ]
    for p in possible:
        if os.path.isfile(p):
            return p
    return None


def step_install_deps():
    """安装构建依赖"""
    print("\n📦 安装构建依赖...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "pyinstaller", "pystray", "Pillow",
        "--quiet"
    ])
    print("   ✅ 依赖安装完成")


def step_pyinstaller():
    """运行 PyInstaller 打包"""
    print("\n🔨 开始 PyInstaller 打包...")

    pw_browser_path = find_playwright_browsers()
    pw_driver_path = find_playwright_driver()

    print(f"   Playwright 浏览器: {pw_browser_path}")
    print(f"   Playwright Driver: {pw_driver_path}")

    # 清理旧构建
    for d in ["build", "dist"]:
        p = os.path.join(BASE_DIR, d)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print(f"   清理 {d}/")

    # 查找所有浏览器目录（chromium, chromium_headless_shell, ffmpeg, winldd 等）
    browser_subdirs = [
        d for d in os.listdir(pw_browser_path)
        if os.path.isdir(os.path.join(pw_browser_path, d)) and not d.startswith(".")
    ]
    if not browser_subdirs:
        raise FileNotFoundError(f"在 {pw_browser_path} 中找不到浏览器目录")
    print(f"   浏览器组件: {browser_subdirs}")

    # 构建 PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        # 不用 --onefile，用 --onedir（启动更快，且方便携带大量浏览器文件）
        "--contents-directory", ".",
        # 添加数据文件
        "--add-data", f"templates{os.pathsep}templates",
        "--add-data", f"static{os.pathsep}static",
        # 添加 Playwright driver
        "--add-data", f"{pw_driver_path}{os.pathsep}playwright/driver",
        # 隐藏导入
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.async_api",
        "--hidden-import", "playwright._impl",
        "--hidden-import", "playwright._impl._driver",
        "--hidden-import", "engineio.async_drivers.threading",
        "--hidden-import", "apscheduler.triggers.cron",
        "--hidden-import", "apscheduler.schedulers.background",
        "--hidden-import", "apscheduler.executors.pool",
        "--hidden-import", "apscheduler.jobstores.memory",
        "--hidden-import", "pystray",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        # 收集整个 playwright 包
        "--collect-all", "playwright",
        # 窗口模式（不显示命令行窗口）
        "--noconsole",
    ]

    # 图标
    ico_path = os.path.join(BASE_DIR, "app.ico")
    if os.path.isfile(ico_path):
        cmd.extend(["--icon", ico_path])

    # 入口脚本
    cmd.append("launcher.py")

    print(f"   运行 PyInstaller...")
    subprocess.check_call(cmd, cwd=BASE_DIR)

    # 打包完成后，复制所有 Playwright 浏览器组件到 dist 目录
    print(f"\n📂 复制 Playwright 浏览器组件...")
    for subdir in browser_subdirs:
        src = os.path.join(pw_browser_path, subdir)
        dest = os.path.join(DIST_DIR, "browsers", subdir)
        print(f"   复制 {subdir}...")
        shutil.copytree(src, dest)
    print(f"   ✅ 所有浏览器组件已复制")

    # 创建 data 目录
    os.makedirs(os.path.join(DIST_DIR, "data"), exist_ok=True)

    print(f"\n✅ PyInstaller 打包完成！输出目录: {DIST_DIR}")


def step_inno_setup():
    """运行 Inno Setup 编译安装包"""
    iscc = find_inno_setup()
    if not iscc:
        print("\n⚠️  未找到 Inno Setup，跳过安装包编译。")
        print("   如需生成安装包，请安装 Inno Setup 6: https://jrsoftware.org/isinfo.php")
        print(f"   当前可以直接使用 {DIST_DIR} 目录运行程序。")
        return

    iss_file = os.path.join(BASE_DIR, "installer.iss")
    if not os.path.isfile(iss_file):
        print(f"\n❌ 找不到 Inno Setup 脚本: {iss_file}")
        return

    print(f"\n📦 编译 Inno Setup 安装包...")
    print(f"   ISCC: {iscc}")
    subprocess.check_call([iscc, iss_file])
    print(f"\n✅ 安装包已生成！查看 output/ 目录")


def main():
    args = set(sys.argv[1:])

    if not args or args == {"--all"}:
        # 完整构建
        step_install_deps()
        step_pyinstaller()
        step_inno_setup()
    elif "--pyinstaller" in args:
        step_install_deps()
        step_pyinstaller()
    elif "--inno" in args:
        step_inno_setup()
    else:
        print(f"未知参数: {args}")
        print("用法:")
        print("  python build_installer.py                # 完整构建")
        print("  python build_installer.py --pyinstaller   # 仅 PyInstaller")
        print("  python build_installer.py --inno          # 仅 Inno Setup")
        sys.exit(1)


if __name__ == "__main__":
    main()
