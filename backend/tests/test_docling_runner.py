from __future__ import annotations

import ast
import json
import sys
import threading
import time
import types
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config, docling_runner


class _FakeConversionStatus(str, Enum):
    PENDING = "pending"
    FAILURE = "failure"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    SKIPPED = "skipped"


class _FakeQualityGrade(str, Enum):
    GOOD = "good"
    EXCELLENT = "excellent"


class _FakeComponentType(str, Enum):
    PIPELINE = "pipeline"
    MODEL = "model"


class _FakeFailureCategory(str, Enum):
    TIMEOUT = "timeout"
    INFERENCE_FAILURE = "inference_failure"


@pytest.fixture(autouse=True)
def _clear_converter_cache():
    docling_runner._converter_cache.clear()
    yield
    docling_runner._converter_cache.clear()


def _fake_result(
    *,
    status=_FakeConversionStatus.SUCCESS,
    errors=None,
    pages=None,
    mean_grade=_FakeQualityGrade.GOOD,
    clusters=None,
):
    if pages is None:
        pages = {"1": {"size": {"width": 612.0, "height": 792.0}}}
    document = SimpleNamespace(export_to_dict=lambda: {"pages": pages, "texts": []})
    confidence = SimpleNamespace(
        layout_score=0.92,
        mean_score=0.91,
        mean_grade=mean_grade,
        ocr_score=float("nan"),
        table_score=0.88,
        parse_score=0.95,
    )
    if clusters is None:
        clusters = [
            SimpleNamespace(
                page_no=1,
                predictions=SimpleNamespace(
                    layout=SimpleNamespace(
                        clusters=[
                            SimpleNamespace(
                                bbox=SimpleNamespace(l=10.0, t=20.0, r=100.0, b=50.0),
                                confidence=0.94,
                            )
                        ]
                    )
                ),
            )
        ]
    return SimpleNamespace(
        status=status,
        errors=errors or [],
        document=document,
        confidence=confidence,
        pages=clusters,
    )


