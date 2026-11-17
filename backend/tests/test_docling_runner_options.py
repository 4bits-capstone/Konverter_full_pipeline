"""Docling's built-in heading-hierarchy stage is what restores real levels on
section headers (PDF bookmarks -> leading numbering -> visual style); the
layout model alone only says "this is a header" and leaves every heading at
level 1. These tests pin the options the pipeline asks for, and that the
builder degrades gracefully on docling versions that predate the font-style
refinement instead of failing on an unknown field.
"""

from __future__ import annotations

import pytest

from app import docling_runner


def test_documented_heading_hierarchy_options() -> None:
    kwargs = docling_runner.heading_hierarchy_option_kwargs()
    assert kwargs == {
        "enabled": True,
        "use_bookmarks": True,
        "use_numbering": True,
        "use_style": True,
        "use_font_style": True,
        "style_size_tolerance": 0.05,
        "max_level": 5,
        "bookmark_match_threshold": 0.76,
    }


def test_unsupported_options_are_dropped_for_older_docling() -> None:
    # docling 2.119 exposes the core signals but not use_font_style /
    # style_size_tolerance, which arrived in a later release.
    supported = {
        "enabled",
        "use_bookmarks",
        "use_numbering",
        "use_style",
        "numbering_schemes",
        "max_level",
        "bookmark_match_threshold",
    }
    kwargs = docling_runner.heading_hierarchy_option_kwargs(supported)
    assert "use_font_style" not in kwargs
    assert "style_size_tolerance" not in kwargs
    assert kwargs["enabled"] is True
    assert kwargs["max_level"] == 5


def test_stage_is_enabled_on_the_installed_docling() -> None:
    pytest.importorskip("docling")
    from docling.datamodel.pipeline_options import HeadingHierarchyOptions

    options = docling_runner.heading_hierarchy_options(HeadingHierarchyOptions)

    assert options.enabled is True
    assert options.use_bookmarks is True
    assert options.use_numbering is True
    assert options.use_style is True
    assert options.max_level == 5
    assert options.bookmark_match_threshold == 0.76
    if "use_font_style" in HeadingHierarchyOptions.model_fields:
        assert options.use_font_style is True
        assert options.style_size_tolerance == 0.05
