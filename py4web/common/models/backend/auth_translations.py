"""Validator translation overrides for auth forms."""

from pydal.validators import Validator

VALIDATION_TRANSLATIONS = {
    "Value not allowed": "Waarde niet toegestaan",
    "Enter a value": "Vul een waarde in",
    "Password too simple (%(have)s/%(need)s)": "Wachtwoord is te eenvoudig",
}


def setup_validator_translations() -> None:
    """Install Dutch translations for selected validator messages."""
    Validator.translator = staticmethod(lambda text: VALIDATION_TRANSLATIONS.get(text, text))


__all__ = ["setup_validator_translations"]
