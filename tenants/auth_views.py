import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from tenants.crypto import has_api_v3_key_in_config, masked_config
from tenants.emails import send_verification_email
from tenants.models import Company, Connector, EmailVerificationToken, Tenant, User
from tenants.workspace.services import validate_company_domain


def _unique_tenant_slug(name: str) -> str:
    base = slugify(name) or "tenant"
    slug = base
    counter = 2
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _user_company(user: User):
    return (
        Company.objects.filter(tenant_id=user.tenant_id)
        .order_by("created_at")
        .first()
    )


def _create_verification_token(user: User) -> EmailVerificationToken:
    return EmailVerificationToken.objects.create(
        user=user,
        email=user.email,
        token=secrets.token_urlsafe(32),
        expires_at=timezone.now()
        + timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS),
    )


def _verify_email_success_response(user: User) -> Response:
    return Response(
        {
            "detail": "Email verified. You can sign in.",
            "email": user.email,
            "email_verified": True,
        },
        status=status.HTTP_200_OK,
    )


def _verify_email_invalid_response() -> Response:
    return Response(
        {"detail": "Invalid or expired verification link."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _connector_display_name(name: str) -> str:
    if name == "manago_ai":
        return "Manago.ai"
    if name == "shopify":
        return "Shopify"
    return name


def _serialize_connector(connector: Connector) -> dict:
    item = {
        "id": str(connector.id),
        "name": connector.name,
        "type": connector.type,
        "display_name": _connector_display_name(connector.name),
        "status": connector.status,
        "config": masked_config(connector.config),
        "created_at": connector.created_at,
    }
    if connector.name == "manago_ai":
        item["has_api_v3_key"] = has_api_v3_key_in_config(connector.config)
    return item


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password")
        name = request.data.get("name")
        company_name = request.data.get("company_name")
        company_domain = request.data.get("company_domain")
        tenant_name = request.data.get("tenant_name") or company_name

        missing = [
            field
            for field, value in {
                "email": email,
                "password": password,
                "name": name,
                "company_name": company_name,
                "company_domain": company_domain,
            }.items()
            if not value
        ]
        if missing:
            return Response(
                {field: ["This field is required."] for field in missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company_domain = validate_company_domain(company_domain)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"email": ["A user with this email already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=tenant_name,
                slug=_unique_tenant_slug(tenant_name),
            )
            company = Company.objects.create(
                tenant=tenant,
                name=company_name,
                domain=company_domain,
            )
            user = User(
                email=email,
                name=name,
                tenant=tenant,
                role=User.Role.ADMIN,
                email_verified=False,
                is_active=False,
            )
            user.set_password(password)
            user.save()
            verification = _create_verification_token(user)

        send_verification_email(email=user.email, token=verification.token)

        return Response(
            {
                "detail": (
                    "Account created. Check your email to verify before signing in."
                ),
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "email_verified": user.email_verified,
                    "tenant_id": str(user.tenant_id),
                    "created_at": user.created_at,
                },
                "tenant": {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                },
                "company": {
                    "id": str(company.id),
                    "name": company.name,
                    "domain": company.domain,
                    "tenant_id": str(company.tenant_id),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        email = (request.data.get("email") or "").strip().lower()

        if not token or not email:
            return _verify_email_invalid_response()

        with transaction.atomic():
            verification = (
                EmailVerificationToken.objects.select_related("user")
                .select_for_update()
                .filter(token=token, email__iexact=email)
                .first()
            )
            if verification is None:
                return _verify_email_invalid_response()

            user = verification.user

            if user.email_verified:
                if verification.used_at is None:
                    verification.used_at = timezone.now()
                    verification.save(update_fields=["used_at"])
                return _verify_email_success_response(user)

            if verification.used_at is not None:
                return _verify_email_invalid_response()

            if verification.expires_at <= timezone.now():
                return _verify_email_invalid_response()

            user.email_verified = True
            user.is_active = True
            user.save(update_fields=["email_verified", "is_active", "updated_at"])
            verification.used_at = timezone.now()
            verification.save(update_fields=["used_at"])

        return _verify_email_success_response(user)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password")
        origin = request.headers.get("Origin", "-")

        print(
            f"[login] attempt email={email!r} origin={origin} "
            f"has_password={bool(password)}"
        )

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            print(f"[login] failed email={email!r} reason=user_not_found")
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.check_password(password or ""):
            print(f"[login] failed email={email!r} reason=bad_password")
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.email_verified:
            print(f"[login] failed email={email!r} reason=email_not_verified")
            return Response(
                {
                    "detail": "Email is not verified.",
                    "code": "email_not_verified",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        connectors = []
        if company is not None:
            connectors = list(Connector.objects.filter(company=company))

        needs_connector = not any(c.status == "connected" for c in connectors)

        print(
            f"[login] success email={email!r} user_id={user.id} "
            f"needs_connector={needs_connector}"
        )

        return Response(
            {
                "access": str(AccessToken.for_user(user)),
                "needs_connector": needs_connector,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "email_verified": user.email_verified,
                    "tenant_id": str(user.tenant_id),
                    "company_id": str(company.id) if company else None,
                },
                "connectors": [_serialize_connector(c) for c in connectors],
            },
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        payload = {
            "detail": (
                "If an account exists and is unverified, a new link has been sent."
            )
        }

        user = User.objects.filter(email__iexact=email).first()
        if user is not None and not user.email_verified:
            with transaction.atomic():
                EmailVerificationToken.objects.filter(
                    user=user,
                    used_at__isnull=True,
                ).update(used_at=timezone.now())
                verification = _create_verification_token(user)
            send_verification_email(email=user.email, token=verification.token)

        return Response(payload, status=status.HTTP_200_OK)
