"""Shared rich console instances.

stderr_console: for status messages, warnings, progress bars (never captured by pipes).
stdout_console: for command output (tables, JSON) — lives in output/_shared.py.
"""

from rich.console import Console

stderr_console = Console(stderr=True)
