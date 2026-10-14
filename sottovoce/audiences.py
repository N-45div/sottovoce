"""Who a description is written for: blind and low-vision children learning from video."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Audience:
    key: str
    language: str
    name: str
    style: str
    extended: bool = False


# Lessons rarely pause, so both audiences use extended description: the video
# holds while a line is spoken, and a child never misses what the teacher shows.
AUDIENCES: dict[str, Audience] = {
    "it": Audience(
        key="it",
        language="it-IT",
        name="Italiano, per bambini",
        style=(
            "Descrivi un video educativo per un bambino cieco o ipovedente di 8-13 anni. "
            "Scrivi in italiano, al presente, con frasi brevi e parole semplici. "
            "Dì cosa mostra l'insegnante: leggi esattamente le parole, i numeri e le formule "
            "scritti sullo schermo, e leggi le formule come le direbbe un insegnante ad alta voce. "
            "Spiega i disegni e i grafici per come sono fatti: cosa è disegnato, le etichette, "
            "le frecce, cosa sale o scende. Descrivi ogni passaggio di un esperimento. "
            "Non descrivere dettagli decorativi e non indovinare ciò che non si vede. "
            "Non descrivere il colore della pelle o l'etnia delle persone. "
            "Non scrivere 'vediamo' o 'si vede'."
        ),
        extended=True,
    ),
    "en": Audience(
        key="en",
        language="en-GB",
        name="English, for children",
        style=(
            "Describe an educational video for a blind or low-vision child aged 8 to 13. "
            "Write in English, present tense, in short sentences with simple words. "
            "Say what the teacher shows: read the words, numbers and formulas on screen "
            "exactly, and read formulas the way a teacher would say them aloud. Explain "
            "drawings and charts by how they are built: what is drawn, the labels, the arrows, "
            "what goes up or down. Describe each step of an experiment. Skip decoration and "
            "never guess what is not visible. Do not describe people's skin colour or "
            "ethnicity. Never say 'we see'."
        ),
        extended=True,
    ),
}
