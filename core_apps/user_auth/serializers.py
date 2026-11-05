from django.contrib.auth import get_user_model
from djoser.serializers import (
    UserCreateSerializer as DjoserUserCreateSerializer,
)

User = get_user_model()


class UserCreateSerializer(DjoserUserCreateSerializer):
    class Meta(DjoserUserCreateSerializer.Meta):
        model = User 
        fields = [
            "password",
            "email", 
            "username",
            "first_name",
            "last_name",
            "id_no",
            "security_question",
            "security_answer"
        ]

        extra_kwargs = {
            "security_answer": {"write_only": True},
            "password": {"write_only": True},
            "username": {"read_only": True},
        }

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user
