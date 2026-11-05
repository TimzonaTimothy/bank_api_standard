from django.contrib import admin
from django.utils.translation import gettext_lazy as _ 
from .models import BankAccount, Transaction, StaffAuditLog
from django.contrib.auth import get_user_model 

User = get_user_model()
# Register your models here.

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = [
        'account_number',
        'user',
        'currency',
        'account_type',
        'account_balance',
        'account_status',
        'is_primary', 
        'kyc_verified',
        'get_verified_by',
    ]
    list_filter = [
        'currency',
        'account_type',
        'account_status',
        'is_primary',
        'kyc_submitted',
        'kyc_verified',
    ]
    
    search_fields = [
        'account_number',
        'user__email',
        'user__first_name',
        'user__last_name',
    ]
    
    readonly_fields =[
        'account_number',
        'account_balance',
        'user',
        'currency',
        'account_type',
        'created_at', 
        'updated_at',
    ]
    
    fieldsets = (
        (
            None,
            {
                "fields": (
                    'user',
                    'account_number',
                    'account_balance',
                    'currency', 
                    'account_type',
                    'is_primary'
                )
            }, 
        ),
        (
            _('Status'),
            {
                "fields": (
                    "account_status",
                    'kyc_submitted',
                    'kyc_verified',
                    'verification_date',
                    'fully_activated',
                    'verfication_notes'
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields":("created_at","updated_at"),
                "classes": ("collapse",),
                
            },
        ),
    )
    
    def get_verified_by(self, obj):
        return obj.verified_by.full_name if obj.verified_by else "-"
    
    get_verified_by.short_description = "Verified By"
    get_verified_by.admin_order_field = "verified_by__first_name"


    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs 
        
        return qs.filter(verified_by=request.user)
    
    def has_change_permission(self, request, obj=None):
        if not obj:
            return True 
        return request.user.is_superuser or obj.verified_by == request.user 

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "verified_by":
            kwargs['queryset'] = User.objects.filter(is_staff=True) 
        return super().formfield_for_foreignkey(db_field,request,**kwargs)



    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from django.db import transaction
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            StaffAuditLog.objects.create(
                actor=request.user, action='bank_account_admin_update', object_id=obj.pk,
                details={'fields': list(form.changed_data)},
            )


@admin.register(Transaction, StaffAuditLog)
class FinancialAuditAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
