from urllib.parse import urlencode

import logging

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dataruns.connectors.base import (
    decrypt_connector_config,
    enqueue_connector_bootstrap,
    find_latest_bootstrap_data_run,
)
from dataruns.connectors.bootstrap_health import build_latest_bootstrap_payload
from dataruns.audit import append_audit_event
from dataruns.models import AuditLog
from tenants import shopify
from tenants.connector_types import (
    CONNECTOR_TYPE_ECOMMERCE,
    resolve_connector_type,
)
from tenants.connector_uniqueness import (
    AccountAlreadyConnectedError,
    PLATFORM_MANAGO,
    PLATFORM_SHOPIFY,
    assert_external_account_available,
    get_manago_account_warning,
    resolve_manago_external_account_key,
    resolve_shopify_external_account_key,
)
from tenants.crypto import encrypt_config, has_api_v3_key_in_config, masked_config
from tenants.manago import verify_credentials
from tenants.manago_topology_service import (
    ManagoTopologyError,
    apply_primary_owner,
    ensure_manago_primary_owner,
    list_manago_owners,
    preferred_owner_from_config,
    topology_status,
)
from tenants.models import Company, Connector, ConnectorSnapshot, User
from tenants.emails import MailerAPIError, send_connector_connected_email
from tenants.shopify import ShopifyOAuthError

SHOPIFY_STATE_SALT = "tenants.shopify.oauth"
SHOPIFY_STATE_MAX_AGE_SECONDS = 600

logger = logging.getLogger(__name__)


def _user_company(user: User):
    return (
        Company.objects.filter(tenant_id=user.tenant_id)
        .order_by("created_at")
        .first()
    )


def _notify_connector_connected(
    *,
    company: Company,
    platform: str,
    account_label: str | None = None,
) -> None:
    try:
        send_connector_connected_email(
            company=company,
            platform=platform,
            account_label=account_label,
        )
    except MailerAPIError:
        logger.warning(
            "connector connected email failed platform=%s company_id=%s",
            platform,
            company.id,
        )
    except Exception:  # noqa: BLE001 — never fail connect because of email
        logger.exception(
            "connector connected email unexpected error platform=%s company_id=%s",
            platform,
            company.id,
        )


