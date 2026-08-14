from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.auth.serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    UpdateMeSerializer,
)
from tenants.auth.services import (
    change_user_password,
    consume_password_reset_token,
    create_password_reset_token,
    find_user_for_password_reset,
    reset_user_password,
    serialize_me_response,
    update_user_display_name,
)
from tenants.emails import send_password_reset_email

_FORGOT_PASSWORD_RESPONSE = {
    "detail": "If an account exists, a reset link has been sent.",
}


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = find_user_for_password_reset(serializer.validated_data["email"])
        if user is not None:
            reset_token = create_password_reset_token(user)
            send_password_reset_email(email=user.email, token=reset_token.token)

        return Response(_FORGOT_PASSWORD_RESPONSE, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reset_token = consume_password_reset_token(
            serializer.validated_data["token"],
            serializer.validated_data["email"],
        )
        reset_user_password(reset_token, serializer.validated_data["password"])

        return Response(
            {"detail": "Password updated. You can sign in."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        change_user_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )

        return Response(
            {"detail": "Password updated."},
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            serialize_me_response(request.user),
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        serializer = UpdateMeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = update_user_display_name(
            user=request.user,
            name=serializer.validated_data["name"],
        )
        return Response(
            serialize_me_response(user),
            status=status.HTTP_200_OK,
        )
