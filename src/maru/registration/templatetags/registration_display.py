from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def money_minor(value: object, currency: str) -> str:
    try:
        amount = Decimal(str(value)) / Decimal(100)
    except ArithmeticError:
        return f"{value} {currency}"
    return f"{amount:,.2f} {currency}"
