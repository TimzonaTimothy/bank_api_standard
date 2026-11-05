from django.urls import path

from .views import CardListCreateAPIView, CardDetailAPIView, CardStatusAPIView, CardTopUpAPIView

app_name = "cards"

urlpatterns = [
    path("", CardListCreateAPIView.as_view(), name="card_list_create"),
    path("<uuid:pk>/", CardDetailAPIView.as_view(), name="card_detail"),
    path("<uuid:pk>/status/", CardStatusAPIView.as_view(), name="card_status"),
    path("<uuid:pk>/top-up/", CardTopUpAPIView.as_view(), name="card_top_up"),
]
