"""Internationalization constants and utilities."""

from typing import NamedTuple


class Language(NamedTuple):
    """Represents a supported language."""

    code: str
    name: str
    native_name: str


# Centralized list of supported languages
SUPPORTED_LANGUAGES = [
    Language(code="en", name="English", native_name="English"),
    Language(code="de", name="German", native_name="Deutsch"),
    Language(code="nl", name="Dutch", native_name="Nederlands"),
    Language(code="pt_BR", name="Portuguese (Brazil)", native_name="Português (Brasil)"),
]

# Convenience list of just the language codes
SUPPORTED_LANGUAGE_CODES = [lang.code for lang in SUPPORTED_LANGUAGES]

# Default language
DEFAULT_LANGUAGE = "en"
