"""Use Case Library HTTP API (PRD-UC-01 §9, PRD-WF-01 build package, PRD-QA-01, PRD-HO-01)."""

from __future__ import annotations

import uuid

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.use_cases.build_package import (
    BuildPackageError,
    generate_build_package,
    serialize_build_package,
)
from dataruns.use_cases.handoff_activation import (
    HandoffActivationError,
    approve_handoff_for_activation,
    build_approve_response,
    build_confirm_response,
    build_reject_response,
    confirm_handoff_activated,
    get_handoff_for_activation,
    reject_handoff,
)
from dataruns.use_cases.handoff_package import (
    latest_handoff_for_package,
    serialize_handoff,
)
from dataruns.use_cases.handoff_stage import (
    HandoffStageError,
    stage_handoff_for_package,
)
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
    WorkflowQaResult,
)
from dataruns.use_cases.qa_result import latest_qa_result_for_package, serialize_qa_result
from dataruns.use_cases.qa_run import QaRunError, run_qa_for_package
from dataruns.use_cases.recommend import (
    build_recommendations_payload,
    build_single_recommendation_payload,
)
from dataruns.use_cases.serialize import list_catalogue_payload, serialize_pilot_detail
from tenants.auth.services import get_user_company
from tenants.models import Company, User

_UC_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)
_UC_BUILD_ROLES = (User.Role.ADMIN, User.Role.ANALYST)
# PRD-QA-01 §7.2 v1: any authenticated company member may run/read QA.
_UC_QA_ROLES = _UC_READ_ROLES
# PRD-HO-01 §5: read = Admin/Analyst/Viewer; create = Admin/Analyst.
_UC_HANDOFF_READ_ROLES = _UC_READ_ROLES
_UC_HANDOFF_CREATE_ROLES = _UC_BUILD_ROLES


# PRD-HO-02 §6.3: approve / reject / confirm locked to Admin for MVP1.
_UC_HANDOFF_ACTIVATE_ROLES = (User.Role.ADMIN,)


def _request_dict(request) -> dict:
    data = request.data if hasattr(request, "data") else {}
    return data if isinstance(data, dict) else {}


def _manifest_hash_from_body(body: dict) -> tuple[str | None, Response | None]:
    raw = body.get("manifest_hash")
    if raw is None or not str(raw).strip():
        return None, Response(
            {
                "detail": "manifest_hash is required.",
                "code": "manifest_required",
            },
            status=400,
        )
    return str(raw).strip().lower(), None


