"""Human language labels from Maru's shared ISO language catalog."""

from django import template

from maru.core.localization import language_labels

register = template.Library()


@register.filter
def language_name(code: str) -> str:
    """Display the human name while retaining unknown regional codes truthfully.

    Parameters
    ----------
    code : str
        Stored language code already admitted by the owning page.

    Returns
    -------
    str
        English language name, or the exact code when the catalog lacks it.
    """
    return language_labels().get(code, code)
