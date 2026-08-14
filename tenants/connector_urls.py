from django.urls import path

from tenants.connector_views import (
    ConnectorBootstrapStatusView,
    ConnectorDisconnectView,
    ConnectorListCreateView,
    ConnectorVerifyView,
    ManagoApiV3KeyView,
    ManagoFetchView,
    ManagoOwnersView,
    ShopifyFetchView,
    ShopifyOAuthCallbackView,
    ShopifyOAuthStartView,
)

urlpatterns = [
    path("verify/", ConnectorVerifyView.as_view(), name="connectors-verify"),
    path(
        "shopify/start/",
        ShopifyOAuthStartView.as_view(),
        name="connectors-shopify-start",
    ),
    path(
        "shopify/callback/",
        ShopifyOAuthCallbackView.as_view(),
        name="connectors-shopify-callback",
    ),
    path(
        "shopify/fetch/",
        ShopifyFetchView.as_view(),
        name="connectors-shopify-fetch",
    ),
    path(
        "manago_ai/fetch/",
        ManagoFetchView.as_view(),
        name="connectors-manago-fetch",
    ),
    path(
        "manago_ai/owners/",
        ManagoOwnersView.as_view(),
        name="connectors-manago-owners",
    ),
    path(
        "manago_ai/api-v3-key/",
        ManagoApiV3KeyView.as_view(),
        name="connectors-manago-api-v3-key",
    ),
    path(
        "<uuid:pk>/bootstrap/",
        ConnectorBootstrapStatusView.as_view(),
        name="connectors-bootstrap-status",
    ),
    path(
        "<uuid:pk>/",
        ConnectorDisconnectView.as_view(),
        name="connectors-disconnect",
    ),
    path("", ConnectorListCreateView.as_view(), name="connectors"),
]
