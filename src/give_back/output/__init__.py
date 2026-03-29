"""Terminal output formatting for give-back.

Split by command group for maintainability. All public functions are
re-exported here so existing ``from give_back.output import X`` still works.
"""

from give_back.output._shared import _console, _extract_signal_detail
from give_back.output.assess import print_assessment, print_assessment_json, print_cached_notice
from give_back.output.audit import print_audit, print_audit_comparison, print_audit_json
from give_back.output.calibration import print_calibration
from give_back.output.check import print_check_results, print_prepare_json
from give_back.output.conventions import print_conventions, print_conventions_json
from give_back.output.deps import print_deps, print_deps_json
from give_back.output.discover import print_discover, print_discover_json
from give_back.output.sniff import print_sniff, print_sniff_json
from give_back.output.status import print_status, print_status_json
from give_back.output.submit import print_submit_json, print_submit_success
from give_back.output.triage import print_triage, print_triage_json

__all__ = [
    "_console",
    "_extract_signal_detail",
    "print_assessment",
    "print_assessment_json",
    "print_audit",
    "print_audit_comparison",
    "print_audit_json",
    "print_cached_notice",
    "print_calibration",
    "print_check_results",
    "print_conventions",
    "print_conventions_json",
    "print_deps",
    "print_deps_json",
    "print_discover",
    "print_discover_json",
    "print_prepare_json",
    "print_sniff",
    "print_sniff_json",
    "print_status",
    "print_status_json",
    "print_submit_json",
    "print_submit_success",
    "print_triage",
    "print_triage_json",
]
