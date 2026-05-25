# -*- coding: utf-8 -*-
r"""Install and initialize Crawl4AI for this project.

Run:
    E:\anaconda\python.exe install_crawl4ai.py

Optional:
    E:\anaconda\python.exe install_crawl4ai.py --upgrade
    E:\anaconda\python.exe install_crawl4ai.py --skip-setup
    E:\anaconda\python.exe install_crawl4ai.py --browser chromium
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def run_step(name: str, command: list[str], required: bool = True) -> bool:
    print(f"\n===== {name} =====")
    print("[cmd] " + " ".join(command))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(command, env=env)
    if result.returncode == 0:
        print(f"[ok] {name}")
        return True
    print(f"[warn] {name} 失败，退出码: {result.returncode}")
    if required:
        raise SystemExit(result.returncode)
    return False


def scripts_dir() -> Path:
    scripts = sysconfig.get_path("scripts")
    if scripts:
        return Path(scripts)
    return Path(sys.executable).resolve().parent / "Scripts"


def find_cli(name: str) -> str | None:
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found

    script_path = scripts_dir() / f"{name}.exe"
    if script_path.exists():
        return str(script_path)

    script_path = scripts_dir() / name
    if script_path.exists():
        return str(script_path)

    return None


def import_crawl4ai() -> None:
    try:
        import crawl4ai  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"[error] Crawl4AI 导入失败: {exc}") from exc

    version = "unknown"
    try:
        from crawl4ai.__version__ import __version__ as crawl4ai_version

        version = crawl4ai_version
    except Exception:
        pass
    print(f"[ok] Crawl4AI 已可导入，版本: {version}")


def install_package(args: argparse.Namespace) -> None:
    package = args.package
    command = [sys.executable, "-m", "pip", "install"]
    if args.upgrade:
        command.append("--upgrade")
    command.append(package)
    run_step("安装 Crawl4AI Python 包", command)


def run_crawl4ai_setup(args: argparse.Namespace) -> None:
    if args.skip_setup:
        print("\n[skip] 已跳过 crawl4ai-setup")
        return

    setup_cli = find_cli("crawl4ai-setup")
    if setup_cli:
        run_step("运行 crawl4ai-setup 初始化浏览器/依赖", [setup_cli], required=False)
        return

    print("\n[warn] 没找到 crawl4ai-setup，改用 Playwright 安装浏览器兜底")
    run_step(
        f"安装 Playwright 浏览器: {args.browser}",
        [sys.executable, "-m", "playwright", "install", args.browser],
        required=False,
    )


def run_doctor(args: argparse.Namespace) -> None:
    if args.skip_doctor:
        print("\n[skip] 已跳过 crawl4ai-doctor")
        return

    doctor_cli = find_cli("crawl4ai-doctor")
    if not doctor_cli:
        print("\n[warn] 没找到 crawl4ai-doctor，跳过环境诊断")
        return

    run_step("运行 crawl4ai-doctor 环境诊断", [doctor_cli], required=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安装并初始化 Crawl4AI")
    parser.add_argument(
        "--package",
        default=os.getenv("CRAWL4AI_PACKAGE", "crawl4ai"),
        help="pip 安装包名或版本约束，例如 crawl4ai==0.8.6",
    )
    parser.add_argument("--upgrade", action="store_true", help="升级已安装的 Crawl4AI")
    parser.add_argument("--skip-setup", action="store_true", help="跳过 crawl4ai-setup")
    parser.add_argument("--skip-doctor", action="store_true", help="跳过 crawl4ai-doctor")
    parser.add_argument(
        "--browser",
        default=os.getenv("CRAWL4AI_BROWSER", "chromium"),
        help="setup CLI 不存在时，用 Playwright 安装的浏览器，默认 chromium",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"[python] {sys.executable}")
    print(f"[scripts] {scripts_dir()}")
    print(f"[package] {args.package}")

    install_package(args)
    import_crawl4ai()
    run_crawl4ai_setup(args)
    run_doctor(args)

    print("\n===== 完成 =====")
    print("主流程里把 SEARCH_BACKEND = 2 即可使用：博查 URL + Crawl4AI 抓正文。")


if __name__ == "__main__":
    main()
