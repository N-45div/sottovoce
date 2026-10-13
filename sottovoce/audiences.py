"""Who a description is written for, and the house style for each audience."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Audience:
    key: str
    language: str
    name: str
    style: str
    extended: bool = False


_ITALIAN_RULES = (
    "Scrivi in italiano, al presente, in terza persona. "
    "Descrivi solo ciò che è visibile: prima le azioni, poi il luogo, poi l'aspetto. "
    "Non interpretare le emozioni se non sono evidenti sul volto. "
    "Non usare un nome finché il dialogo non lo ha detto. "
    "Non scrivere 'vediamo' o 'si vede', e non usare termini di regia."
)

AUDIENCES: dict[str, Audience] = {
    "it": Audience(
        key="it",
        language="it-IT",
        name="Audiodescrizione in italiano",
        style=_ITALIAN_RULES + " Sii essenziale: una frase breve per pausa.",
    ),
    "en": Audience(
        key="en",
        language="en-GB",
        name="English audio description for visitors",
        style=(
            "Write in plain English, present tense, third person, for a visitor who "
            "does not speak Italian. Describe only what is visible: actions first, then "
            "the place, then appearance. Translate any Italian text that is visible on "
            "screen. Never say 'we see' and avoid camera jargon."
        ),
    ),
    "extended": Audience(
        key="extended",
        language="it-IT",
        name="Audiodescrizione estesa",
        style=_ITALIAN_RULES
        + " Il video si mette in pausa per te: descrivi anche il luogo e i dettagli utili.",
        extended=True,
    ),
}
