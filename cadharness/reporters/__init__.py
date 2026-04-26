"""Reporters for the v0.6 unified `Report` shape: text / markdown / json."""
from .text import render_text
from .markdown import render_markdown
from .json_writer import render_json

__all__ = ["render_text", "render_markdown", "render_json"]
