from typing import Any

from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response

from core_apps.common.renderers import GenericJSONRenderer
from core_apps.user_profile.views import StandardResultsSetPagination
from .models import VirtualCard
from .serializers import CardSerializer, CreateCardSerializer, CardTopUpSerializer, CardStatusSerializer
from .utils import top_up_card
from core_apps.accounts.services import execute_idempotently


class CardQuerysetMixin:
    renderer_classes = [GenericJSONRenderer]
    object_label = "card"

    def get_queryset(self):
        return VirtualCard.objects.filter(
            bank_account__user=self.request.user,
        ).select_related("bank_account", "bank_account__user")


class CardListCreateAPIView(CardQuerysetMixin, generics.ListCreateAPIView):
    pagination_class = StandardResultsSetPagination
    object_label = "cards"

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateCardSerializer
        return CardSerializer


class CardDetailAPIView(CardQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = CardSerializer


class CardStatusAPIView(CardQuerysetMixin, generics.UpdateAPIView):
    serializer_class = CardStatusSerializer
    http_method_names = ["patch", "options"]


class CardTopUpAPIView(CardQuerysetMixin, generics.GenericAPIView):
    serializer_class = CardTopUpSerializer

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return execute_idempotently(request, "card_top_up", lambda: self.top_up(request))

    def top_up(self, request):
        instance = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = top_up_card(request.user, instance.pk, serializer.validated_data["amount"])
        return Response(
            {"message": "Card topped up successfully", "data": CardSerializer(card).data},
            status=status.HTTP_200_OK,
        )
