from django.db import models
import uuid 
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.utils import timezone 
from django.utils.translation import gettext_lazy as _ 
# Create your models here.

from .emails import send_account_locked_email
from .managers import UserManager
from django.db import transaction


class User(AbstractUser):
    class SecurityQuestions(models.TextChoices):
        MAIDEN_NAME = (
            "maiden_name",
            _("What is your mother's maiden name?"),
        )
        FAVORITE_COLOR = (
            "favorite_color",
            _("What is your favorite color?")
        )
        BIRTH_CITY = (
            "birth_city",
            _("What is the city where you were born?")
        )
        CHILDHOOD_FRIEND = (
            "childhood_friend",
            _("What is the name of your childhood best friend?")
        )

    class AccountStatus(models.TextChoices):
        ACTIVE = "active", _("Active")
        LOCKED = "locked", _("Locked")

    class RoleChoices(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        ACCOUNT_EXECUTIVE = "account_executive", _("Account Executive") 
        TELLER = "teller", _("Teller")
        BRANCH_MANAGER = "branch_manager", _("Branch Manager")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    username = models.CharField(_("username"), max_length=12, unique=True)
    security_question = models.CharField(
        _("Security Question"), 
        max_length=30, 
        choices=SecurityQuestions.choices, 
    )
    security_answer = models.CharField(_("Security Answer"), max_length=128)
    email = models.EmailField(_("Email"), unique=True, db_index=True)
    first_name = models.CharField(_("First Name"), max_length=30) 
    middle_name = models.CharField(_("Middle name"), max_length=30, blank=True, null=True) 
    last_name = models.CharField(_("Last Name"), max_length=30) 
    id_no = models.PositiveIntegerField(_("ID Number"), unique=True) 
    account_status = models.CharField(
        _("Account Status"), 
        max_length=10, 
        choices=AccountStatus.choices, 
        default=AccountStatus.ACTIVE, 
    )
    role = models.CharField(
        _("Role"), max_length=20, 
        choices=RoleChoices.choices, 
        default=RoleChoices.CUSTOMER
    )
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    auth_version = models.PositiveIntegerField(default=0)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = [
        "first_name",
        "last_name",
        "id_no",
        "security_question", 
        "security_answer",
    ]

    def handle_failed_login_attempts(self) -> None:
        self.failed_login_attempts +=1
        self.last_failed_login = timezone.now()
        if self.failed_login_attempts >= settings.LOGIN_ATTEMPTS:
            self.account_status = self.AccountStatus.LOCKED
            self.save()
            send_account_locked_email(self)
        self.save() 

    def reset_failed_login_attempts(self) -> None: 
        self.failed_login_attempts = 0
        self.last_failed_login = None 
        self.account_status = self.AccountStatus.ACTIVE 
        self.save() 

    def unlock_account(self) -> None:
        if self.account_status == self.AccountStatus.LOCKED:
            self.account_status = self.AccountStatus.ACTIVE
            self.failed_login_attempts = 0 
            self.last_failed_login = None 
            self.save()

    @property
    def is_locked_out(self) -> bool: 
        if self.account_status == self.AccountStatus.LOCKED:
            if(self.last_failed_login and (timezone.now() - self.last_failed_login) > settings.LOCKOUT_DURATION):
                self.unlock_account()
                return False 
            return True
        return False 
    
    @property
    def full_name(self) -> str:
        full_name = f"{self.first_name} {self.last_name}"
        return full_name.title().strip() 
    
    class Meta:
        verbose_name = _("User") 
        verbose_name_plural = _("Users")
        ordering = ["-date_joined"]

    def has_role(self, role_name: str) -> bool:
        return hasattr(self, "role") and self.role == role_name 
    
    def __str__(self):
        return f"{self.full_name} - {self.get_role_display()}"
    
    @transaction.atomic
    def save(self, *args, **kwargs):
        from django.contrib.auth.hashers import identify_hasher, make_password
        if self.security_answer:
            try:
                identify_hasher(self.security_answer)
            except ValueError:
                self.security_answer = make_password(self.security_answer)
        if self.email:
            self.email = self.email.lower()
        if self.username:
            self.username = self.username.lower()
        previous = type(self).objects.select_for_update().filter(pk=self.pk).values("password", "auth_version").first()
        if previous and previous["password"] != self.password:
            self.auth_version = previous["auth_version"] + 1
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"auth_version"}
        elif previous:
            self.auth_version = previous["auth_version"]
        super().save(*args, **kwargs)


class OTPChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otp_challenges")
    purpose = models.CharField(max_length=20)
    code_hash = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    auth_version = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    result = models.ForeignKey("accounts.Transaction", on_delete=models.PROTECT, null=True, blank=True)
