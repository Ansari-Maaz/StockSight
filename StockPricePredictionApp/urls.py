from django.urls import path

from . import views

urlpatterns = [
    # Pages
    path("", views.landing, name="landing"),
    path("dashboard/", views.home, name="home"),
    path("compare/", views.compare, name="compare"),
    path("predict/", views.predict_view, name="predict"),
    path("stocks/", views.all_stocks, name="all_stocks"),
    path("details/<str:id>/", views.details, name="details"),
    path("api-docs/", views.api_docs, name="api_docs"),
    path("download/<str:id>/", views.download, name="download"),

    # JSON API
    path("api/health/", views.api_health, name="api_health"),
    path("api/history/", views.api_history, name="api_history"),
    path("api/quote/", views.api_quote, name="api_quote"),
    path("api/predict/", views.api_predict, name="api_predict"),
    path("api/search/", views.api_search, name="api_search"),
    path("api/refresh/", views.api_refresh, name="api_refresh"),
]
