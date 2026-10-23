"""Normalización de nombres de equipos para comparar lo que escribe el usuario (o el LLM) con los nombres canónicos."""

import unicodedata


def normalize_name(name: str) -> str:
    """Minúsculas, sin acentos ni puntuación: 'Ñublense' = 'nublense' y 'Colo-Colo' = 'Colo Colo'."""
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(c if c.isalnum() else " " for c in text if not unicodedata.combining(c))
    return " ".join(text.split())
