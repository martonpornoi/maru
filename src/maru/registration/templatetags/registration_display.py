"""Provide registration display support for the templatetags module."""

from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def money_minor(value: object, currency: str) -> str:
    """Return money minor.

    Parameters
    ----------
    value : object
        The untrusted value to normalize against the documented contract.
    currency : str
        The ISO currency code.

    Returns
    -------
    str
        The normalized text for money minor.
    """
    try:
        amount = Decimal(str(value)) / Decimal(100)
    except ArithmeticError:
        return f"{value} {currency}"
    return f"{amount:,.2f} {currency}"
