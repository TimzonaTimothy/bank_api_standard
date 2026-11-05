from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from loguru import logger


def send_card_top_up_email(user, amount, currency, card_number, new_balance) -> None:
    context = {
        "user": user, "amount": amount, "currency": currency,
        "card_number": card_number, "new_balance": new_balance,
        "site_name": settings.SITE_NAME,
    }
    try:
        html_email = render_to_string("emails/card_top_up_confirmation.html", context)
        email = EmailMultiAlternatives(
            _("Card Top-Up Confirmation"), strip_tags(html_email),
            settings.DEFAULT_FROM_EMAIL, [user.email],
        )
        email.attach_alternative(html_email, "text/html")
        email.send()
        logger.info(f"Card top-up confirmation email sent to: {user.email}")
    except Exception as e:
        logger.error(f"Failed to send card top-up confirmation email: {str(e)}")
