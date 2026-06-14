# -*- coding: utf-8 -*-

import json
import shutil
import time
import uuid
from pathlib import Path


class JmDownloadError(RuntimeError):
    pass


def download_album_as_pdf(album_id, work_root, max_pdf_mb=100):
    """Download one JM album and return (pdf_path, task_dir)."""
    album_id = str(album_id).strip()
    if not album_id.isdigit():
        raise JmDownloadError("JM编号格式不正确")

    try:
        from jmcomic import Feature, create_option_by_file, download_album
    except ImportError as exc:
        raise JmDownloadError("缺少 jmcomic 依赖，请重新运行 Run.bat 安装依赖") from exc

    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    task_dir = work_root / f"JM{album_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    image_dir = task_dir / "images"
    pdf_dir = task_dir / "pdf"
    image_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # JSON is valid YAML and avoids Windows path escaping problems.
    option_path = task_dir / "option.yml"
    option_data = {
        "log": True,
        "client": {
            "impl": "api",
            "retry_times": 5,
            "postman": {"meta_data": {"proxies": "system"}},
        },
        "download": {
            "cache": True,
            "image": {"decode": True, "suffix": ".jpg"},
            "threading": {"image": 10, "photo": 2},
        },
        "dir_rule": {"base_dir": str(image_dir), "rule": "Bd / Ptitle"},
    }
    option_path.write_text(json.dumps(option_data, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        option = create_option_by_file(str(option_path))
        pdf_feature = Feature.export_pdf(
            pdf_dir=str(pdf_dir),
            filename_rule="Aid",
            delete_original_file=False,
        )
        download_album(album_id, option, extra=pdf_feature)
    except Exception as exc:
        cleanup_task_dir(str(task_dir))
        raise JmDownloadError(f"JM{album_id} 下载或生成PDF失败: {exc}") from exc

    pdf_files = sorted(pdf_dir.rglob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not pdf_files:
        cleanup_task_dir(str(task_dir))
        raise JmDownloadError(f"JM{album_id} 下载完成，但没有找到生成的PDF")

    pdf_path = pdf_files[0]
    max_bytes = max(1, int(max_pdf_mb)) * 1024 * 1024
    if pdf_path.stat().st_size > max_bytes:
        size_mb = pdf_path.stat().st_size / 1024 / 1024
        cleanup_task_dir(str(task_dir))
        raise JmDownloadError(f"生成的PDF为 {size_mb:.1f}MB，超过 {max_pdf_mb}MB 限制")

    return str(pdf_path), str(task_dir)


def cleanup_task_dir(task_dir):
    if task_dir:
        shutil.rmtree(task_dir, ignore_errors=True)
