# Design: CLA Pre-Signing Enhancement

## Problem

give-back already detects CLA requirements (`conventions/cla.py` returns a
boolean), but the user experience stops at "CLA required — check
CONTRIBUTING.md for the signing link." Users still get surprised by the CLA
shame-bot after pushing their PR because:

1. The warning is generic (doesn't say *which* CLA system or *where* to sign)
2. There's no proactive offer to open the signing URL during `prepare`
3. The `check` guardrail is WARN severity, easily overlooked

The fix: identify the CLA system, extract or derive the signing URL, surface
it early during `prepare`, offer to open it, and gate on it during `check`.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Detection timing | During `conventions` (already happens) | No workflow change needed |
| User-facing timing | Advisory in `prepare`, gate in `check` | See it early, can't forget it |
| Automation level | Detect + offer to open URL | Can't sign FOR them (legal), but one click away |
| Guardrail severity | Upgrade from WARN to BLOCK | User asked for a gate, not a suggestion |

## CLA System → URL Mapping

| System | Detection signal | URL derivation |
|--------|-----------------|---------------|
| CLA Assistant | `.clabot`, CI pattern `cla-assistant`, bot login `CLAassistant` | Deterministic: `https://cla-assistant.io/{owner}/{repo}` |
| EasyCLA | CI pattern `easycla`, bot login `linux-foundation-easycla` | From bot PR comment (contains signing link) or generic: `https://easycla.lfx.linuxfoundation.org/` |
| Google CLA | CI pattern `google-cla`, bot login `googlebot`/`google-cla` | Generic: `https://cla.developers.google.com/` |
| Apache ICLA | CONTRIBUTING.md contains "ICLA" or "apache.org/licenses" | `https://www.apache.org/licenses/contributor-agreements.html` |
| DCO | `dco_required` already detected separately | No URL — just `git commit -s` (already handled by DCO guardrail) |
| Unknown/other | CLA detected but system unidentified | Generic message: "Check CONTRIBUTING.md for signing instructions" |

## Data Model

### New: `CLAInfo` dataclass (`conventions/models.py`)

```python
@dataclass
class CLAInfo:
    """CLA system metadata — what to sign and where."""

    required: bool = False
    system: str = "unknown"
    """One of: 'cla-assistant', 'easycla', 'google', 'apache', 'dco', 'unknown'"""
    signing_url: str | None = None
    """Direct URL to sign the CLA, or None if not derivable."""
    detection_source: str = ""
    """How we detected it: 'config-file', 'ci-workflow', 'pr-comment'"""
```

### Change: `ContributionBrief`

Replace `cla_required: bool = False` with:
```python
cla_info: CLAInfo = field(default_factory=CLAInfo)
```

Backward compat: `brief.cla_required` becomes a property:
```python
@property
def cla_required(self) -> bool:
    return self.cla_info.required
```

This preserves all existing call sites (`guardrails.py`, `brief_writer.py`,
`context.json`) without changing their interface.

## Changes

### 1. `conventions/cla.py` — return `CLAInfo` instead of `bool`

Rename `detect_cla()` → keep signature compatible but return `CLAInfo`:

```python
def detect_cla(
    clone_dir: Path,
    client: GitHubClient | None = None,
    owner: str | None = None,
    repo: str | None = None,
) -> CLAInfo:
```

The three existing detection steps (`_check_cla_files`, `_check_ci_for_cla`,
`_check_pr_comments_for_cla`) already return the detection source as a
string. Enhance them to also identify the *system*:

- If CI pattern contains "cla-assistant" or "cla_assistant" → system = "cla-assistant"
- If CI pattern contains "easycla" → system = "easycla"
- If CI pattern contains "google-cla" → system = "google"
- If bot login is "CLAassistant" → system = "cla-assistant"
- If bot login is "linux-foundation-easycla" → system = "easycla"
- If bot login is "googlebot" or "google-cla" → system = "google"

Then derive `signing_url` from the system + owner/repo (see mapping table).

For EasyCLA: if detected via PR comment, try to extract the signing URL from
the bot's comment body (EasyCLA bots include a `https://...` link). Fall back
to generic LFX URL.

### 2. `conventions/brief.py` — store `CLAInfo`

```python
brief.cla_info = detect_cla(clone_dir, client=client, owner=owner, repo=repo)
```

### 3. `prepare/brief_writer.py` — surface URL in brief

In `_generate_notes()`, replace the generic CLA note with:
```python
if brief.cla_required:
    if brief.cla_info.signing_url:
        notes.append(
            f"CLA required ({brief.cla_info.system}) — sign at: {brief.cla_info.signing_url}"
        )
    else:
        notes.append(
            "CLA required — check CONTRIBUTING.md for the signing link"
        )
```

In `_build_context()` JSON output, add:
```python
"cla_system": brief.cla_info.system,
"cla_signing_url": brief.cla_info.signing_url,
```

### 4. `guardrails.py` — upgrade severity + include URL

```python
def check_cla_signed(cla_info: CLAInfo) -> GuardrailResult:
    if not cla_info.required:
        return GuardrailResult(name="cla_signed", severity=Severity.INFO, passed=True, ...)

    msg = "This project requires a CLA."
    if cla_info.signing_url:
        msg += f" Sign at: {cla_info.signing_url}"
    else:
        msg += " Check CONTRIBUTING.md for the signing link."
    msg += " The CLA bot will block your PR until this is done."

    return GuardrailResult(
        name="cla_signed",
        severity=Severity.BLOCK,  # upgraded from WARN
        passed=False,
        message=msg,
    )
```

### 5. `skill/SKILL.md` — offer to open URL during prepare

Add to Step 5 (Prepare workspace), after "Tell the user":

```
5. If the brief mentions a CLA signing URL, offer: "This project requires
   a CLA. Want me to open the signing page?" If yes, run
   `open <cla_signing_url>` (macOS) or provide the URL for manual opening.
```

### 6. `cli/check.py` — pass CLAInfo to guardrail

Update the `check_cla_signed` call to pass `cla_info` instead of `cla_required`:
```python
results.append(check_cla_signed(context.get("cla_info", CLAInfo())))
```

This requires the context.json to store enough info to reconstruct CLAInfo,
or the guardrail reads it from the brief directly.

**Simpler approach:** `check` already reads `context.json`. Store
`cla_required`, `cla_system`, and `cla_signing_url` as flat fields (already
planned in step 3). Reconstruct CLAInfo from those in `check`:
```python
cla_info = CLAInfo(
    required=context.get("cla_required", False),
    system=context.get("cla_system", "unknown"),
    signing_url=context.get("cla_signing_url"),
)
results.append(check_cla_signed(cla_info))
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| CLA detected but system unknown | Generic message, no URL, still BLOCK severity |
| EasyCLA without extractable URL | Fall back to generic LFX URL |
| DCO (already handled separately) | `cla_info.system = "dco"`, no signing_url (DCO uses `--signoff`) |
| No CLA detected | `cla_info.required = False`, guardrail passes as INFO |
| User already signed CLA | Still shows BLOCK — we can't verify externally. User uses `--skip-guardrail cla_signed` or confirms |

## Guardrail Override

The BLOCK severity means `check` will fail. The user needs a way to say
"I already signed it." Options:

1. `give-back check --skip cla_signed` — explicit override per guardrail name
2. `give-back check --cla-signed` — dedicated flag
3. Store a "CLA acknowledged" marker in `.give-back/context.json`

Recommend option 3: after `prepare` offers to open the signing URL and the
user confirms they signed, write `"cla_acknowledged": true` to context.json.
The guardrail checks this field and passes if set.

## Files Changed

| File | Change |
|------|--------|
| `src/give_back/conventions/models.py` | Add `CLAInfo` dataclass, `cla_info` field on `ContributionBrief`, `cla_required` property |
| `src/give_back/conventions/cla.py` | Return `CLAInfo` with system + URL, enhance pattern matching |
| `src/give_back/conventions/brief.py` | Store `CLAInfo` instead of bool |
| `src/give_back/prepare/brief_writer.py` | Surface system + URL in notes and context.json |
| `src/give_back/guardrails.py` | `check_cla_signed` takes `CLAInfo`, severity → BLOCK, includes URL |
| `src/give_back/cli/check.py` | Reconstruct `CLAInfo` from context.json, pass to guardrail |
| `src/give_back/skill/SKILL.md` | Offer to open signing URL in Step 5 |
| `tests/conventions/test_cla.py` | New: test system identification + URL derivation |
| `tests/test_guardrails.py` | Update: test BLOCK severity + URL in message |

## Not In Scope

- **Verifying CLA was actually signed** (would require polling external services)
- **Auto-signing** (legal concern — user must click through themselves)
- **GitHub App detection** (requires additional API permissions)
- **CLA system registration/config** (no user-side config needed)
