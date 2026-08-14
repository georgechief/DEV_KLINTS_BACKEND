from django.urls import path

from tenants.auth.views import (
    ChangePasswordView,
    ForgotPasswordView,
    ResetPasswordView,
)

urlpatterns = [
    path(
        "forgot-password/",
        ForgotPasswordView.as_view(),
        name="auth-forgot-password",
    ),
    path(
        "reset-password/",
        ResetPasswordView.as_view(),
        name="auth-reset-password",
    ),
    path(
        "change-password/",
        ChangePasswordView.as_view(),
        name="auth-change-password",
    ),
]
