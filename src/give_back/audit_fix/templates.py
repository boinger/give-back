"""Template content for community health files and write utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Code of Conduct — Contributor Covenant v2.1
# ---------------------------------------------------------------------------

CODE_OF_CONDUCT = """\
# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our \
community a harassment-free experience for everyone, regardless of age, body \
size, visible or invisible disability, ethnicity, sex characteristics, gender \
identity and expression, level of experience, education, socio-economic status, \
nationality, personal appearance, race, caste, color, religion, or sexual \
identity and orientation.

We pledge to act and interact in ways that contribute to an open, welcoming, \
diverse, inclusive, and healthy community.

## Our Standards

Examples of behavior that contributes to a positive environment for our \
community include:

* Demonstrating empathy and kindness toward other people
* Being respectful of differing opinions, viewpoints, and experiences
* Giving and gracefully accepting constructive feedback
* Accepting responsibility and apologizing to those affected by our mistakes, \
and learning from the experience
* Focusing on what is best not just for us as individuals, but for the overall \
community

Examples of unacceptable behavior include:

* The use of sexualized language or imagery, and sexual attention or advances \
of any kind
* Trolling, insulting or derogatory comments, and personal or political attacks
* Public or private harassment
* Publishing others' private information, such as a physical or email address, \
without their explicit permission
* Other conduct which could reasonably be considered inappropriate in a \
professional setting

## Enforcement Responsibilities

Community leaders are responsible for clarifying and enforcing our standards of \
acceptable behavior and will take appropriate and fair corrective action in \
response to any behavior that they deem inappropriate, threatening, offensive, \
or harmful.

Community leaders have the right and responsibility to remove, edit, or reject \
comments, commits, code, wiki edits, issues, and other contributions that are \
not aligned to this Code of Conduct, and will communicate reasons for moderation \
decisions when appropriate.

## Scope