def _connector_display_name(name: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    if name == "manago_ai":
        return "Manago.ai"
    if name == "shopify":
        return "Shopify"
    return name


def _account_already_connected_response(
    exc: AccountAlreadyConnectedError,
) -> Response:
    return Response(
        {
            "detail": exc.detail,
            "code": exc.code,
            "platform": exc.platform,
            "external_key": exc.external_key,
        },
        status=status.HTTP_409_CONFLICT,
    )


def _latest_bootstrap_for_connector(
    *,
    company: Company,
    connector: Connector,
) -> dict | None:
    data_run = find_latest_bootstrap_data_run(company=company, connector=connector)
    if data_run is None:
        return None
    return build_latest_bootstrap_payload(data_run)


def _serialize_connector_list_item(
    *,
    company: Company,
    connector: Connector,
) -> dict:
    item = {
        "id": str(connector.id),
        "name": connector.name,
        "type": connector.type,
        "display_name": _connector_display_name(connector.name),
        "status": connector.status,
        "config": masked_config(connector.config),
        "created_at": connector.created_at,
        "latest_bootstrap": _latest_bootstrap_for_connector(
            company=company,
            connector=connector,
        ),
    }
    if connector.name == PLATFORM_MANAGO:
        item["has_api_v3_key"] = has_api_v3_key_in_config(connector.config)
        plain = decrypt_connector_config(connector.config)
        primary = preferred_owner_from_config(plain)
        item["primary_owner"] = primary
        item["topology_configured"] = bool(
            primary and isinstance(plain.get("topology"), dict)
        )
    return item


def _manago_api_v3_key_response(connector: Connector) -> dict:
    masked = masked_config(connector.config)
    return {
        "platform": PLATFORM_MANAGO,
        "has_api_v3_key": has_api_v3_key_in_config(connector.config),
        "api_v3_key_masked": masked.get("api_v3_key", ""),
    }


def _get_manago_connector(*, company: Company) -> Connector | None:
    return Connector.objects.filter(company=company, name=PLATFORM_MANAGO).first()


class ConnectorVerifyView(APIView):
    """Verify Manago.ai credentials without saving a connector."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        client_id = (request.data.get("client_id") or "").strip()
        api_secret = (request.data.get("api_secret") or "").strip()
        endpoint = (request.data.get("endpoint") or "").strip()

        print(
            f"[manago verify] attempt endpoint={endpoint!r} "
            f"client_id={client_id!r} has_api_secret={bool(api_secret)} "
            f"user={getattr(request.user, 'email', None)!r}"
        )

        missing = [
            field
            for field, value in {
                "client_id": client_id,
                "api_secret": api_secret,
                "endpoint": endpoint,
            }.items()
            if not value
        ]
        if missing:
            print(f"[manago verify] failed reason=missing_fields fields={missing}")
            return Response(
                {field: ["This field is required."] for field in missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = verify_credentials(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=endpoint,
        )
        if result.valid:
            print(
                f"[manago verify] success endpoint={endpoint!r} "
                f"client_id={client_id!r} message={result.message!r}"
            )
        else:
            print(
                f"[manago verify] failed endpoint={endpoint!r} "
                f"client_id={client_id!r} error={result.message!r}"
            )

        response_data = {
            "valid": result.valid,
            "message": result.message,
        }
        if result.valid:
            company = _user_company(request.user)
            if company is not None:
                warning = get_manago_account_warning(
                    external_key=client_id,
                    company=company,
                )
                if warning is not None:
                    response_data["warning"] = warning

        # Always HTTP 200: validity is in the body (`valid` + `message`).
        return Response(
            response_data,
            status=status.HTTP_200_OK,
        )


class ConnectorListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        company = _user_company(request.user)
        qs = Connector.objects.none()
        if company is not None:
            qs = Connector.objects.filter(company=company).order_by("name")

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        results = [
            _serialize_connector_list_item(company=company, connector=connector)
            for connector in page
        ]
        return paginator.get_paginated_response(results)

    def post(self, request):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to add connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = request.data.get("name")
        display_name = request.data.get("display_name")
        config = request.data.get("config")

        if name != "manago_ai":
            return Response(
                {"name": ["Only manago_ai is supported."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(config, dict):
            return Response(
                {"config": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        missing_config = [
            field
            for field in ("base_url", "workspace_id", "api_key")
            if not config.get(field)
        ]
        if missing_config:
            return Response(
                {
                    "config": [
                        f"Missing required fields: {', '.join(missing_config)}."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Connector.objects.filter(company=company, name="manago_ai").exists():
            return Response(
                {"detail": "Connector already connected."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            assert_external_account_available(
                platform=PLATFORM_MANAGO,
                external_key=str(config["workspace_id"]).strip(),
                company=company,
            )
        except AccountAlreadyConnectedError as exc:
            return _account_already_connected_response(exc)

        plain_api_key = config["api_key"]
        base_url = str(config.get("base_url") or config.get("endpoint") or "").strip()
        stored_config_input = {
            key: value
            for key, value in config.items()
            if key not in ("base_url", "endpoint", "api_key")
        }
        stored_config_input["workspace_id"] = config["workspace_id"]
        stored_config_input["base_url"] = base_url.rstrip("/")
        stored_config = encrypt_config(
            {**stored_config_input, "api_key": plain_api_key}
        )
        snapshot_data = dict(stored_config_input)

        with transaction.atomic():
            connector = Connector.objects.create(
                company=company,
                name=name,
                type=resolve_connector_type(name),
                config=stored_config,
                status="connected",
                external_account_key=resolve_manago_external_account_key(
                    str(config["workspace_id"])
                ),
            )
            snapshot = ConnectorSnapshot.objects.create(
                connector=connector,
                version=1,
                snapshot_data=snapshot_data,
            )

        bootstrap = enqueue_connector_bootstrap(
            company=company,
            connector=connector,
            actor_user_id=str(user.id),
        )

        append_audit_event(
            company=company,
            action="connector.connected",
            summary=f"{_connector_display_name(connector.name, fallback=display_name)} connected",
            performed_by=user.email,
            actor_user_id=str(user.id),
            metadata={
                "platform": connector.name,
                "connector_id": str(connector.id),
            },
        )

        _notify_connector_connected(
            company=company,
            platform=connector.name,
            account_label=str(config.get("workspace_id") or "").strip() or None,
        )

        response_config = {
            **stored_config_input,
            "api_key": masked_config({"api_key": plain_api_key})["api_key"],
        }

        return Response(
            {
                "id": str(connector.id),
                "company_id": str(connector.company_id),
                "name": connector.name,
                "type": connector.type,
                "display_name": _connector_display_name(
                    connector.name, fallback=display_name
                ),
                "status": connector.status,
                "config": response_config,
                "snapshot": {
                    "id": str(snapshot.id),
                    "version": snapshot.version,
                    "created_at": snapshot.created_at,
                },
                "created_at": connector.created_at,
                "bootstrap": {
                    "data_run_id": bootstrap.data_run.id,
                    "task_queued": bootstrap.task_queued,
                    "days": bootstrap.data_run.metadata.get("days"),
                },
            },
            status=status.HTTP_201_CREATED,
        )


def _shopify_redirect(return_to: str, **params: str) -> HttpResponseRedirect:
    target = return_to or settings.FRONTEND_SHOPIFY_REDIRECT_URL
    separator = "&" if "?" in target else "?"
    return HttpResponseRedirect(f"{target}{separator}{urlencode(params)}")


class ShopifyOAuthStartView(APIView):
    """
    Begin the Shopify OAuth flow for the user's company.

    Returns the Shopify authorize URL for the frontend to navigate to.
    Works from both onboarding and the integrations page: pass an optional
    `return_to` URL to control where the callback redirects afterwards.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to add connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not settings.SHOPIFY_API_KEY or not settings.SHOPIFY_API_SECRET:
            return Response(
                {"detail": "Shopify integration is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            shop = shopify.normalize_shop_domain(request.data.get("shop") or "")
        except ShopifyOAuthError as exc:
            return Response(
                {"shop": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            assert_external_account_available(
                platform=PLATFORM_SHOPIFY,
                external_key=shop,
                company=company,
            )
        except AccountAlreadyConnectedError as exc:
            return _account_already_connected_response(exc)

        return_to = request.data.get("return_to") or ""
        state = signing.dumps(
            {
                "user_id": str(user.id),
                "company_id": str(company.id),
                "shop": shop,
                "return_to": return_to,
            },
            salt=SHOPIFY_STATE_SALT,
        )

        return Response(
            {
                "authorize_url": shopify.build_authorize_url(
                    shop=shop, state=state
                ),
                "shop": shop,
            },
            status=status.HTTP_200_OK,
        )


class ShopifyOAuthCallbackView(APIView):
    """
    Shopify redirects the merchant's browser here after consent.

    Unauthenticated by necessity; trust is established by the signed state
    (created by an authenticated admin/analyst) and Shopify's HMAC.
    On success the connector is created or updated, then the browser is
    redirected back to the frontend with status query parameters.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        params = {
            key: request.query_params[key] for key in request.query_params
        }

        try:
            state = signing.loads(
                params.get("state", ""),
                salt=SHOPIFY_STATE_SALT,
                max_age=SHOPIFY_STATE_MAX_AGE_SECONDS,
            )
        except signing.BadSignature:
            return _shopify_redirect("", shopify="error", reason="invalid_state")

        return_to = state.get("return_to") or ""
        shop = state.get("shop") or ""

        if params.get("shop") != shop:
            return _shopify_redirect(
                return_to, shopify="error", reason="shop_mismatch"
            )

        if not shopify.verify_callback_hmac(params):
            return _shopify_redirect(
                return_to, shopify="error", reason="invalid_hmac"
            )

        code = params.get("code")
        if not code:
            return _shopify_redirect(
                return_to, shopify="error", reason="missing_code"
            )

        company = Company.objects.filter(pk=state.get("company_id")).first()
        if company is None:
            return _shopify_redirect(
                return_to, shopify="error", reason="company_not_found"
            )

        try:
            token = shopify.exchange_code_for_token(shop=shop, code=code)
            shop_info = shopify.fetch_shop(
                shop=shop, access_token=token.access_token
            )
        except ShopifyOAuthError:
            return _shopify_redirect(
                return_to, shopify="error", reason="token_exchange_failed"
            )

        try:
            assert_external_account_available(
                platform=PLATFORM_SHOPIFY,
                external_key=shop,
                company=company,
                shop_id=shop_info.get("id"),
            )
        except AccountAlreadyConnectedError:
            return _shopify_redirect(
                return_to,
                shopify="error",
                reason="account_already_connected",
            )

        config = {
            "shop_domain": shop,
            "shop_id": shop_info.get("id"),
            "shop_name": shop_info.get("name"),
            "api_version": settings.SHOPIFY_API_VERSION,
            **shopify.token_bundle_to_config_fields(token),
        }
        stored_config = encrypt_config(config)
        snapshot_data = shopify.snapshot_safe_shopify_config(config)

        with transaction.atomic():
            connector, created = Connector.objects.update_or_create(
                company=company,
                name="shopify",
                defaults={
                    "type": CONNECTOR_TYPE_ECOMMERCE,
                    "config": stored_config,
                    "status": "connected",
                    "external_account_key": resolve_shopify_external_account_key(shop),
                },
            )
            last_version = (
                ConnectorSnapshot.objects.filter(connector=connector)
                .aggregate(Max("version"))["version__max"]
                or 0
            )
            ConnectorSnapshot.objects.create(
                connector=connector,
                version=last_version + 1,
                snapshot_data=snapshot_data,
            )

        bootstrap = enqueue_connector_bootstrap(
            company=company,
            connector=connector,
            supersede_existing=not created,
            actor_user_id=state.get("user_id"),
        )

        actor_user_id = state.get("user_id")
        actor = User.objects.filter(pk=actor_user_id).first() if actor_user_id else None
        append_audit_event(
            company=company,
            action="connector.connected",
            summary=f"Shopify connected ({shop})",
            performed_by=actor.email if actor is not None else "system",
            actor_user_id=str(actor.id) if actor is not None else None,
            metadata={
                "platform": "shopify",
                "connector_id": str(connector.id),
            },
        )

        _notify_connector_connected(
            company=company,
            platform="shopify",
            account_label=shop,
        )

        return _shopify_redirect(
            return_to,
            shopify="connected",
            shop=shop,
            bootstrap="queued",
            data_run_id=str(bootstrap.data_run.id),
        )


def _parse_fetch_days(request) -> tuple[int | None, Response | None]:
    days = request.data.get("days", settings.BOOTSTRAP_DAYS)
    if not isinstance(days, int) or isinstance(days, bool):
        return None, Response(
            {"days": ["Must be an integer."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if days < 1 or days > 31:
        return None, Response(
            {"days": ["Must be between 1 and 31."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return days, None


def _run_connector_import(request, *, platform: str) -> Response:
    user = request.user
    if user.role != User.Role.ADMIN:
        return Response(
            {"detail": "You do not have permission to fetch connector data."},
            status=status.HTTP_403_FORBIDDEN,
        )

    days, error_response = _parse_fetch_days(request)
    if error_response is not None:
        return error_response

    company = _user_company(user)
    if company is None:
        return Response(
            {"detail": "Company not found for this user."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        connector = Connector.objects.get(company=company, name=platform)
    except Connector.DoesNotExist:
        return Response(
            {"detail": "Connector not connected."},
            status=status.HTTP_404_NOT_FOUND,
        )

    bootstrap = enqueue_connector_bootstrap(
        company=company,
        connector=connector,
        triggered_by="manual_fetch",
        actor_user_id=str(user.id),
        days=days,
    )

    return Response(
        {
            "data_run_id": bootstrap.data_run.id,
            "run_id": None,
            "status": bootstrap.data_run.status,
            "days": bootstrap.data_run.metadata.get("days", days),
            "platform": platform,
            "detail": "Bootstrap fetch queued.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


class ShopifyFetchView(APIView):
    """Fetch Shopify data via the connector import pipeline (PRD §7)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _run_connector_import(request, platform="shopify")


class ManagoFetchView(APIView):
    """Fetch Manago.ai data via the connector import pipeline (PRD §7)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _run_connector_import(request, platform="manago_ai")


class ConnectorBootstrapStatusView(APIView):
    """Return bootstrap status for a connector (PRD-CONN-01 §8.3)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        if user.role != User.Role.ADMIN:
            return Response(
                {"detail": "You do not have permission to view bootstrap status."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = Connector.objects.filter(pk=pk, company=company).first()
        if connector is None:
            return Response(
                {"detail": "Connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        data_run = find_latest_bootstrap_data_run(
            company=company,
            connector=connector,
        )
        if data_run is None:
            return Response(
                {"detail": "Bootstrap not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        metadata = data_run.metadata or {}
        health_report = metadata.get("health_report")
        if not isinstance(health_report, dict):
            health_report = {}

        return Response(
            {
                "connector_id": str(connector.id),
                "connector_name": connector.name,
                "connector_status": connector.status,
                "data_run_id": data_run.id,
                "data_run_status": data_run.status,
                "run_id": metadata.get("run_id"),
                "days": metadata.get("days"),
                "window_start": health_report.get("window_start"),
                "window_end": health_report.get("window_end"),
                "health_report": health_report,
                "started_at": data_run.started_at,
                "finished_at": data_run.finished_at,
            },
            status=status.HTTP_200_OK,
        )


_MANAGO_API_V3_KEY_MIN_LENGTH = 8


def _shopify_shop_domain_for_company(company: Company) -> str | None:
    shopify = Connector.objects.filter(company=company, name=PLATFORM_SHOPIFY).first()
    if shopify is None:
        return None
    config = decrypt_connector_config(shopify.config)
    domain = config.get("shop_domain")
    if isinstance(domain, str) and domain.strip():
        return domain.strip()
    return None


def _manago_owners_response(
    *,
    connector: Connector,
    config: dict,
    owners: list[str],
) -> dict:
    status_payload = topology_status(config=config, owners=owners)
    return {
        "platform": PLATFORM_MANAGO,
        "connector_id": str(connector.id),
        **status_payload,
    }


class ManagoOwnersView(APIView):
    """
    GET  /api/v1/connectors/manago_ai/owners/ — list Manago users + selection state
    PUT  /api/v1/connectors/manago_ai/owners/ — set primary owner (FD-06)

    Frontend: after Manago connect, GET owners; if needs_primary_selection, show
    picker; PUT {\"owner\": \"email@…\"}.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = _get_manago_connector(company=company)
        if connector is None:
            return Response(
                {"detail": "Manago connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        config = decrypt_connector_config(connector.config)
        try:
            owners = list_manago_owners(config=config)
        except ManagoTopologyError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if user.role in (User.Role.ADMIN, User.Role.ANALYST):
            ensure_manago_primary_owner(
                company,
                actor_user_id=str(user.id),
                performed_by=user.email,
                allow_multi_owner_inference=False,
            )

        return Response(
            _manago_owners_response(
                connector=connector,
                config=decrypt_connector_config(connector.config),
                owners=owners,
            )
        )

    def put(self, request):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to update connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = _get_manago_connector(company=company)
        if connector is None:
            return Response(
                {"detail": "Manago connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        raw_owner = request.data.get("owner") or request.data.get("primary_owner")
        if not isinstance(raw_owner, str) or not raw_owner.strip():
            return Response(
                {"owner": ["Select a Manago primary owner email."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        primary = raw_owner.strip()

        config = decrypt_connector_config(connector.config)
        try:
            owners = list_manago_owners(config=config)
        except ManagoTopologyError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if owners and not any(o.lower() == primary.lower() for o in owners):
            return Response(
                {
                    "owner": [
                        "Owner must be one of the Manago users on this account."
                    ],
                    "owners": owners,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        shop_domain = _shopify_shop_domain_for_company(company)
        try:
            config = apply_primary_owner(
                config=config,
                primary_owner=primary,
                all_owners=owners or [primary],
                shop_domain=shop_domain,
            )
        except ManagoTopologyError as exc:
            return Response(
                {"owner": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector.config = encrypt_config(config)
        connector.save(update_fields=["config", "updated_at"])

        append_audit_event(
            company=company,
            action="connector.manago_primary_owner_set",
            summary="Manago primary owner selected",
            performed_by=user.email,
            actor_user_id=str(user.id),
            metadata={
                "platform": PLATFORM_MANAGO,
                "connector_id": str(connector.id),
                "primary_owner": config.get("owner"),
                "owner_count": len(owners) if owners else 1,
            },
        )

        from dataruns.dcs.enqueue import maybe_enqueue_dcs_after_bootstrap

        try:
            maybe_enqueue_dcs_after_bootstrap(company)
        except Exception:  # noqa: BLE001 — never fail owner save because of DCS enqueue
            logger.exception(
                "DCS enqueue after Manago primary owner set failed company_id=%s",
                company.id,
            )

        return Response(
            _manago_owners_response(
                connector=connector,
                config=config,
                owners=owners or [config["owner"]],
            )
        )


class ManagoApiV3KeyView(APIView):
    """PUT/DELETE /api/v1/connectors/manago_ai/api-v3-key/ (PRD-CONN-06)."""

    permission_classes = [IsAuthenticated]

    def put(self, request):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to update connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = _get_manago_connector(company=company)
        if connector is None:
            return Response(
                {"detail": "Manago connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        raw_key = request.data.get("api_v3_key")
        if not isinstance(raw_key, str):
            return Response(
                {"api_v3_key": ["Enter an API v3 key."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        api_v3_key = raw_key.strip()
        if not api_v3_key:
            return Response(
                {"api_v3_key": ["Enter an API v3 key."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(api_v3_key) < _MANAGO_API_V3_KEY_MIN_LENGTH:
            return Response(
                {"api_v3_key": ["Enter a valid API v3 key."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = decrypt_connector_config(connector.config)
        config["api_v3_key"] = api_v3_key
        connector.config = encrypt_config(config)
        connector.save(update_fields=["config", "updated_at"])

        append_audit_event(
            company=company,
            action="connector.manago_api_v3_key_set",
            summary="Manago API v3 key updated",
            performed_by=user.email,
            actor_user_id=str(user.id),
            metadata={
                "platform": PLATFORM_MANAGO,
                "connector_id": str(connector.id),
            },
        )

        return Response(_manago_api_v3_key_response(connector))

    def delete(self, request):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to update connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = _get_manago_connector(company=company)
        if connector is None:
            return Response(
                {"detail": "Manago connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        config = decrypt_connector_config(connector.config)
        had_key = has_api_v3_key_in_config(config)
        config.pop("api_v3_key", None)
        connector.config = encrypt_config(config)
        connector.save(update_fields=["config", "updated_at"])

        if had_key:
            append_audit_event(
                company=company,
                action="connector.manago_api_v3_key_removed",
                summary="Manago API v3 key removed",
                performed_by=user.email,
                actor_user_id=str(user.id),
                metadata={
                    "platform": PLATFORM_MANAGO,
                    "connector_id": str(connector.id),
                },
            )

        return Response(
            {
                "platform": PLATFORM_MANAGO,
                "has_api_v3_key": False,
            }
        )


class ConnectorDisconnectView(APIView):
    """
    Disconnect (remove) a connector belonging to the user's company.

    Works for any connector name (shopify, manago_ai). Deleting the row
    matches the create endpoints, which treat row existence as "connected",
    so the connector can be re-added afterwards.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        user = request.user
        if user.role not in (User.Role.ADMIN, User.Role.ANALYST):
            return Response(
                {"detail": "You do not have permission to remove connectors."},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = _user_company(user)
        if company is None:
            return Response(
                {"detail": "Company not found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        connector = Connector.objects.filter(pk=pk, company=company).first()
        if connector is None:
            return Response(
                {"detail": "Connector not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        connector_id = str(connector.id)
        connector_name = connector.name
        append_audit_event(
            company=company,
            action="connector.disconnected",
            summary=f"{_connector_display_name(connector_name)} disconnected",
            performed_by=user.email,
            tone=AuditLog.Tone.RISK,
            actor_user_id=str(user.id),
            metadata={
                "platform": connector_name,
                "connector_id": connector_id,
            },
        )
        connector.delete()

        needs_connector = not Connector.objects.filter(
            company=company, status="connected"
        ).exists()

        return Response(
            {
                "detail": "Connector disconnected.",
                "id": connector_id,
                "name": connector_name,
                "needs_connector": needs_connector,
            },
            status=status.HTTP_200_OK,
        )
