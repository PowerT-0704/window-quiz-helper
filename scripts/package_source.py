"""Create a source archive from an explicit allowlist, never from the whole tree."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quiz_helper import __version__
DOCUMENTS = (
    "main.py", "README.md", "ROADMAP.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
    "DELIVERY.md",
    "requirements.txt", "requirements-build.txt", ".gitignore", ".gitattributes",
)
DIRECTORIES = {
    "quiz_helper": {".py", ".ico"},
    "tests": {".py"},
    "scripts": {".py", ".ps1"},
    "LICENSES": {".txt", ".md", ".html"},
    "docs": {".md", ".png"},
}


def source_files() -> list[Path]:
    files = [
        ROOT / name for name in DOCUMENTS
        if (ROOT / name).is_file()
        and not (ROOT / name).is_symlink()
        and (ROOT / name).resolve().is_relative_to(ROOT)
    ]
    for directory, suffixes in DIRECTORIES.items():
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in suffixes:
                if "__pycache__" not in path.parts and path.resolve().is_relative_to(ROOT):
                    files.append(path)
    return sorted(set(files))


def package(output: Path) -> tuple[int, int]:
    output = output.resolve()
    if not output.is_relative_to((ROOT / "dist").resolve()) or output.suffix.lower() != ".zip":
        raise ValueError("源码包输出必须为项目 dist 目录内的 ZIP 文件。")
    if output.drive.upper() == "C:":
        raise ValueError("源码包必须输出到非 C 盘。")
    files = source_files()
    if not (ROOT / "main.py").is_file():
        raise ValueError("main.py 尚未准备好，不能打包源码。")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname=Path("题目查询助手-source") / path.relative_to(ROOT))
    return len(files), output.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="按白名单生成不含运行数据的源码包。")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"题目查询助手-source-v{__version__}.zip")
    arguments = parser.parse_args()
    try:
        count, size = package(arguments.output)
    except (OSError, ValueError) as exc:
        print(f"源码打包失败：{exc}", file=sys.stderr)
        return 1
    print(f"源码包：{arguments.output.resolve()}（{count} 个文件，{size:,} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
