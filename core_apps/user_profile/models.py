from django.db import models
from typing import Any 
from django.conf import settings
from django.contrib.auth import get_user_model 
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _ 
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from cloudinary.models import CloudinaryField
from django.core.validators import MinValueValidator, MaxValueValidator

from core_apps.common.models import TimeStampedModel
# Create your models here.


User = get_user_model() 

class Profile(TimeStampedModel):
    class Salutation(models.TextChoices):
        MR = ("mr",_("Mr"),)
        MRS = ("mrs",_("Mrs"),)
        MISS = ("miss",_("Miss"),)
    
    class Gender(models.TextChoices):
        MALE = ("male", _("Male"),)
        FEMALE = ("female", _("Female"),)

    class MaritalStatus(models.TextChoices):
        MARRIED = ("married", _("Married"),)
        SINGLE = ("single", _("Single"),)
        DIVORCED = ("divorced", _("Divorced"),)
        WIDOWED = ("widowed", _("Widowed"),)
        SEPARATED = ("separated", _("Separated"),)
        Unknown = ("unknown",_("Unknown"),)

    class IdentificationMeans(models.TextChoices):
        DRIVERS_LICENSE = ("driver_license", _("Driver License"),)
        NATIONAL_ID = ("national_id", _("National ID"),)
        PASSPORT = ("passport", _("Passport"),)

    class EmploymentStatus(models.TextChoices):
        SELF_EMPLOYED = ("self_employed", _("Self Employed"),)
        EMPLOYED = ("employed", _("employed"),)
        UNEMPLOYED = ("unemployed", _("unemployed"),)
        RETIRED = ("retired", _("Retired"),)
        STUDENT = ("student", _("Student"),)

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    title = models.CharField(_("Salutation"), max_length=10,  choices=Salutation.choices, default=Salutation.MR)
    gender = models.CharField(_("Gender"), max_length=8, choices=Gender.choices, default=Gender.MALE)
    date_of_birth = models.DateField(_("Date Of Birth"), default=settings.DEFAULT_BIRTH_DATE)
    country_of_birth = CountryField(_("Country Of Birth"), default=settings.DEFAULT_COUNTRY)
    place_of_birth = models.CharField(_("Place Of Birth"), max_length=50, default="Unknown")
    marital_status = models.CharField(_("Marital Status"), max_length=20, choices=MaritalStatus.choices, default=MaritalStatus.Unknown)
    means_of_identification = models.CharField(_("Means Of Identification"), max_length=20, choices=IdentificationMeans.choices, default=IdentificationMeans.DRIVERS_LICENSE)
    id_issue_date = models.DateField(_("ID or Passport Issue Date"), default=settings.DEFAULT_DATE)
    id_expiry_date = models.DateField(_("ID or Passport Expiry Date"), default=settings.DEFAULT_EXPIRY_DATE)
    id_number = models.CharField(_("ID Number"), max_length=20, blank=True, null=True)
    nationality = models.CharField(_("Nationality"), max_length=30, default="Unknown")
    phone_number = PhoneNumberField(_("Phone Number"), max_length=30, default=settings.DEFAULT_PHONE_NUMBER)
    address = models.CharField(_("Address"), max_length=100, default="Unknown") 
    city = models.CharField(_("City"), max_length=100, default="Unknown")
    country = CountryField(_("Country"), default=settings.DEFAULT_COUNTRY)
    employment_status = models.CharField(_("Employment Status"), max_length=20, choices=EmploymentStatus.choices, default=EmploymentStatus.SELF_EMPLOYED)
    photo = CloudinaryField(_("Photo"), blank=True, null=True)
    photo_url = models.URLField(_("Photo URL"), blank=True, null=True)
    id_photo = CloudinaryField(_("ID Photo"), blank=True, null=True) 
    id_photo_url = models.URLField(_("ID Photo URL"), blank=True, null=True)
    signature_photo = CloudinaryField(_("Signature Photo"), blank=True, null=True)
    signature_photo_url = models.URLField(_("Signature Photo URL"), blank=True, null=True)

    def clean(self) -> None:
        super().clean()
        if self.id_issue_date and self.id_expiry_date:
            if self.id_expiry_date <= self.id_issue_date:
                raise ValidationError(
                    _("ID expiry date must come after issue date.")
                )
            
    def save(self, *args:Any, **kwargs:Any) -> None:
        self.full_clean() 
        super().save(*args, **kwargs) 
        
        
    def is_complete_with_next_of_kin(self) -> bool:
        required_fields = [
            self.title,
            self.gender,
            self.date_of_birth,
            self.country_of_birth,
            self.place_of_birth,
            self.marital_status,
            self.means_of_identification,
            self.id_issue_date,
            self.id_expiry_date,
            self.id_number,
            self.nationality,
            self.phone_number,
            self.address,
            self.city,
            self.country,
            self.employment_status,
            self.photo,
            self.id_photo,
            self.signature_photo,
        ]
        return all(required_fields) and self.next_of_kin.exists()

    
    def __str__(self) -> str:
        return f"{self.title} {self.user.first_name}'s Profile"
    
    
class NextOfKin(TimeStampedModel):
    class Salutation(models.TextChoices):
        MR = ("mr",_("Mr"),)
        MRS = ("mrs",_("Mrs"),)
        MISS = ("miss",_("Miss"),)
        
    class Gender(models.TextChoices):
        MALE = ("male", _("Male"),)
        FEMALE = ("female", _("Female"),)
        
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="next_of_kin")
    title = models.CharField(_("Salutation"), max_length=10, choices=Salutation.choices)
    first_name = models.CharField(_("First Name"), max_length=100)
    last_name = models.CharField(_("Last Name"), max_length=100)
    other_names = models.CharField(_("Other Names"), max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(_("Date Of Birth"))
    gender = models.CharField(_("Gender"), max_length=10, choices=Gender.choices)
    relationship = models.CharField(_("Relationship"), max_length=50)
    email_address = models.EmailField(_("Email"), db_index=True, max_length=100)
    phone_number = PhoneNumberField(_("Phone Number"))
    address = models.CharField(_("Address"), max_length=100)
    city = models.CharField(_("City"), max_length=100)
    country = CountryField(_("Country"))
    is_primary = models.BooleanField(_("Is Primary Next of Kin"), default=False)
    
    def clean(self) -> None:
        super().clean()
        if self.is_primary:
            existing_primary = NextOfKin.objects.filter(profile=self.profile, is_primary=True).exclude(pk=self.pk)
            if existing_primary.exists():
                raise ValidationError(_("There can only be one primary next of kin per profile."))
            
    def save(self, *args:Any, **kwargs:Any) -> None:
        self.full_clean() 
        super().save(*args, **kwargs)
        
    def __str__(self) -> str:
        return f"{self.title} {self.first_name} {self.last_name} - Next of Kin for {self.profile.user.first_name}"
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['profile', 'is_primary'], condition=models.Q(is_primary=True), name='unique_primary_next_of_kin_per_profile')
        ]