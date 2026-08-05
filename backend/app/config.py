from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_threshold(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _as_docling_device(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value in {"auto", "cpu", "cuda", "mps", "xpu"}:
        return value
    if re.fullmatch(r"(?:cuda|xpu):\d+", value):
        return value
    raise ValueError(f"{name} must be auto, cpu, cuda, mps, xpu, cuda:N or xpu:N")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cors_origins: tuple[str, ...]
    do_ocr: bool
    do_table_structure: bool
    docling_device: str
    rule_based_headings: bool
    worker_count: int
    max_pages: int
    high_confidence_threshold: float
    medium_confidence_threshold: float
    baseline_seconds_per_page: float
    baseline_startup_seconds: float
    site_url: str
    site_name: str
    page_url_template: str
    public_api_url: str
    default_license_url: str
    default_copyright_holder: str
    description_max_chars: int
    log_level: str


def load_settings() -> Settings:
    default_data = Path(__file__).resolve().parents[1] / "runtime"
    origins = os.getenv("KONVERTER_CORS_ORIGINS", "http://localhost:5173")
    high_threshold = _as_threshold("KONVERTER_HIGH_CONFIDENCE", 0.75)
    medium_threshold = _as_threshold("KONVERTER_MEDIUM_CONFIDENCE", 0.55)
    if medium_threshold >= high_threshold:
        raise ValueError(
            "KONVERTER_MEDIUM_CONFIDENCE must be lower than KONVERTER_HIGH_CONFIDENCE"
        )
    return Settings(
        data_dir=Path(os.getenv("KONVERTER_DATA_DIR", default_data)).resolve(),
        cors_origins=tuple(
            value.strip() for value in origins.split(",") if value.strip()
        ),
        do_ocr=_as_bool("KONVERTER_DO_OCR", False),
        do_table_structure=_as_bool("KONVERTER_DO_TABLE_STRUCTURE", True),
        docling_device=_as_docling_device("KONVERTER_DOCLING_DEVICE", "cpu"),
        rule_based_headings=_as_bool("KONVERTER_RULE_BASED_HEADINGS", True),
        worker_count=max(1, int(os.getenv("KONVERTER_WORKERS", "1"))),
        max_pages=max(1, int(os.getenv("KONVERTER_MAX_PAGES", "2000"))),
        high_confidence_threshold=high_threshold,
        medium_confidence_threshold=medium_threshold,
        baseline_seconds_per_page=max(
            0.1, float(os.getenv("KONVERTER_BASELINE_SECONDS_PER_PAGE", "2.8"))
        ),
        baseline_startup_seconds=max(
            1.0, float(os.getenv("KONVERTER_BASELINE_STARTUP_SECONDS", "30"))
        ),
        site_url=os.getenv("KONVERTER_SITE_URL", "").strip().rstrip("/"),
        site_name=os.getenv("KONVERTER_SITE_NAME", "").strip(),
        page_url_template=os.getenv("KONVERTER_PAGE_URL_TEMPLATE", "").strip(),
        public_api_url=os.getenv("KONVERTER_PUBLIC_API_URL", "").strip().rstrip("/"),
        default_license_url=os.getenv(
            "KONVERTER_DEFAULT_LICENSE_URL", ""
        ).strip(),
        default_copyright_holder=os.getenv(
            "KONVERTER_DEFAULT_COPYRIGHT_HOLDER", ""
        ).strip(),
        description_max_chars=max(
            160, int(os.getenv("KONVERTER_DESCRIPTION_MAX_CHARS", "600"))
        ),
        log_level=os.getenv("KONVERTER_LOG_LEVEL", "INFO").strip().upper(),
    )
