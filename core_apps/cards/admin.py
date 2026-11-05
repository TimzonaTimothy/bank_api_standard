from django.contrib import admin

from .models import VirtualCard


@admin.register(VirtualCard)
class VirtualCardAdmin(admin.ModelAdmin):
    list_display = ["masked_card_number", "bank_account", "balance", "is_active", "expiry_date"]
    list_filter = ["is_active", "bank_account__currency", "expiry_date"]
    search_fields = ["bank_account__account_number", "bank_account__user__email"]
    readonly_fields = [
        "id", "bank_account", "masked_card_number", "balance", "expiry_date",
        "created_at", "updated_at",
    ]
    fields = readonly_fields + ["is_active"]
    list_select_related = ["bank_account", "bank_account__user"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