This Code of Conduct applies within all community spaces, and also applies when \
an individual is officially representing the community in public spaces. Examples \
of representing our community include using an official e-mail address, posting \
via an official social media account, or acting as an appointed representative \
at an online or offline event.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be \
reported to the community leaders responsible for enforcement at \
[https://github.com/{owner}/{repo}/issues](https://github.com/{owner}/{repo}/issues). \
All complaints will be reviewed and investigated promptly and fairly.

All community leaders are obligated to respect the privacy and security of the \
reporter of any incident.

## Enforcement Guidelines

Community leaders will follow these Community Impact Guidelines in determining \
the consequences for any action they deem in violation of this Code of Conduct:

### 1. Correction

**Community Impact**: Use of inappropriate language or other behavior deemed \
unprofessional or unwelcome in the community.

**Consequence**: A private, written warning from community leaders, providing \
clarity around the nature of the violation and an explanation of why the \
behavior was inappropriate. A public apology may be requested.

### 2. Warning

**Community Impact**: A violation through a single incident or series of actions.

**Consequence**: A warning with consequences for continued behavior. No \
interaction with the people involved, including unsolicited interaction with \
those enforcing the Code of Conduct, for a specified period of time. This \
includes avoiding interactions in community spaces as well as external channels \
like social media. Violating these terms may lead to a temporary or permanent ban.

### 3. Temporary Ban

**Community Impact**: A serious violation of community standards, including \
sustained inappropriate behavior.

**Consequence**: A temporary ban from any sort of interaction or public \
communication with the community for a specified period of time. No public or \
private interaction with the people involved, including unsolicited interaction \
with those enforcing the Code of Conduct, is allowed during this period. \
Violating these terms may lead to a permanent ban.

### 4. Permanent Ban

**Community Impact**: Demonstrating a pattern of violation of community \
standards, including sustained inappropriate behavior, harassment of an \
individual, or aggression toward or disparagement of classes of individuals.

**Consequence**: A permanent ban from any sort of public interaction within \
the community.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant][homepage], \
version 2.1, available at \
[https://www.contributor-covenant.org/version/2/1/code_of_conduct.html][v2.1].

Community Impact Guidelines were inspired by \
[Mozilla's code of conduct enforcement ladder][Mozilla CoC].

For answers to common questions about this code of conduct, see the FAQ at \
[https://www.contributor-covenant.org/faq][FAQ]. Translations are available at \
[https://www.contributor-covenant.org/translations][translations].

[homepage]: https://www.contributor-covenant.org
[v2.1]: https://www.contributor-covenant.org/version/2/1/code_of_conduct.html
[Mozilla CoC]: https://github.com/mozilla/diversity
[FAQ]: https://www.contributor-covenant.org/faq
[translations]: https://www.contributor-covenant.org/translations
"""

# ---------------------------------------------------------------------------
# Security policy
# ---------------------------------------------------------------------------

SECURITY = """\
# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's private vulnerability reporting:

https://github.com/{owner}/{repo}/security/advisories/new

Do not open a public issue for security vulnerabilities.
"""

# ---------------------------------------------------------------------------
# PR template
# ---------------------------------------------------------------------------

PR_TEMPLATE = """\
## Summary

<!-- What does this PR do and why? -->

## Test plan

<!-- How did you verify this works? -->

## Checklist

- [ ] Tests pass
- [ ] Tests added or updated for changed behavior
- [ ] Documentation updated if needed
"""

# ---------------------------------------------------------------------------
# Issue templates (YAML forms)
# ---------------------------------------------------------------------------

BUG_REPORT_YML = """\
name: Bug report
description: Something isn't working as expected
labels: ["bug"]
body:
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: What did you expect to happen, and what happened instead?
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      description: The exact steps to trigger the problem.
      placeholder: |
        1. Run '...'
        2. ...
    validations:
      required: true
  - type: textarea
    id: output
    attributes:
      label: Output
      description: Paste the full terminal output if applicable.
      render: shell
  - type: input
    id: version
    attributes:
      label: Version
      description: What version are you using?
    validations:
      required: true
  - type: dropdown
    id: os
    attributes:
      label: Operating system
      options:
        - macOS
        - Linux
        - Windows
        - Other
"""

FEATURE_REQUEST_YML = """\
name: Feature request
description: Suggest an improvement or new capability
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
      description: Describe the use case.
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
      description: How would you like this to work?
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
      description: Have you tried any workarounds?
"""

CONFIG_YML = """\
blank_issues_enabled: true
"""


# ---------------------------------------------------------------------------
# File writing utility
# ---------------------------------------------------------------------------


def preview_content(content: str, label: str, max_lines: int = 30) -> None:
    """Display a preview of file content."""
    lines = content.splitlines()
    click.echo(f"\n  ── {label} ──")
    for line in lines[:max_lines]:
        click.echo(f"  │ {line}")
    if len(lines) > max_lines:
        click.echo(f"  │ ... ({len(lines) - max_lines} more lines)")
    click.echo()


def confirm_with_preview(content: str, label: str) -> bool:
    """Ask user to write, preview, or skip a generated file. Returns True to write."""
    while True:
        choice = click.prompt(
            f"  {label}: [w]rite / [p]review / [s]kip",
            type=click.Choice(["w", "p", "s"], case_sensitive=False),
            default="w",
            show_choices=False,
        )
        if choice == "p":
            preview_content(content, label)
            continue
        return choice == "w"


def write_file(path: Path, content: str) -> None:
    """Write *content* to *path* atomically. Creates parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    # Catch BaseException intentionally: the cleanup-and-reraise pattern must
    # handle KeyboardInterrupt between mkstemp and replace, otherwise Ctrl+C
    # leaves a stray .tmp file. See CLAUDE.md "No catch-all exceptions" carve-out.
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def write_if_missing(path: Path, content: str, label: str) -> bool:
    """Write *content* to *path* if it doesn't exist, with interactive confirmation.

    Creates parent directories as needed. Returns True if the file was written.
    """
    if path.exists():
        click.echo(f"  Already exists: {label} — skipping")
        return False

    if not click.confirm(f"  Create {label}?", default=True):
        return False

    # Re-check after user interaction (race guard)
    if path.exists():
        click.echo(f"  Already exists: {label} — skipping")
        return False

    write_file(path, content)
    return True
