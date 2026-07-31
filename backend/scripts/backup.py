#!/usr/bin/env python3
"""
数据库备份与恢复脚本。

使用方式:
  # 备份
  python scripts/backup.py backup

  # 恢复
  python scripts/backup.py restore backups/2024-01-01_120000.sql.gz

  # 列出备份
  python scripts/backup.py list
"""

import argparse
import gzip
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path("backups")
DB_NAME = os.getenv("DB_NAME", "data_analysis")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "30"))


def backup():
    """执行数据库备份。"""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{ts}.sql.gz"
    filepath = BACKUP_DIR / filename

    cmd = [
        "mysqldump",
        f"--host={DB_HOST}",
        f"--port={DB_PORT}",
        f"--user={DB_USER}",
    ]
    if DB_PASS:
        cmd.append(f"--password={DB_PASS}")
    cmd.extend([
        "--single-transaction",
        "--routines",
        "--triggers",
        "--set-gtid-purged=OFF",
        DB_NAME,
    ])

    print(f"[Backup] 开始备份 {DB_NAME} ...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, check=True
        )
        with gzip.open(filepath, "wb") as f:
            f.write(result.stdout)
        size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"[Backup] 完成: {filepath} ({size_mb:.1f} MB)")
    except subprocess.CalledProcessError as e:
        print(f"[Backup] 失败: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)

    cleanup_old_backups()


def restore(filepath: str):
    """从备份文件恢复数据库。"""
    path = Path(filepath)
    if not path.exists():
        print(f"[Restore] 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "mysql",
        f"--host={DB_HOST}",
        f"--port={DB_PORT}",
        f"--user={DB_USER}",
    ]
    if DB_PASS:
        cmd.append(f"--password={DB_PASS}")
    cmd.append(DB_NAME)

    print(f"[Restore] 从 {filepath} 恢复到 {DB_NAME} ...")
    confirm = input("确认恢复？这将覆盖现有数据 [y/N]: ")
    if confirm.lower() != "y":
        print("[Restore] 已取消")
        return

    try:
        if str(path).endswith(".gz"):
            with gzip.open(path, "rb") as f:
                sql_data = f.read()
        else:
            with open(path, "rb") as f:
                sql_data = f.read()

        subprocess.run(cmd, input=sql_data, check=True)
        print("[Restore] 恢复完成")
    except subprocess.CalledProcessError as e:
        print(f"[Restore] 失败: {e}", file=sys.stderr)
        sys.exit(1)


def list_backups():
    """列出所有备份文件。"""
    if not BACKUP_DIR.exists():
        print("[List] 无备份目录")
        return
    files = sorted(BACKUP_DIR.glob("*.sql*"), reverse=True)
    if not files:
        print("[List] 无备份文件")
        return
    print(f"{'文件名':<35} {'大小':<10} {'时间'}")
    print("-" * 60)
    for f in files:
        size = f"{f.stat().st_size / 1024 / 1024:.1f} MB"
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        print(f"{f.name:<35} {size:<10} {mtime}")


def cleanup_old_backups():
    """清理超出保留数量的旧备份。"""
    files = sorted(BACKUP_DIR.glob("*.sql*"), reverse=True)
    if len(files) > MAX_BACKUPS:
        for old in files[MAX_BACKUPS:]:
            old.unlink()
            print(f"[Cleanup] 删除旧备份: {old.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据库备份恢复工具")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("backup", help="执行备份")
    restore_p = sub.add_parser("restore", help="恢复备份")
    restore_p.add_argument("file", help="备份文件路径")
    sub.add_parser("list", help="列出备份")

    args = parser.parse_args()
    if args.command == "backup":
        backup()
    elif args.command == "restore":
        restore(args.file)
    elif args.command == "list":
        list_backups()
    else:
        parser.print_help()