def _company_for_handoff_activate(
    request,
) -> tuple[Company | None, Response | None]:
    if request.user.role not in _UC_HANDOFF_ACTIVATE_ROLES:
        return None, Response(
            {
                "detail": "Only admins can approve, reject, or confirm handoff activation.",
                "code": "forbidden",
            },
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _company_or_error(request) -> tuple[Company | None, Response | None]:
    if request.user.role not in _UC_QA_ROLES:
        return None, Response(
            {"detail": "You do not have permission to access workflow QA."},
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _company_for_handoff_read(
    request,
) -> tuple[Company | None, Response | None]:
    if request.user.role not in _UC_HANDOFF_READ_ROLES:
        return None, Response(
            {"detail": "You do not have permission to view handoffs."},
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _company_for_handoff_create(
    request,
) -> tuple[Company | None, Response | None]:
    if request.user.role not in _UC_HANDOFF_CREATE_ROLES:
        return None, Response(
            {"detail": "You do not have permission to stage handoffs."},
            status=403,
        )
    company = get_user_company(request.user)
    if company is None:
        return None, Response(
            {"detail": "No company is associated with this account."},
            status=400,
        )
    return company, None


def _package_for_company(
    *,
    company: Company,
    package_id: str | uuid.UUID,
) -> WorkflowBuildPackage | None:
    return (
        WorkflowBuildPackage.objects.select_related("pilot", "pilot__blueprint", "company")
        .filter(pk=package_id, company=company)
        .first()
    )


def _handoff_for_company(
    *,
    company: Company,
    handoff_id: str | uuid.UUID,
) -> HandoffPackage | None:
    return (
        HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        )
        .filter(pk=handoff_id, company=company)
        .first()
    )


def _parse_optional_uuid(value):
    """
    Parse an optional UUID.

    Returns:
      - None when value is missing/blank
      - uuid.UUID when valid
      - False when present but invalid (caller maps to HTTP 400)
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except (ValueError, TypeError, AttributeError):
        return False


class UseCaseCatalogueView(APIView):
    """GET /api/v1/use-cases/ — list 16 MVP1 pilots."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        return Response(list_catalogue_payload())


class UseCaseDetailView(APIView):
    """GET /api/v1/use-cases/{use_case_id}/ — pilot + blueprint summary."""

    permission_classes = [IsAuthenticated]

    def get(self, request, use_case_id: str):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .filter(use_case_id=use_case_id.upper())
            .first()
        )
        if pilot is None:
            return Response({"detail": "Use case not found."}, status=404)
        return Response(serialize_pilot_detail(pilot))


class UseCaseRecommendationsView(APIView):
    """GET /api/v1/use-cases/recommendations/ — company-scoped evaluation."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        return Response(build_recommendations_payload(company=company))


class UseCaseRecommendationDetailView(APIView):
    """GET /api/v1/use-cases/recommendations/{use_case_id}/."""

    permission_classes = [IsAuthenticated]

    def get(self, request, use_case_id: str):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view use cases."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        payload = build_single_recommendation_payload(
            company=company,
            use_case_id=use_case_id,
        )
        if payload is None:
            return Response({"detail": "Use case not found."}, status=404)
        return Response(payload)


class UseCaseBuildPackageView(APIView):
    """POST /api/v1/use-cases/{use_case_id}/build-package/ — BL-016."""

    permission_classes = [IsAuthenticated]

    def post(self, request, use_case_id: str):
        if request.user.role not in _UC_BUILD_ROLES:
            return Response(
                {"detail": "You do not have permission to generate build packages."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        try:
            result = generate_build_package(
                company=company,
                use_case_id=use_case_id,
                generated_by=request.user,
            )
        except BuildPackageError as exc:
            body: dict = {"detail": exc.detail, "code": exc.code}
            if exc.blockers:
                body["blockers"] = exc.blockers
            return Response(body, status=exc.status)
        return Response(serialize_build_package(result.package), status=201)


class BuildPackageDetailView(APIView):
    """GET /api/v1/build-packages/{package_id}/."""

    permission_classes = [IsAuthenticated]

    def get(self, request, package_id: str):
        if request.user.role not in _UC_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view build packages."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        record = WorkflowBuildPackage.objects.filter(
            pk=package_id,
            company=company,
        ).first()
        if record is None:
            return Response({"detail": "Build package not found."}, status=404)
        return Response(serialize_build_package(record))


class BuildPackageQaView(APIView):
    """POST/GET /api/v1/build-packages/{package_id}/qa/ (PRD-QA-01)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, package_id):
        company, err = _company_or_error(request)
        if err is not None:
            return err
        package = _package_for_company(company=company, package_id=package_id)
        if package is None:
            return Response({"detail": "Build package not found."}, status=404)
        try:
            outcome = run_qa_for_package(
                package=package,
                created_by=request.user,
            )
        except QaRunError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )
        return Response(outcome.payload, status=201)

    def get(self, request, package_id):
        company, err = _company_or_error(request)
        if err is not None:
            return err
        package = _package_for_company(company=company, package_id=package_id)
        if package is None:
            return Response({"detail": "Build package not found."}, status=404)
        latest = latest_qa_result_for_package(
            company_id=company.id,
            package_id=package.id,
        )
        if latest is None:
            return Response({"detail": "QA has not been run for this package."}, status=404)
        return Response(serialize_qa_result(latest))


class QaRunDetailView(APIView):
    """GET /api/v1/qa-runs/{qa_run_id}/ (PRD-QA-01 optional detail)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, qa_run_id):
        company, err = _company_or_error(request)
        if err is not None:
            return err
        record = (
            WorkflowQaResult.objects.filter(pk=qa_run_id, company=company)
            .first()
        )
        if record is None:
            return Response({"detail": "QA run not found."}, status=404)
        return Response(serialize_qa_result(record))


class BuildPackageHandoffView(APIView):
    """GET/POST /api/v1/build-packages/{package_id}/handoff/ (PRD-HO-01 §4–§5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, package_id):
        company, err = _company_for_handoff_read(request)
        if err is not None:
            return err
        package = _package_for_company(company=company, package_id=package_id)
        if package is None:
            return Response({"detail": "Build package not found."}, status=404)
        record = latest_handoff_for_package(
            company_id=company.id,
            package_id=package.id,
        )
        if record is None:
            return Response(
                {"detail": "Handoff has not been staged for this package."},
                status=404,
            )
        return Response(serialize_handoff(record))

    def post(self, request, package_id):
        company, err = _company_for_handoff_create(request)
        if err is not None:
            return err
        package = _package_for_company(company=company, package_id=package_id)
        if package is None:
            return Response({"detail": "Build package not found."}, status=404)

        raw_qa_run_id = (
            request.data.get("qa_run_id") if hasattr(request, "data") else None
        )
        qa_run_id = _parse_optional_uuid(raw_qa_run_id)
        if qa_run_id is False:
            return Response(
                {
                    "detail": "qa_run_id must be a valid UUID.",
                    "code": "invalid_qa_run_id",
                },
                status=400,
            )

        try:
            outcome = stage_handoff_for_package(
                package=package,
                created_by=request.user,
                qa_run_id=qa_run_id,
            )
        except HandoffStageError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        status_code = 201 if outcome.created else 200
        return Response(serialize_handoff(outcome.record), status=status_code)


