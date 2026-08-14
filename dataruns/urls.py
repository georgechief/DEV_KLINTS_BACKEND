from django.urls import include, path
from rest_framework.routers import DefaultRouter

from dataruns.views import DataRunViewSet

router = DefaultRouter()
router.register("", DataRunViewSet, basename="datarun")

urlpatterns = [
    path("", include(router.urls)),
]
