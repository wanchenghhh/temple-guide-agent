#!/usr/bin/env python
"""备份业务数据（SQLite 用官方 backup API，热备份不锁库）。

    python scripts/backup_data.py                 # 备份到 data/backups/
    python scripts/backup_data.py --keep 14       # 只保留最近 14 份
    python scripts/backup_data.py --out /Volumes/x/pa-backups

为什么不用 cp：SQLite 在 WAL 模式下直接复制文件可能拿到不一致的状态。
``sqlite3.Connection.backup`` 会拿到一致快照。

建议：cron 每天跑一次，并把备份目录同步到别处（对象存储 / 网盘）。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"
SKIP_DIRS = {"backups"}


def _sqlite_files(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.glob("*.db") if p.is_file())


def backup(data_dir: Path, out_dir: Path, keep: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stage = out_dir / f".tmp-{stamp}"
    stage.mkdir()
    try:
        for db_path in _sqlite_files(data_dir):
            target = stage / db_path.name
            source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)      # 一致快照，无需停服
            finally:
                dest.close()
                source.close()
        # 小文件（密钥派生、用量计数）直接拷
        for extra in ("travel_usage.json", "bocha_usage.json", ".harness_id_key"):
            path = data_dir / extra
            if path.exists():
                shutil.copy2(path, stage / extra)
        archive = out_dir / f"personal-agent-{stamp}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(stage, arcname=f"personal-agent-{stamp}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    _prune(out_dir, keep)
    return archive


def _prune(out_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    archives = sorted(out_dir.glob("personal-agent-*.tar.gz"))
    for old in archives[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="备份 data/ 目录")
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--out", default="")
    ap.add_argument("--keep", type=int, default=7, help="保留最近几份（0=不清理）")
    args = ap.parse_args(argv)

    data_dir = Path(args.data)
    if not data_dir.exists():
        print(f"数据目录不存在：{data_dir}")
        return 2
    out_dir = Path(args.out) if args.out else data_dir / "backups"
    if args.out and out_dir.resolve() == data_dir.resolve():
        print("备份目录不能就是数据目录")
        return 2

    archive = backup(data_dir, out_dir, args.keep)
    size_mb = archive.stat().st_size / 1e6
    print(f"已备份：{archive}（{size_mb:.1f} MB）")
    restored = "恢复方法：停服 → 解包 → 把 *.db 放回 DATA_DIR → 启动"
    print(restored)
    return 0


if __name__ == "__main__":
    sys.exit(main())
