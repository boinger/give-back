"""Parse dependency manifests into package name lists.

Supports:
- go.mod (require block, skips replace directives with local paths)
- pyproject.toml (PEP 621 [project].dependencies + Poetry [tool.poetry.dependencies])
- requirements.txt (simple line-by-line, skips comments/-r/-e/URLs)
- Cargo.toml (Rust [dependencies] + [dev-dependencies] + workspace members)
- package.json (Node.js dependencies + devDependencies)
- Gemfile (Ruby gem statements)

No external dependencies — uses tomllib and json from stdlib.
"""

from __future__ import annotations

import re
import tomllib


def parse_gomod(content: str) -> list[str]:
    """Parse go.mod content and return a list of module paths.

    Extracts from `require` blocks and single-line `require` statements.
    Skips local replace directives.
    """
    # Collect replaced modules pointing to local paths so we can skip them
    local_replaces: set[str] = set()
    for m in re.finditer(r"replace\s+(\S+)\s+=>\s+(\S+)", content):
        target = m.group(2)
        if target.startswith(".") or target.startswith("/"):
            local_replaces.add(m.group(1))

    modules: list[str] = []

    # Multi-line require blocks: require ( ... )
    for block_match in re.finditer(r"require\s*\((.*?)\)", content, re.DOTALL):
        block = block_match.group(1)
        for line in block.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                mod_path = parts[0]
                if mod_path not in local_replaces:
                    modules.append(mod_path)

    # Single-line require: require module/path vX.Y.Z (not require ( ... ) blocks)
    for m in re.finditer(r"^require\s+(?!\()(\S+)\s+\S+", content, re.MULTILINE):
        mod_path = m.group(1)
        if mod_path not in local_replaces and mod_path not in modules:
            modules.append(mod_path)

    return modules


def parse_pyproject(content: str) -> list[str]:
    """Parse pyproject.toml content and return a list of package names.

    Supports PEP 621 ([project].dependencies) and Poetry ([tool.poetry.dependencies]).
    Strips version constraints and extras.
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    packages: list[str] = []

    # PEP 621: [project].dependencies
    pep621_deps = data.get("project", {}).get("dependencies", [])
    for dep in pep621_deps:
        name = _extract_package_name(dep)
        if name:
            packages.append(name)

    # Poetry: [tool.poetry.dependencies]
    if not packages:
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for name in poetry_deps:
            if name.lower() != "python":
                packages.append(name)

    return packages


def parse_requirements_txt(content: str) -> list[str]:
    """Parse requirements.txt content and return package names.

    Skips comments, blank lines, -r includes, -e editable installs,
    URL-based requirements, and options lines.
    """
    packages: list[str] = []

    for line in content.splitlines():
        line = line.strip()

        # Skip empty, comments, options
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Skip URL-based requirements
        if "://" in line or line.startswith("git+"):
            continue

        name = _extract_package_name(line)
        if name:
            packages.append(name)

    return packages


def parse_cargo_toml(content: str) -> list[str]:
    """Parse Cargo.toml content and return a list of crate names.

    Extracts from [dependencies], [dev-dependencies], and [build-dependencies].
    Skips path-only dependencies (local crates).
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    crates: list[str] = []

    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps = data.get(section, {})
        for name, value in deps.items():
            # Skip path-only deps (local workspace crates)
            if isinstance(value, dict) and "path" in value and "version" not in value:
                continue
            crates.append(name)

    return crates


def parse_package_json(content: str) -> list[str]:
    """Parse package.json content and return a list of npm package names.

    Extracts from dependencies and devDependencies.
    Skips local file references (file:, link:).
    """
    import json

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    packages: list[str] = []

    for section in ("dependencies", "devDependencies"):
        deps = data.get(section, {})
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            # Skip local references
            if isinstance(version, str) and (version.startswith("file:") or version.startswith("link:")):
                continue
            packages.append(name)

    return packages


def parse_gemfile(content: str) -> list[str]:
    """Parse Gemfile content and return a list of gem names.

    Extracts gem names from `gem 'name'` and `gem "name"` statements.
    Skips commented lines and gems with path: or git: options pointing to local sources.
    """
    gems: list[str] = []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Match: gem 'name' or gem "name" (with optional version/options after)
        m = re.match(r"""gem\s+['"]([^'"]+)['"]""", line)
        if not m:
            continue

        # Skip path-local gems
        if "path:" in line or "path =>" in line:
            continue

        gems.append(m.group(1))

    return gems


def _extract_package_name(dep_spec: str) -> str | None:
    """Extract the package name from a dependency specifier.

    Handles: 'package>=1.0', 'package[extra]>=1.0', 'package ==1.0', etc.
    """
    dep_spec = dep_spec.strip()
    if not dep_spec:
        return None

    # Strip extras: package[extra] → package
    name = re.split(r"[\[;><=!~\s]", dep_spec, maxsplit=1)[0]
    name = name.strip()

    if not name or not re.match(r"^[a-zA-Z0-9]", name):
        return None

    # Normalize: PEP 503 — replace hyphens/underscores/dots with hyphens
    return name
