from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import User
from tenants.workspace.serializers import UpdateWorkspaceSerializer
from tenants.workspace.services import update_workspace


class WorkspaceView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response(
                {"detail": "Admin only."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = UpdateWorkspaceSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        payload = update_workspace(
            user=request.user,
            tenant_name=serializer.validated_data.get("tenant_name"),
            company_name=serializer.validated_data.get("company_name"),
            company_domain=serializer.validated_data.get("company_domain"),
        )
        return Response(payload, status=status.HTTP_200_OK)
