from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _ 
from .models import User
from .forms import UserChangeForm, UserCreationForm
# Register your models here.


@admin.register(User) 
class CustomUserAdmin(UserAdmin):
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    form = UserChangeForm 
    add_form = UserCreationForm 
    model = User
    list_display = ['email','username','first_name', 'last_name', 'is_staff', 'is_active','role',]
    list_filter = ['email', 'is_staff', 'is_active', 'role']
    fieldsets = (
        (
            _("Login Credentials"),
            {
                "fields": (
                    "username", 
                    "email",
                    "password",
                )
            },
        ),
        (
            _("Personal Information"),
            {
                "fields": (
                    "first_name",
                    "middle_name",
                    "last_name",
                    "id_no",
                    "role",
                )
            },
        ),
        (
            _("Account Status"),
            {
                "fields": (
                    "account_status",
                    "failed_login_attempts",
                    "last_failed_login",
                )
            },
        ),
        (
            _("Security"), 
            {
                "fields": (
                    "security_question",
                )
            },
        ),
        (
            _("Permissions and Groups"), 
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Important dates"),
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['email']