def test_run_docling_success_serialises_grade_value_and_metadata(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result(mean_grade=_FakeQualityGrade.GOOD)
    fake_converter = SimpleNamespace(convert=lambda path: fake_res)
    monkeypatch.setattr(docling_runner, "_get_converter", lambda opts, **_kwargs: fake_converter)
    monkeypatch.setitem(sys.modules, "docling", SimpleNamespace(__version__="2.121.0"))

    # Confirm Python (str, Enum) str() differs from .value, proving regression guard.
    assert str(_FakeQualityGrade.GOOD) != "good"

    output = docling_runner.run_docling(pdf_path)

    assert output["raw_docling"]["pages"] == {
        "1": {"size": {"width": 612.0, "height": 792.0}}
    }
    assert output["cluster_confidences"] == [
        [1, {"l": 10.0, "t": 20.0, "r": 100.0, "b": 50.0}, 0.94]
    ]
    assert output["docling_version"] == "2.121.0"
    assert output["conversion_status"] == "success"
    assert output["conversion_errors"] == []
    assert output["parse_elapsed_seconds"] >= 0.0
    assert output["doc_confidence"]["mean_grade"] == "good"
    assert output["doc_confidence"]["conversion_status"] == "success"
    assert output["doc_confidence"]["error_count"] == 0
    assert output["doc_confidence"]["failed_pages"] == []


def test_run_docling_partial_success_surfaces_errors_and_failed_pages(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "partial.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    errors = [
        SimpleNamespace(
            component_type=_FakeComponentType.MODEL,
            module_name="tableformer",
            error_message="page 3 table inference timed out",
            category=_FakeFailureCategory.TIMEOUT,
            page_no=3,
        ),
        SimpleNamespace(
            component_type=_FakeComponentType.MODEL,
            module_name="layout",
            error_message="page 1 fallback",
            category=_FakeFailureCategory.INFERENCE_FAILURE,
            page_no=1,
        ),
        SimpleNamespace(
            component_type=_FakeComponentType.PIPELINE,
            module_name="standard_pdf_pipeline",
            error_message="duplicate page 3 timeout summary",
            category=_FakeFailureCategory.TIMEOUT,
            page_no=3,
        ),
        SimpleNamespace(
            component_type=_FakeComponentType.PIPELINE,
            module_name="standard_pdf_pipeline",
            error_message="document timeout reached",
            category=_FakeFailureCategory.TIMEOUT,
            page_no=None,
        ),
    ]
    fake_res = _fake_result(
        status=_FakeConversionStatus.PARTIAL_SUCCESS,
        errors=errors,
        mean_grade=_FakeQualityGrade.EXCELLENT,
    )
    fake_converter = SimpleNamespace(convert=lambda path: fake_res)
    monkeypatch.setattr(docling_runner, "_get_converter", lambda opts, **_kwargs: fake_converter)
    monkeypatch.setitem(sys.modules, "docling", SimpleNamespace(__version__="2.121.0"))

    output = docling_runner.run_docling(pdf_path, {"do_ocr": False})

    assert output["conversion_status"] == "partial_success"
    assert output["doc_confidence"]["mean_grade"] == "excellent"
    assert output["doc_confidence"]["conversion_status"] == "partial_success"
    assert output["doc_confidence"]["error_count"] == 4
    assert output["doc_confidence"]["failed_pages"] == [1, 3]
    assert output["conversion_errors"] == [
        {
            "component_type": "model",
            "module_name": "tableformer",
            "error_message": "page 3 table inference timed out",
            "category": "timeout",
            "page_no": 3,
        },
        {
            "component_type": "model",
            "module_name": "layout",
            "error_message": "page 1 fallback",
            "category": "inference_failure",
            "page_no": 1,
        },
        {
            "component_type": "pipeline",
            "module_name": "standard_pdf_pipeline",
            "error_message": "duplicate page 3 timeout summary",
            "category": "timeout",
            "page_no": 3,
        },
        {
            "component_type": "pipeline",
            "module_name": "standard_pdf_pipeline",
            "error_message": "document timeout reached",
            "category": "timeout",
            "page_no": None,
        },
    ]


def test_run_docling_raises_on_failure_status(monkeypatch, tmp_path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    errors = [
        SimpleNamespace(
            component_type=_FakeComponentType.PIPELINE,
            module_name="pypdfium2",
            error_message="corrupt xref table",
            category=_FakeFailureCategory.INFERENCE_FAILURE,
            page_no=None,
        )
    ]
    fake_res = _fake_result(status=_FakeConversionStatus.FAILURE, errors=errors)
    fake_converter = SimpleNamespace(convert=lambda path: fake_res)
    monkeypatch.setattr(docling_runner, "_get_converter", lambda opts, **_kwargs: fake_converter)

    with pytest.raises(RuntimeError, match="failure.*corrupt xref table"):
        docling_runner.run_docling(pdf_path, {})

    skipped_res = _fake_result(status=_FakeConversionStatus.SKIPPED)
    monkeypatch.setattr(
        docling_runner,
        "_get_converter",
        lambda opts, **_kwargs: SimpleNamespace(convert=lambda path: skipped_res),
    )
    with pytest.raises(RuntimeError, match="skipped"):
        docling_runner.run_docling(pdf_path, {})


def test_run_docling_raises_on_empty_pages(monkeypatch, tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result(status=_FakeConversionStatus.SUCCESS, pages={})
    fake_converter = SimpleNamespace(convert=lambda path: fake_res)
    monkeypatch.setattr(docling_runner, "_get_converter", lambda opts, **_kwargs: fake_converter)

    with pytest.raises(RuntimeError, match="no pages"):
        docling_runner.run_docling(pdf_path, {})


def test_run_docling_cancel_check_aborts_before_convert(monkeypatch, tmp_path):
    pdf_path = tmp_path / "stopped.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    get_converter_calls = 0
    convert_calls = 0

    def fake_get_converter(opts, **_kwargs):
        nonlocal get_converter_calls
        get_converter_calls += 1
        return SimpleNamespace(
            convert=lambda path: (_ for _ in ()).throw(AssertionError("should not convert"))
        )

    monkeypatch.setattr(docling_runner, "_get_converter", fake_get_converter)

    # Cancelled before _get_converter
    with pytest.raises(InterruptedError, match="stopped"):
        docling_runner.run_docling(pdf_path, {}, cancel_check=lambda: True)
    assert get_converter_calls == 0

    # Cancelled after acquiring _lock (False on pre-check, True inside lock)
    checks = iter([False, True])

    def fake_get_converter_2(opts, **_kwargs):
        nonlocal get_converter_calls
        get_converter_calls += 1

        def _convert(path):
            nonlocal convert_calls
            convert_calls += 1
            return _fake_result()

        return SimpleNamespace(convert=_convert)

    monkeypatch.setattr(docling_runner, "_get_converter", fake_get_converter_2)
    with pytest.raises(InterruptedError, match="stopped"):
        docling_runner.run_docling(pdf_path, {}, cancel_check=lambda: next(checks))
    assert get_converter_calls == 1
    assert convert_calls == 0


def test_run_docling_parse_elapsed_excludes_lock_wait(monkeypatch, tmp_path):
    pdf_path = tmp_path / "queued.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result()

    def fast_convert(path):
        time.sleep(0.005)
        return fake_res

    monkeypatch.setattr(
        docling_runner,
        "_get_converter",
        lambda opts, **_kwargs: SimpleNamespace(convert=fast_convert),
    )
    monkeypatch.setitem(sys.modules, "docling", SimpleNamespace(__version__="2.121.0"))

    lock_acquired = threading.Event()

    def hold_lock():
        with docling_runner._lock:
            lock_acquired.set()
            time.sleep(0.08)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_acquired.wait(timeout=2.0)

    wall_start = time.monotonic()
    output = docling_runner.run_docling(pdf_path, {})
    wall_elapsed = time.monotonic() - wall_start
    holder.join(timeout=2.0)

    assert wall_elapsed >= 0.07
    assert 0.0 <= output["parse_elapsed_seconds"] < 0.05


def _install_docling_stubs(monkeypatch):
    """Install lightweight offline docling stubs into sys.modules."""
    docling_pkg = types.ModuleType("docling")
    docling_pkg.__version__ = "2.121.0"

    datamodel_pkg = types.ModuleType("docling.datamodel")
    settings_mod = types.ModuleType("docling.datamodel.settings")
    settings_mod.settings = SimpleNamespace(inference=SimpleNamespace(compile_torch_models=True))

    backend_pkg = types.ModuleType("docling.backend")
    pypdfium_mod = types.ModuleType("docling.backend.pypdfium2_backend")

    class FakePyPdfiumBackend:
        pass

    pypdfium_mod.PyPdfiumDocumentBackend = FakePyPdfiumBackend

    accel_mod = types.ModuleType("docling.datamodel.accelerator_options")

    class FakeAcceleratorDevice(str, Enum):
        AUTO = "auto"
        CPU = "cpu"
        CUDA = "cuda"
        MPS = "mps"
        XPU = "xpu"

    class FakeAcceleratorOptions:
        def __init__(self, *, device):
            self.device = device

    accel_mod.AcceleratorDevice = FakeAcceleratorDevice
    accel_mod.AcceleratorOptions = FakeAcceleratorOptions

    base_models_mod = types.ModuleType("docling.datamodel.base_models")

    class FakeInputFormat(str, Enum):
        PDF = "pdf"

    base_models_mod.InputFormat = FakeInputFormat

    pipeline_opts_mod = types.ModuleType("docling.datamodel.pipeline_options")

    class FakeTableFormerMode(str, Enum):
        FAST = "fast"
        ACCURATE = "accurate"

    class FakeTableStructureOptions:
        def __init__(self, *, do_cell_matching=True, mode=FakeTableFormerMode.ACCURATE):
            self.do_cell_matching = do_cell_matching
            self.mode = mode

    class FakeHeadingHierarchyOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakePdfPipelineOptions:
        def __init__(self):
            self.do_ocr = False
            self.do_table_structure = True
            self.table_structure_options = None
            self.document_timeout = None
            self.generate_parsed_pages = False
            self.heading_hierarchy_options = None
            self.accelerator_options = None

    pipeline_opts_mod.TableFormerMode = FakeTableFormerMode
    pipeline_opts_mod.TableStructureOptions = FakeTableStructureOptions
    pipeline_opts_mod.HeadingHierarchyOptions = FakeHeadingHierarchyOptions
    pipeline_opts_mod.PdfPipelineOptions = FakePdfPipelineOptions

    converter_mod = types.ModuleType("docling.document_converter")

    class FakePdfFormatOption:
        def __init__(self, *, pipeline_options, backend):
            self.pipeline_options = pipeline_options
            self.backend = backend

    class FakeDocumentConverter:
        def __init__(self, *, format_options):
            self.format_options = format_options

    converter_mod.PdfFormatOption = FakePdfFormatOption
    converter_mod.DocumentConverter = FakeDocumentConverter

    for name, mod in {
        "docling": docling_pkg,
        "docling.datamodel": datamodel_pkg,
        "docling.datamodel.settings": settings_mod,
        "docling.backend": backend_pkg,
        "docling.backend.pypdfium2_backend": pypdfium_mod,
        "docling.datamodel.accelerator_options": accel_mod,
        "docling.datamodel.base_models": base_models_mod,
        "docling.datamodel.pipeline_options": pipeline_opts_mod,
        "docling.document_converter": converter_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return FakeTableFormerMode, FakeAcceleratorDevice


def test_build_converter_forwards_table_mode_and_document_timeout_and_caches_separately(
    monkeypatch,
):
    FakeTableFormerMode, FakeAcceleratorDevice = _install_docling_stubs(monkeypatch)
    InputFormat = sys.modules["docling.datamodel.base_models"].InputFormat

    c_default = docling_runner._get_converter(
        {"do_ocr": False, "do_table_structure": True, "device": "cpu"}
    )
    opts_default = c_default.format_options[InputFormat.PDF].pipeline_options
    assert opts_default.table_structure_options.do_cell_matching is True
    assert opts_default.table_structure_options.mode == FakeTableFormerMode.ACCURATE
    assert opts_default.document_timeout is None
    assert opts_default.accelerator_options.device == FakeAcceleratorDevice.CPU

    # Identical effective options hit cache.
    c_default_again = docling_runner._get_converter(
        {
            "do_ocr": False,
            "do_table_structure": True,
            "device": "CPU",
            "table_mode": "accurate",
            "document_timeout": None,
        }
    )
    assert c_default_again is c_default

    # Fast table mode + explicit timeout builds a distinct converter & cache entry.
    c_fast_timeout = docling_runner._get_converter(
        {
            "do_ocr": False,
            "do_table_structure": True,
            "device": "cuda:0",
            "table_mode": "fast",
            "document_timeout": 120.0,
        }
    )
    assert c_fast_timeout is not c_default
    opts_fast = c_fast_timeout.format_options[InputFormat.PDF].pipeline_options
    assert opts_fast.table_structure_options.do_cell_matching is True
    assert opts_fast.table_structure_options.mode == FakeTableFormerMode.FAST
    assert opts_fast.document_timeout == 120.0
    assert opts_fast.accelerator_options.device == "cuda:0"

    # Different timeout alone also produces a distinct cache entry.
    c_other_timeout = docling_runner._get_converter(
        {
            "do_ocr": False,
            "do_table_structure": True,
            "device": "cuda:0",
            "table_mode": "fast",
            "document_timeout": 240.0,
        }
    )
    assert c_other_timeout is not c_fast_timeout
    assert len(docling_runner._converter_cache) == 3


def test_run_docling_invalid_options_raise_value_error(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    for bad_mode in ("turbo", "", 123):
        with pytest.raises(ValueError, match="table_mode"):
            docling_runner.run_docling(pdf_path, {"table_mode": bad_mode})

    for bad_timeout in (0, -5.0, float("nan"), float("inf"), True, "abc", ""):
        with pytest.raises(ValueError, match="document_timeout"):
            docling_runner.run_docling(pdf_path, {"document_timeout": bad_timeout})


def test_run_docling_returns_unknown_version_when_docling_not_installed(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result()
    monkeypatch.setattr(
        docling_runner,
        "_get_converter",
        lambda opts, **_kwargs: SimpleNamespace(convert=lambda path: fake_res),
    )
    monkeypatch.setitem(sys.modules, "docling", None)

    output = docling_runner.run_docling(pdf_path)
    assert output["docling_version"] == "unknown"


def test_docling_runner_has_no_backend_app_imports():
    runner_path = Path(docling_runner.__file__).resolve()
    tree = ast.parse(runner_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("backend")
                assert not alias.name.startswith("app")
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            module = node.module or ""
            assert not module.startswith("backend")
            assert not module.startswith("app")

    # Top-level module body must not import docling eagerly.
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("docling") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("docling")


def test_config_docling_timeout_table_mode_and_remote_device(monkeypatch):
    for var in (
        "KONVERTER_DOCLING_TIMEOUT_SECONDS",
        "KONVERTER_DOCLING_TABLE_MODE",
        "KONVERTER_DOCLING_REMOTE_DEVICE",
    ):
        monkeypatch.delenv(var, raising=False)

    defaults = config.load_settings()
    assert defaults.docling_timeout_seconds == 600.0
    assert defaults.docling_table_mode == "accurate"
    assert defaults.docling_remote_device == "cuda"

    for disabled in ("none", "NONE", "", "null", "off"):
        monkeypatch.setenv("KONVERTER_DOCLING_TIMEOUT_SECONDS", disabled)
        assert config.load_settings().docling_timeout_seconds is None

    monkeypatch.setenv("KONVERTER_DOCLING_TIMEOUT_SECONDS", "120.5")
    monkeypatch.setenv("KONVERTER_DOCLING_TABLE_MODE", "FAST")
    monkeypatch.setenv("KONVERTER_DOCLING_REMOTE_DEVICE", "CUDA:1")
    custom = config.load_settings()
    assert custom.docling_timeout_seconds == 120.5
    assert custom.docling_table_mode == "fast"
    assert custom.docling_remote_device == "cuda:1"

    for invalid_timeout in ("0", "-10", "nan", "inf", "abc"):
        monkeypatch.setenv("KONVERTER_DOCLING_TIMEOUT_SECONDS", invalid_timeout)
        with pytest.raises(ValueError, match="KONVERTER_DOCLING_TIMEOUT_SECONDS"):
            config.load_settings()
    monkeypatch.delenv("KONVERTER_DOCLING_TIMEOUT_SECONDS")

    monkeypatch.setenv("KONVERTER_DOCLING_TABLE_MODE", "turbo")
    with pytest.raises(ValueError, match="KONVERTER_DOCLING_TABLE_MODE"):
        config.load_settings()
    monkeypatch.delenv("KONVERTER_DOCLING_TABLE_MODE")

    monkeypatch.setenv("KONVERTER_DOCLING_REMOTE_DEVICE", "tpu")
    with pytest.raises(ValueError, match="KONVERTER_DOCLING_REMOTE_DEVICE"):
        config.load_settings()


def test_config_docling_device_accepts_xpu_but_rejects_indexed_xpu(monkeypatch):
    for env_var, attr in (
        ("KONVERTER_DOCLING_DEVICE", "docling_device"),
        ("KONVERTER_DOCLING_REMOTE_DEVICE", "docling_remote_device"),
    ):
        monkeypatch.setenv(env_var, "XPU")
        assert getattr(config.load_settings(), attr) == "xpu"

        monkeypatch.setenv(env_var, "xpu:0")
        with pytest.raises(ValueError, match=env_var):
            config.load_settings()
        monkeypatch.delenv(env_var, raising=False)


def test_run_docling_normalizes_non_finite_confidence_scores_for_strict_json(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "nan_scores.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result(
        status=_FakeConversionStatus.PARTIAL_SUCCESS,
        clusters=[
            SimpleNamespace(
                page_no=1,
                predictions=SimpleNamespace(
                    layout=SimpleNamespace(
                        clusters=[
                            SimpleNamespace(
                                bbox=SimpleNamespace(l=1.0, t=2.0, r=3.0, b=4.0),
                                confidence=float("nan"),
                            ),
                            SimpleNamespace(
                                bbox=SimpleNamespace(l=5.0, t=6.0, r=7.0, b=8.0),
                                confidence=0.87,
                            ),
                        ]
                    )
                ),
            )
        ],
    )
    fake_res.confidence = SimpleNamespace(
        layout_score=float("nan"),
        mean_score=float("-inf"),
        mean_grade=_FakeQualityGrade.GOOD,
        ocr_score=float("nan"),
        table_score=float("inf"),
        parse_score=True,
    )
    monkeypatch.setattr(
        docling_runner,
        "_get_converter",
        lambda opts, **_kwargs: SimpleNamespace(convert=lambda path: fake_res),
    )
    monkeypatch.setitem(sys.modules, "docling", SimpleNamespace(__version__="2.121.0"))

    output = docling_runner.run_docling(pdf_path, {"do_ocr": False})

    assert output["doc_confidence"] == {
        "layout_score": None,
        "mean_score": None,
        "mean_grade": "good",
        "ocr_score": None,
        "table_score": None,
        "parse_score": None,
        "conversion_status": "partial_success",
        "error_count": 0,
        "failed_pages": [],
    }
    assert output["cluster_confidences"] == [
        [1, {"l": 1.0, "t": 2.0, "r": 3.0, "b": 4.0}, None],
        [1, {"l": 5.0, "t": 6.0, "r": 7.0, "b": 8.0}, 0.87],
    ]
    serialized = json.dumps(output, allow_nan=False)
    assert '"ocr_score": null' in serialized


def test_run_docling_raises_runtime_error_when_document_is_none(monkeypatch, tmp_path):
    pdf_path = tmp_path / "none_doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    fake_res = _fake_result(status=_FakeConversionStatus.PARTIAL_SUCCESS)
    fake_res.document = None
    monkeypatch.setattr(
        docling_runner,
        "_get_converter",
        lambda opts, **_kwargs: SimpleNamespace(convert=lambda path: fake_res),
    )

    with pytest.raises(RuntimeError, match="no pages"):
        docling_runner.run_docling(pdf_path, {})


def test_get_converter_uncached_cancel_check_aborts_before_build_converter(
    monkeypatch, tmp_path
):
    pdf_path = tmp_path / "uncached_cancel.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    build_calls = 0

    def fake_build_converter(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        raise AssertionError("_build_converter should not be called after cancel")

    monkeypatch.setattr(docling_runner, "_build_converter", fake_build_converter)

    cancelled = False
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock():
        with docling_runner._lock:
            lock_held.set()
            release_lock.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_held.wait(timeout=2.0)

    errors: list[BaseException] = []

    def run_worker():
        try:
            docling_runner.run_docling(
                pdf_path,
                {"do_ocr": False, "do_table_structure": True, "device": "cpu"},
                cancel_check=lambda: cancelled,
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run_worker)
    worker.start()

    # Wait briefly so worker passes the pre-lock check and blocks on _get_converter's _lock.
    time.sleep(0.05)
    cancelled = True
    release_lock.set()

    worker.join(timeout=2.0)
    holder.join(timeout=2.0)

    assert len(errors) == 1
    assert isinstance(errors[0], InterruptedError)
    assert build_calls == 0
    assert docling_runner._converter_cache == {}