class HandoffDetailView(APIView):
    """GET /api/v1/handoffs/{handoff_id}/ (PRD-HO-01 §5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, handoff_id):
        company, err = _company_for_handoff_read(request)
        if err is not None:
            return err
        record = _handoff_for_company(company=company, handoff_id=handoff_id)
        if record is None:
            return Response({"detail": "Handoff not found."}, status=404)
        return Response(serialize_handoff(record))


class HandoffListView(APIView):
    """GET /api/v1/handoffs/?package_id=&qa_run_id= (PRD-HO-01 §5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        company, err = _company_for_handoff_read(request)
        if err is not None:
            return err

        qs = (
            HandoffPackage.objects.filter(company=company)
            .select_related("package", "package__pilot", "qa_result", "company")
            .order_by("-created_at", "-id")
        )

        package_id = _parse_optional_uuid(request.query_params.get("package_id"))
        if package_id is False:
            return Response(
                {
                    "detail": "package_id must be a valid UUID.",
                    "code": "invalid_package_id",
                },
                status=400,
            )
        if package_id is not None:
            qs = qs.filter(package_id=package_id)

        qa_run_id = _parse_optional_uuid(request.query_params.get("qa_run_id"))
        if qa_run_id is False:
            return Response(
                {
                    "detail": "qa_run_id must be a valid UUID.",
                    "code": "invalid_qa_run_id",
                },
                status=400,
            )
        if qa_run_id is not None:
            qs = qs.filter(qa_result_id=qa_run_id)

        results = [serialize_handoff(row) for row in qs[:100]]
        return Response(
            {
                "count": len(results),
                "results": results,
            }
        )


class HandoffApproveView(APIView):
    """POST /api/v1/handoffs/{handoff_id}/approve/ (PRD-HO-02 §6.1)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, handoff_id):
        company, err = _company_for_handoff_activate(request)
        if err is not None:
            return err
        record = get_handoff_for_activation(
            company=company,
            handoff_id=handoff_id,
        )
        if record is None:
            return Response({"detail": "Handoff not found."}, status=404)

        body = _request_dict(request)
        manifest_hash, manifest_err = _manifest_hash_from_body(body)
        if manifest_err is not None:
            return manifest_err

        approval_token_id = body.get("approval_id") or body.get("approval_token_id")
        notes = body.get("notes")

        try:
            outcome = approve_handoff_for_activation(
                record=record,
                actor=request.user,
                manifest_hash=manifest_hash,
                notes=str(notes).strip() if notes is not None else None,
                approval_token_id=(
                    str(approval_token_id).strip() if approval_token_id else None
                ),
            )
        except HandoffActivationError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        return Response(build_approve_response(outcome), status=200)


class HandoffRejectView(APIView):
    """POST /api/v1/handoffs/{handoff_id}/reject/ (PRD-HO-02 §6)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, handoff_id):
        company, err = _company_for_handoff_activate(request)
        if err is not None:
            return err
        record = get_handoff_for_activation(
            company=company,
            handoff_id=handoff_id,
        )
        if record is None:
            return Response({"detail": "Handoff not found."}, status=404)

        body = _request_dict(request)
        manifest_hash, manifest_err = _manifest_hash_from_body(body)
        if manifest_err is not None:
            return manifest_err

        reason = body.get("reason") or body.get("rejection_reason")

        try:
            outcome = reject_handoff(
                record=record,
                actor=request.user,
                manifest_hash=manifest_hash,
                reason=str(reason).strip() if reason is not None else None,
            )
        except HandoffActivationError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        return Response(build_reject_response(outcome), status=200)


class HandoffConfirmActivatedView(APIView):
    """POST /api/v1/handoffs/{handoff_id}/confirm-activated/ (PRD-HO-02 §6.2)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, handoff_id):
        company, err = _company_for_handoff_activate(request)
        if err is not None:
            return err
        record = get_handoff_for_activation(
            company=company,
            handoff_id=handoff_id,
        )
        if record is None:
            return Response({"detail": "Handoff not found."}, status=404)

        body = _request_dict(request)
        manifest_hash, manifest_err = _manifest_hash_from_body(body)
        if manifest_err is not None:
            return manifest_err

        external_id = body.get("manago_workflow_external_id")
        notes = body.get("notes")

        try:
            outcome = confirm_handoff_activated(
                record=record,
                actor=request.user,
                manifest_hash=manifest_hash,
                manago_workflow_external_id=(
                    str(external_id).strip() if external_id is not None else None
                ),
                notes=str(notes).strip() if notes is not None else None,
            )
        except HandoffActivationError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=exc.status,
            )

        return Response(build_confirm_response(outcome), status=200)
