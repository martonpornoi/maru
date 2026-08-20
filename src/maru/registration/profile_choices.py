"""Code-owned attendee-profile vocabularies exposed to every client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_BIO_LENGTH = 500
MAX_SPOKEN_LANGUAGES = 5
MAX_FURSUITS = 10
OTHER_PRONOUN_CODE = "other"

# Pronouns are deliberately an extensible presentation vocabulary rather than
# an identity taxonomy. "Other" keeps the write-in escape hatch explicit.
PRONOUN_CHOICES = (
    ("she_her", "she/her"),
    ("he_him", "he/him"),
    ("they_them", "they/them"),
    ("it_its", "it/its"),
    ("one_ones", "one/one's"),
    ("ae_aer", "ae/aer"),
    ("ey_em", "ey/em"),
    ("fae_faer", "fae/faer"),
    ("xe_xem", "xe/xem"),
    ("ze_hir", "ze/hir"),
    ("ze_zir", "ze/zir"),
    ("co_cos", "co/cos"),
    ("e_em_eir", "e/em/eir"),
    ("e_em_es", "e/em/es"),
    ("hu_hum", "hu/hum"),
    ("ne_nem", "ne/nem"),
    ("ne_nir", "ne/nir"),
    ("per_per", "per/per"),
    ("s_he_hir", "s/he/hir"),
    ("thon_thons", "thon/thons"),
    ("ve_ver", "ve/ver"),
    ("vi_vir", "vi/vir"),
    ("vi_vim", "vi/vim"),
    ("zhe_zher", "zhe/zher"),
    ("ki_kin", "ki/kin"),
    ("any", "Any pronouns"),
    ("name_only", "Use my name"),
    ("ask_me", "Ask me"),
    (OTHER_PRONOUN_CODE, "Other pronouns"),
)
PRONOUN_LABELS = dict(PRONOUN_CHOICES)
PRONOUN_CODES = frozenset(PRONOUN_LABELS)

# ISO 639-1 alpha-2 is the bounded, interoperable language list used for badge
# metadata. The Library of Congress is the maintenance authority for the codes.
LANGUAGE_CHOICES = (
    ("aa", "Afar"),
    ("ab", "Abkhazian"),
    ("ae", "Avestan"),
    ("af", "Afrikaans"),
    ("ak", "Akan"),
    ("am", "Amharic"),
    ("an", "Aragonese"),
    ("ar", "Arabic"),
    ("as", "Assamese"),
    ("av", "Avaric"),
    ("ay", "Aymara"),
    ("az", "Azerbaijani"),
    ("ba", "Bashkir"),
    ("be", "Belarusian"),
    ("bg", "Bulgarian"),
    ("bh", "Bihari languages"),
    ("bi", "Bislama"),
    ("bm", "Bambara"),
    ("bn", "Bengali"),
    ("bo", "Tibetan"),
    ("br", "Breton"),
    ("bs", "Bosnian"),
    ("ca", "Catalan"),
    ("ce", "Chechen"),
    ("ch", "Chamorro"),
    ("co", "Corsican"),
    ("cr", "Cree"),
    ("cs", "Czech"),
    ("cu", "Church Slavic"),
    ("cv", "Chuvash"),
    ("cy", "Welsh"),
    ("da", "Danish"),
    ("de", "German"),
    ("dv", "Divehi"),
    ("dz", "Dzongkha"),
    ("ee", "Ewe"),
    ("el", "Greek"),
    ("en", "English"),
    ("eo", "Esperanto"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("eu", "Basque"),
    ("fa", "Persian"),
    ("ff", "Fulah"),
    ("fi", "Finnish"),
    ("fj", "Fijian"),
    ("fo", "Faroese"),
    ("fr", "French"),
    ("fy", "Western Frisian"),
    ("ga", "Irish"),
    ("gd", "Gaelic"),
    ("gl", "Galician"),
    ("gn", "Guarani"),
    ("gu", "Gujarati"),
    ("gv", "Manx"),
    ("ha", "Hausa"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("ho", "Hiri Motu"),
    ("hr", "Croatian"),
    ("ht", "Haitian"),
    ("hu", "Hungarian"),
    ("hy", "Armenian"),
    ("hz", "Herero"),
    ("ia", "Interlingua"),
    ("id", "Indonesian"),
    ("ie", "Interlingue"),
    ("ig", "Igbo"),
    ("ii", "Sichuan Yi"),
    ("ik", "Inupiaq"),
    ("io", "Ido"),
    ("is", "Icelandic"),
    ("it", "Italian"),
    ("iu", "Inuktitut"),
    ("ja", "Japanese"),
    ("jv", "Javanese"),
    ("ka", "Georgian"),
    ("kg", "Kongo"),
    ("ki", "Kikuyu"),
    ("kj", "Kuanyama"),
    ("kk", "Kazakh"),
    ("kl", "Kalaallisut"),
    ("km", "Central Khmer"),
    ("kn", "Kannada"),
    ("ko", "Korean"),
    ("kr", "Kanuri"),
    ("ks", "Kashmiri"),
    ("ku", "Kurdish"),
    ("kv", "Komi"),
    ("kw", "Cornish"),
    ("ky", "Kirghiz"),
    ("la", "Latin"),
    ("lb", "Luxembourgish"),
    ("lg", "Ganda"),
    ("li", "Limburgan"),
    ("ln", "Lingala"),
    ("lo", "Lao"),
    ("lt", "Lithuanian"),
    ("lu", "Luba-Katanga"),
    ("lv", "Latvian"),
    ("mg", "Malagasy"),
    ("mh", "Marshallese"),
    ("mi", "Maori"),
    ("mk", "Macedonian"),
    ("ml", "Malayalam"),
    ("mn", "Mongolian"),
    ("mr", "Marathi"),
    ("ms", "Malay"),
    ("mt", "Maltese"),
    ("my", "Burmese"),
    ("na", "Nauru"),
    ("nb", "Norwegian Bokmal"),
    ("nd", "North Ndebele"),
    ("ne", "Nepali"),
    ("ng", "Ndonga"),
    ("nl", "Dutch"),
    ("nn", "Norwegian Nynorsk"),
    ("no", "Norwegian"),
    ("nr", "South Ndebele"),
    ("nv", "Navajo"),
    ("ny", "Chichewa"),
    ("oc", "Occitan"),
    ("oj", "Ojibwa"),
    ("om", "Oromo"),
    ("or", "Odia"),
    ("os", "Ossetian"),
    ("pa", "Panjabi"),
    ("pi", "Pali"),
    ("pl", "Polish"),
    ("ps", "Pushto"),
    ("pt", "Portuguese"),
    ("qu", "Quechua"),
    ("rm", "Romansh"),
    ("rn", "Rundi"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("rw", "Kinyarwanda"),
    ("sa", "Sanskrit"),
    ("sc", "Sardinian"),
    ("sd", "Sindhi"),
    ("se", "Northern Sami"),
    ("sg", "Sango"),
    ("si", "Sinhala"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sm", "Samoan"),
    ("sn", "Shona"),
    ("so", "Somali"),
    ("sq", "Albanian"),
    ("sr", "Serbian"),
    ("ss", "Swati"),
    ("st", "Southern Sotho"),
    ("su", "Sundanese"),
    ("sv", "Swedish"),
    ("sw", "Swahili"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("tg", "Tajik"),
    ("th", "Thai"),
    ("ti", "Tigrinya"),
    ("tk", "Turkmen"),
    ("tl", "Tagalog"),
    ("tn", "Tswana"),
    ("to", "Tonga"),
    ("tr", "Turkish"),
    ("ts", "Tsonga"),
    ("tt", "Tatar"),
    ("tw", "Twi"),
    ("ty", "Tahitian"),
    ("ug", "Uighur"),
    ("uk", "Ukrainian"),
    ("ur", "Urdu"),
    ("uz", "Uzbek"),
    ("ve", "Venda"),
    ("vi", "Vietnamese"),
    ("vo", "Volapuk"),
    ("wa", "Walloon"),
    ("wo", "Wolof"),
    ("xh", "Xhosa"),
    ("yi", "Yiddish"),
    ("yo", "Yoruba"),
    ("za", "Zhuang"),
    ("zh", "Chinese"),
    ("zu", "Zulu"),
)
LANGUAGE_LABELS = dict(LANGUAGE_CHOICES)
LANGUAGE_CODES = frozenset(LANGUAGE_LABELS)


def pronoun_display(pronoun_code: str, other_pronouns: str = "") -> str:
    """Return the public/badge-safe pronoun label for one validated selection.

    Parameters
    ----------
    pronoun_code : str
        The stable pronoun code from the relevant closed catalog.
    other_pronouns : str, default=''
        The other pronouns evaluated while pronoun display.

    Returns
    -------
    str
        The normalized text for pronoun display.
    """
    if pronoun_code == OTHER_PRONOUN_CODE:
        return other_pronouns.strip()
    return PRONOUN_LABELS.get(pronoun_code, "")


def validate_spoken_language_codes(value: object) -> None:
    """Validate a unique, ordered ISO 639-1 selection.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not isinstance(value, list) or any(not isinstance(code, str) for code in value):
        raise ValidationError(
            "Spoken languages must be a list of ISO 639-1 codes.",
            code="invalid_spoken_languages",
        )
    normalized = [code.lower() for code in value]
    if len(normalized) > MAX_SPOKEN_LANGUAGES:
        raise ValidationError(
            f"Choose no more than {MAX_SPOKEN_LANGUAGES} spoken languages.",
            code="too_many_spoken_languages",
        )
    if len(set(normalized)) != len(normalized):
        raise ValidationError(
            "Spoken languages must be unique.",
            code="duplicate_spoken_language",
        )
    unknown = set(normalized).difference(LANGUAGE_CODES)
    if unknown:
        raise ValidationError(
            f"Unknown spoken language code: {sorted(unknown)[0]}.",
            code="unknown_spoken_language",
        )


def language_labels(codes: Iterable[str]) -> list[str]:
    """Return language labels.

    Parameters
    ----------
    codes : Iterable[str]
        The codes evaluated while language labels.

    Returns
    -------
    list[str]
        The authorized language labels records in deterministic order.
    """
    return [LANGUAGE_LABELS[code] for code in codes if code in LANGUAGE_LABELS]
