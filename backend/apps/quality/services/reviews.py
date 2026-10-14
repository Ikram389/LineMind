"""Reviewing inspection results. Each review is a new row; raw results are never touched.

The newest review is the result's `current_review`, which is what the metrics use.
Reviews never change OEE: OEE counts what the machines physically removed (their
reject counters), and a "false reject" bottle was still removed from the line.
"""

from typing import Any

from django.db import transaction

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.organizations.models import Role
from apps.organizations.tenancy import get_membership
from apps.quality.models import DefectType, InspectionResult, QualityReview, Verdict

REVIEWING_ROLES = frozenset(
    {
        Role.QUALITY_INSPECTOR,
        Role.PRODUCTION_SUPERVISOR,
        Role.FACTORY_MANAGER,
        Role.PLATFORM_ADMIN,
    }
)


class ReviewError(ValueError):
    pass


def can_review(user: User) -> bool:
    membership = get_membership(user)
    return membership is not None and membership.role in REVIEWING_ROLES


def snapshot(review: QualityReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    corrected = review.corrected_defect_type
    return {
        "review_id": review.pk,
        "verdict": review.verdict,
        "corrected_defect_type": corrected.code if corrected else None,
        "comment": review.comment,
        "reviewed_by": review.reviewed_by.email,
    }


def review_result(
    result: InspectionResult,
    verdict: str,
    corrected_defect_type: DefectType | None,
    comment: str,
    user: User,
) -> QualityReview:
    membership = get_membership(user)
    if membership is None or membership.role not in REVIEWING_ROLES:
        raise ReviewError("Your role cannot review inspection results.")
    if verdict not in Verdict.values:
        raise ReviewError(f"Unknown verdict '{verdict}'.")
    if verdict == Verdict.RECLASSIFIED:
        if corrected_defect_type is None:
            raise ReviewError("Choose the correct defect type to reclassify.")
        if (
            corrected_defect_type.organization_id != result.line.factory.organization_id
            or not corrected_defect_type.is_active
        ):
            raise ReviewError("The defect type must be an active type of your organization.")
        if corrected_defect_type.pk == result.defect_type_id:
            raise ReviewError("That is the detected type already: confirm it instead.")
    elif corrected_defect_type is not None:
        raise ReviewError("A corrected defect type is only allowed when reclassifying.")

    with transaction.atomic():
        result = InspectionResult.objects.select_for_update().get(pk=result.pk)
        before = snapshot(result.current_review)
        review = QualityReview.objects.create(
            result=result,
            verdict=verdict,
            corrected_defect_type=corrected_defect_type
            if verdict == Verdict.RECLASSIFIED
            else None,
            comment=comment,
            reviewed_by=user,
        )
        result.current_review = review
        result.save(update_fields=["current_review", "updated_at"])
        record_audit(
            user=user,
            action="inspectionresult.reviewed",
            entity=result,
            organization=membership.organization,
            before=before,
            after=snapshot(review),
        )
    return review
