"""clipbench — batch evaluation for clipagent."""

from .case import Case, Check, check_constraints, load_cases
from .metrics import CaseRun, compare, summarize
from .report import render_comparison, render_markdown, write_json, write_markdown
from .runner import Runner

__all__ = ['Case', 'Check', 'check_constraints', 'load_cases', 'CaseRun',
           'compare', 'summarize', 'render_comparison', 'render_markdown',
           'write_json', 'write_markdown', 'Runner']
__version__ = '0.1.0'
