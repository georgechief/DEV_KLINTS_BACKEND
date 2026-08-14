"""Architecture Assessment HTTP API (PRD-AF-01 §8)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.architecture.coverage import build_coverage_payload
from dataruns.architecture.enqueue import enqueue_architecture_assessment
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.architecture.serialize import (
    build_gaps_payload,
    build_latest_architecture_payload,
    serialize_architecture_assessment,
    serialize_architecture_graph,
)
from dataruns.models import DataRun
from tenants.auth.services import get_user_company
from tenants.models import User

_AF_READ_ROLES = (User.Role.ADMIN, User.Role.ANALYST, User.Role.VIEWER)


class ArchitectureLatestView(APIView):
    """GET /api/v1/architecture/assessments/latest/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        return Response(build_latest_architecture_payload(company=company))


class ArchitectureAssessmentsView(APIView):
    """POST /api/v1/architecture/assessments/ — ops/tests only (PRD §5.1)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Only admins can start an architecture assessment."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )

        body = request.data if isinstance(request.data, dict) else {}
        source_id = body.get("source_dcs_data_run_id")
        source_run = None
        if source_id is not None:
            try:
                source_run = DataRun.objects.get(id=int(source_id))
            except (TypeError, ValueError, DataRun.DoesNotExist):
                return Response(
                    {"detail": "source_dcs_data_run_id not found."},
                    status=404,
                )

        result = enqueue_architecture_assessment(
            company,
            source_dcs_data_run=source_run,
            triggered_by="manual",
            actor_user_id=str(request.user.id),
            queue=True,
        )
        if result.skipped and result.skip_reason == "manago_not_eligible":
            return Response(
                {"detail": "Connect Manago.ai before running architecture assessment."},
                status=422,
            )
        if result.skipped and result.skip_reason == "already_running":
            return Response(
                {
                    "detail": "An architecture assessment is already in progress.",
                    "assessment": serialize_architecture_assessment(result.assessment),
                },
                status=409,
            )
        if result.skipped:
            return Response(
                {"detail": f"Skipped: {result.skip_reason}"},
                status=422,
            )

        return Response(
            {
                "assessment_id": str(result.assessment.id),
                "data_run_id": result.data_run.id,
                "status": result.assessment.status,
                "task_queued": result.task_queued,
            },
            status=202,
        )


class ArchitectureAssessmentDetailView(APIView):
    """GET /api/v1/architecture/assessments/{id}/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id: str):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        assessment = (
            ArchitectureAssessment.objects.filter(id=assessment_id, company=company)
            .select_related("data_run", "source_dcs_data_run")
            .first()
        )
        if assessment is None:
            return Response({"detail": "Assessment not found."}, status=404)
        return Response(serialize_architecture_assessment(assessment))


class ArchitectureAssessmentAssetsView(APIView):
    """GET /api/v1/architecture/assessments/{id}/assets/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id: str):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        assessment = ArchitectureAssessment.objects.filter(
            id=assessment_id,
            company=company,
        ).first()
        if assessment is None:
            return Response({"detail": "Assessment not found."}, status=404)

        qs = assessment.assets.all()
        asset_type = request.query_params.get("asset_type")
        if asset_type:
            qs = qs.filter(asset_type=asset_type.upper())
        lifecycle_stage = request.query_params.get("lifecycle_stage")
        if lifecycle_stage:
            qs = qs.filter(lifecycle_stage=lifecycle_stage)

        verdict_by_asset = {
            row.asset_id: row
            for row in assessment.asset_verdicts.all()
        }
        verdict_filter = (request.query_params.get("verdict") or "").strip().upper()
        if verdict_filter:
            matching_ids = [
                asset_id
                for asset_id, row in verdict_by_asset.items()
                if row.verdict == verdict_filter
            ]
            qs = qs.filter(asset_id__in=matching_ids)

        results = []
        for row in qs[:500]:
            verdict_row = verdict_by_asset.get(row.asset_id)
            verdict = verdict_row.verdict if verdict_row else None
            results.append(
                {
                    "asset_id": row.asset_id,
                    "asset_type": row.asset_type,
                    "name": row.name,
                    "status": row.status,
                    "lifecycle_stage": row.lifecycle_stage,
                    "capability_path": row.capability_path,
                    "definition": row.definition,
                    "verdict": verdict,
                    "dcs_check_ids": (
                        verdict_row.dcs_check_ids if verdict_row else []
                    ),
                    "blocked_reason": (
                        verdict_row.blocked_reason if verdict_row else ""
                    ),
                    "failure_code": (
                        verdict_row.failure_code if verdict_row else ""
                    ),
                }
            )
        return Response(
            {
                "assessment_id": str(assessment.id),
                "count": len(results),
                "results": results,
            }
        )


class ArchitectureAssessmentGraphView(APIView):
    """GET /api/v1/architecture/assessments/{id}/graph/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id: str):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        assessment = ArchitectureAssessment.objects.filter(
            id=assessment_id,
            company=company,
        ).first()
        if assessment is None:
            return Response({"detail": "Assessment not found."}, status=404)
        return Response(serialize_architecture_graph(assessment))


class ArchitectureAssessmentCoverageView(APIView):
    """GET /api/v1/architecture/assessments/{id}/coverage/ — sheet 07 map (PRD §8)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id: str):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        assessment = ArchitectureAssessment.objects.filter(
            id=assessment_id,
            company=company,
        ).first()
        if assessment is None:
            return Response({"detail": "Assessment not found."}, status=404)
        horizon = request.query_params.get("horizon")
        return Response(build_coverage_payload(assessment, horizon=horizon))


class ArchitectureAssessmentGapsView(APIView):
    """GET /api/v1/architecture/assessments/{id}/gaps/ — WF-12 → Opportunities."""

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id: str):
        if request.user.role not in _AF_READ_ROLES:
            return Response(
                {"detail": "You do not have permission to view architecture assessments."},
                status=403,
            )
        company = get_user_company(request.user)
        if company is None:
            return Response(
                {"detail": "No company is associated with this account."},
                status=400,
            )
        assessment = ArchitectureAssessment.objects.filter(
            id=assessment_id,
            company=company,
        ).first()
        if assessment is None:
            return Response({"detail": "Assessment not found."}, status=404)
        return Response(build_gaps_payload(assessment))
