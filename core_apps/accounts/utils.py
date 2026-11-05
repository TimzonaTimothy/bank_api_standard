import secrets
from os import getenv 

from django.db import transaction
from .emails import send_account_creation_email 
from typing import Union, List
from .models import BankAccount

def generate_account_number(currency: str) -> str:
    bank_code = getenv("BANK_CODE") 
    branch_code = getenv("BANK_BRANCH_CODE")
    currency_codes = {
        "us_dollar": getenv("CURRENCY_CODE_USD"),
        "pound_sterling": getenv("CURRENCY_CODE_GBP"),
        "naira": getenv("CURRENCY_CODE_NGN")
    } 
    currency_code = currency_codes.get(currency)
    if not currency_code:
        raise ValueError(f"Invalid currency: {currency}")
    
    prefix = f"{bank_code}{branch_code}{currency_code}"
    
    remaining_digits = 16 - len(prefix) - 1
    
    random_digits = ''.join(secrets.choice("0123456789") for _ in range(remaining_digits)) 
    partial_account_number = f"{prefix}{random_digits}"  
    
    check_digit = calculate_luhn_check_digit(partial_account_number) 
    return f"{partial_account_number}{check_digit}"


def calculate_luhn_check_digit(number: str) -> int:
    def split_into_digits(n: Union[str,int]) -> List[int]:
        return [int(digit) for digit in str(n)] 
    
    digits = split_into_digits(number) 
    odd_digits = digits[-1::-2] 
    even_digits = digits[-2::-2] 
    total = sum(odd_digits) 
    for d in even_digits: 
        doubled = d * 2
        total += sum(split_into_digits(doubled)) 
        
    return (10 - (total % 10)) % 10 

def create_bank_account(user,  currency: str, account_type: str) -> str:
    with transaction.atomic(): 
        while True:
            account_number = generate_account_number(currency) 
            if not BankAccount.objects.filter(account_number=account_number).exists(): 
                break 
            
        is_primary = not BankAccount.objects.filter(user=user).exists() 
        bank_account = BankAccount.objects.create(
            user=user,
            account_number=account_number,
            currency=currency,
            account_type=account_type,
            is_primary=is_primary
        )
        send_account_creation_email(user, bank_account)
    return bank_account


@transaction.atomic
def credit_daily_savings_interest(account_id, interest_date):
    from django.conf import settings
    from django.utils import timezone
    from decimal import Decimal
    from .models import SavingsInterest, Transaction

    account = BankAccount.objects.select_for_update().get(pk=account_id)
    if (
        account.account_type != BankAccount.AccountType.SAVINGS
        or account.account_status != BankAccount.AccountStatus.ACTIVE
        or not account.kyc_verified or not account.fully_activated
        or account.account_balance <= 0
    ):
        return None
    if SavingsInterest.objects.filter(account=account, date=interest_date).exists():
        return None
    amount = account.calculate_interest()
    opening_balance = account.account_balance
    if opening_balance + amount > Decimal("9999999999.99"):
        raise ValueError("Interest credit would exceed the account balance limit.")
    record = None
    if amount > 0:
        BankAccount.objects.filter(pk=account.pk).update(
            account_balance=opening_balance + amount, updated_at=timezone.now(),
        )
        record = Transaction.objects.create(
            user=account.user, receiver=account.user, receiver_account=account,
            amount=amount, description=f"Savings interest for {interest_date}",
            transaction_type=Transaction.TransactionType.DEPOSIT,
            status=Transaction.TransactionStatus.COMPLETED,
        )
    return SavingsInterest.objects.create(
        account=account, date=interest_date, opening_balance=opening_balance,
        annual_rate=Decimal(str(settings.SAVINGS_ANNUAL_INTEREST_RATE)),
        amount=amount, transaction=record,
    )
