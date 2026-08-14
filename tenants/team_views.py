import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from dataruns.audit import append_audit_event
from tenants.auth_views import _serialize_connector, _user_company
from tenants.emails import send_invite_email
from tenants.models import Connector, Invite, User


def _admin_only_response():
    return Response(
        {"detail": "Admin only."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _workspace_creator_id(tenant_id):
    earliest_admin = (
        User.objects.filter(tenant_id=tenant_id, role=User.Role.ADMIN)
        .order_by("created_at")
        .first()
    )
    if earliest_admin is not None:
        return earliest_admin.id
    earliest_user = (
        User.objects.filter(tenant_id=tenant_id).order_by("created_at").first()
    )
    return earliest_user.id if earliest_user is not None else None


def _serialize_member(user, creator_id):
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "email_verified": user.email_verified,
        "is_workspace_creator": user.id == creator_id,
        "created_at": user.created_at,
    }


def _serialize_invite(invite):
    return {
        "id": str(invite.id),
        "email": invite.email,
        "role": invite.role,
        "status": invite.status,
        "invited_by": {
            "id": str(invite.invited_by_id),
            "name": invite.invited_by.name,
            "email": invite.invited_by.email,
        },
        "expires_at": invite.expires_at,
        "created_at": invite.created_at,
        "accepted_at": invite.accepted_at,
    }


def _invite_no_longer_valid_response():
    return Response(
        {"detail": "Invite is no longer valid."},
        status=status.HTTP_410_GONE,
    )


def _invite_expiry():
    return timezone.now() + timedelta(days=settings.INVITE_TTL_DAYS)


def _would_remove_last_admin(tenant_id, target_user, new_role=None, new_is_active=None):
    role = new_role if new_role is not None else target_user.role
    is_active = new_is_active if new_is_active is not None else target_user.is_active

    if role == User.Role.ADMIN and is_active:
        return False

    active_admin_count = User.objects.filter(
        tenant_id=tenant_id,
        role=User.Role.ADMIN,
        is_active=True,
    ).count()

    if target_user.role == User.Role.ADMIN and target_user.is_active:
        if role != User.Role.ADMIN or not is_active:
            active_admin_count -= 1

    return active_admin_count < 1


def _accept_session_payload(user):
    company = _user_company(user)
    connectors = []
    if company is not None:
        connectors = list(Connector.objects.filter(company=company))
    needs_connector = not any(c.status == "connected" for c in connectors)
    tenant = user.tenant
    return {
        "access": str(AccessToken.for_user(user)),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "email_verified": user.email_verified,
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
            },
        },
        "connectors": [_serialize_connector(c) for c in connectors],
        "needs_connector": needs_connector,
    }


class TeamMemberListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        members = User.objects.filter(tenant_id=request.user.tenant_id).order_by(
            "created_at"
        )
        creator_id = _workspace_creator_id(request.user.tenant_id)
        return Response(
            {
                "members": [
                    _serialize_member(member, creator_id) for member in members
                ]
            },
            status=status.HTTP_200_OK,
        )


class TeamMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        if request.user.role != User.Role.ADMIN:
            return _admin_only_response()

        new_role = request.data.get("role")
        new_is_active = request.data.get("is_active")

        if new_role is not None and new_role not in User.Role.values:
            return Response(
                {"role": ["Invalid role."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            member = (
                User.objects.select_for_update()
                .filter(pk=id, tenant_id=request.user.tenant_id)
                .first()
            )
            if member is None:
                return Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if new_role is None and new_is_active is None:
                creator_id = _workspace_creator_id(request.user.tenant_id)
                return Response(
                    _serialize_member(member, creator_id),
                    status=status.HTTP_200_OK,
                )

            parsed_is_active = new_is_active
            if parsed_is_active is not None and not isinstance(parsed_is_active, bool):
                return Response(
                    {"is_active": ["Must be a boolean."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if _would_remove_last_admin(
                request.user.tenant_id,
                member,
                new_role=new_role,
                new_is_active=parsed_is_active,
            ):
                return Response(
                    {"detail": "Cannot remove the last admin."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            update_fields = ["updated_at"]
            if new_role is not None:
                member.role = new_role
                update_fields.append("role")
            if parsed_is_active is not None:
                member.is_active = parsed_is_active
                update_fields.append("is_active")
            member.save(update_fields=update_fields)

        creator_id = _workspace_creator_id(request.user.tenant_id)
        return Response(
            _serialize_member(member, creator_id),
            status=status.HTTP_200_OK,
        )


class TeamInviteListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        invites = (
            Invite.objects.filter(tenant_id=request.user.tenant_id)
            .select_related("invited_by")
            .order_by("-created_at")
        )
        return Response(
            {"invites": [_serialize_invite(invite) for invite in invites]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return _admin_only_response()

        email = (request.data.get("email") or "").strip().lower()
        role = request.data.get("role")

        missing = [
            field
            for field, value in {"email": email, "role": role}.items()
            if not value
        ]
        if missing:
            return Response(
                {field: ["This field is required."] for field in missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if role not in User.Role.values:
            return Response(
                {"role": ["Invalid role."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant_id = request.user.tenant_id

        if User.objects.filter(tenant_id=tenant_id, email__iexact=email).exists():
            return Response(
                {"email": ["This email is already on the team."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"email": ["A user with this email already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Invite.objects.filter(
            tenant_id=tenant_id,
            email__iexact=email,
            status=Invite.Status.PENDING,
        ).exists():
            return Response(
                {"email": ["An invite is already pending for this email."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invite = Invite.objects.create(
            tenant=request.user.tenant,
            email=email,
            role=role,
            invited_by=request.user,
            expires_at=_invite_expiry(),
        )

        send_invite_email(
            email=invite.email,
            token=invite.token,
            workspace_name=request.user.tenant.name,
            invited_by_name=request.user.name,
            role=invite.role,
        )

        invite = Invite.objects.select_related("invited_by").get(pk=invite.pk)

        company = _user_company(request.user)
        if company is not None:
            append_audit_event(
                company=company,
                action="team.invite_sent",
                summary=f"Team invite sent to {invite.email}",
                performed_by=request.user.email,
                actor_user_id=str(request.user.id),
                metadata={"email": invite.email, "role": invite.role},
            )

        return Response(
            _serialize_invite(invite),
            status=status.HTTP_201_CREATED,
        )


class TeamInviteResendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        if request.user.role != User.Role.ADMIN:
            return _admin_only_response()

        with transaction.atomic():
            invite = (
                Invite.objects.select_related("invited_by", "tenant")
                .select_for_update()
                .filter(pk=id, tenant_id=request.user.tenant_id)
                .first()
            )
            if invite is None:
                return Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if invite.status != Invite.Status.PENDING:
                return Response(
                    {"detail": "Invite is not pending."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if invite.expires_at <= timezone.now():
                return Response(
                    {"detail": "Invite has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            invite.token = secrets.token_urlsafe(32)
            invite.expires_at = _invite_expiry()
            invite.save(update_fields=["token", "expires_at", "updated_at"])

        send_invite_email(
            email=invite.email,
            token=invite.token,
            workspace_name=invite.tenant.name,
            invited_by_name=invite.invited_by.name,
            role=invite.role,
        )

        return Response(_serialize_invite(invite), status=status.HTTP_200_OK)


class TeamInviteRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        if request.user.role != User.Role.ADMIN:
            return _admin_only_response()

        invite = Invite.objects.select_related("invited_by").filter(
            pk=id,
            tenant_id=request.user.tenant_id,
        ).first()
        if invite is None:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if invite.status != Invite.Status.PENDING:
            return Response(
                {"detail": "Invite is not pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if invite.expires_at <= timezone.now():
            return Response(
                {"detail": "Invite has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invite.status = Invite.Status.REVOKED
        invite.save(update_fields=["status", "updated_at"])

        return Response(_serialize_invite(invite), status=status.HTTP_200_OK)


class TeamInviteAcceptView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        token = (request.query_params.get("token") or "").strip()
        if not token:
            return Response(
                {"detail": "token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            invite = (
                Invite.objects.select_related("tenant", "invited_by")
                .select_for_update()
                .filter(token=token)
                .first()
            )
            if invite is None:
                return Response(
                    {"detail": "Invite not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if invite.status in (
                Invite.Status.ACCEPTED,
                Invite.Status.REVOKED,
                Invite.Status.EXPIRED,
            ):
                return _invite_no_longer_valid_response()

            if invite.expires_at < timezone.now():
                invite.status = Invite.Status.EXPIRED
                invite.save(update_fields=["status", "updated_at"])
                return _invite_no_longer_valid_response()

        return Response(
            {
                "email": invite.email,
                "role": invite.role,
                "workspace_name": invite.tenant.name,
                "invited_by_name": invite.invited_by.name,
                "expires_at": invite.expires_at,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        name = (request.data.get("name") or "").strip()
        password = request.data.get("password")

        missing = [
            field
            for field, value in {
                "token": token,
                "name": name,
                "password": password,
            }.items()
            if not value
        ]
        if missing:
            return Response(
                {field: ["This field is required."] for field in missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = None
        with transaction.atomic():
            invite = (
                Invite.objects.select_related("tenant")
                .select_for_update()
                .filter(token=token)
                .first()
            )
            if invite is None:
                return Response(
                    {"detail": "Invite not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if invite.status != Invite.Status.PENDING:
                return _invite_no_longer_valid_response()

            if invite.expires_at < timezone.now():
                invite.status = Invite.Status.EXPIRED
                invite.save(update_fields=["status", "updated_at"])
                return _invite_no_longer_valid_response()

            if User.objects.filter(email__iexact=invite.email).exists():
                return Response(
                    {"email": ["A user with this email already exists."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = User(
                email=invite.email,
                name=name,
                tenant=invite.tenant,
                role=invite.role,
                email_verified=True,
                is_active=True,
            )
            user.set_password(password)
            user.save()

            invite.status = Invite.Status.ACCEPTED
            invite.accepted_at = timezone.now()
            invite.accepted_user = user
            invite.save(
                update_fields=[
                    "status",
                    "accepted_at",
                    "accepted_user",
                    "updated_at",
                ]
            )

        company = _user_company(user) if user is not None else None
        if company is not None:
            append_audit_event(
                company=company,
                action="team.invite_accepted",
                summary=f"Team invite accepted by {user.email}",
                performed_by=user.email,
                actor_user_id=str(user.id),
                metadata={"email": user.email, "role": user.role},
            )

        return Response(_accept_session_payload(user), status=status.HTTP_200_OK)
