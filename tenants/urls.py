from django.urls import include, path
from rest_framework.routers import DefaultRouter

from tenants.views import TenantViewSet

router = DefaultRouter()
router.register("", TenantViewSet, basename="tenant")

urlpatterns = [
    path("", include(router.urls)),
]
