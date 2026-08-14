from django.urls import path

from dataruns.search_views import GlobalSearchView

urlpatterns = [
    path("", GlobalSearchView.as_view(), name="global-search"),
]
