from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    
    path("api/v1/auth/", include("djoser.urls")),
    path("api/v1/auth/", include("core_apps.user_auth.urls")),
]

admin.site.site_header = "FLOW BANK API"
admin.site.site_title = "FLOW BANK API"
admin.site.index_title = "FLOW BANK API Administration"