"""Policy functions for the supervision subsystem."""

from __future__ import annotations

from bridge.supervision.model import InspectionResult, SupervisionPlan


def should_escalate(
    inspection_result: InspectionResult, plan: SupervisionPlan
) -> bool:
    """Determine if an inspection result warrants escalating to Architect.

    Escalate when:
    - The inspector explicitly flags an alert.
    - No progress has been detected for 2 or more consecutive inspections.
    - The same error signature has recurred 3 or more times.
    """
    if inspection_result.alert:
        return True
    if plan.no_progress_count >= 2:
        return True
    if plan.repeated_error_count >= 3:
        return True
    return False


def classify_completion(deliverables: dict) -> str:
    """Classify a completed task.

    Returns one of: REVIEW_REQUIRED, ASSISTANCE_REQUIRED, FAILED.

    - FAILED: no deliverables at all, or missing result/tests.
    - ASSISTANCE_REQUIRED: has an assistance request or blocker.
    - REVIEW_REQUIRED: has result and tests, no assistance/blocker.
    """
    if not deliverables:
        return "FAILED"

    has_result = bool(
        deliverables.get("result")
        or deliverables.get("RESULT.md")
        or deliverables.get("diff")
    )
    has_tests = bool(
        deliverables.get("tests")
        or deliverables.get("TESTS.md")
        or deliverables.get("testResult")
    )
    has_assistance = bool(
        deliverables.get("assistance")
        or deliverables.get("ASSISTANCE_REQUEST.md")
    )
    has_blocker = bool(
        deliverables.get("blocker")
        or deliverables.get("BLOCKER.md")
    )

    if has_assistance or has_blocker:
        return "ASSISTANCE_REQUIRED"
    if not has_result or not has_tests:
        return "FAILED"
    return "REVIEW_REQUIRED"
