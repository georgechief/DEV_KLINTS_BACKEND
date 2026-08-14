from django.urls import include, path

from tenants.auth.views import MeView
from tenants.auth_views import (
    LoginView,
    RegisterView,
    ResendVerificationView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path(
        "resend-verification/",
        ResendVerificationView.as_view(),
        name="auth-resend-verification",
    ),
    path("me/", MeView.as_view(), name="auth-me"),
    path("", include("tenants.auth.urls")),
    path("", include("tenants.workspace.urls")),
]
