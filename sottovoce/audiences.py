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
    # The same lesson, told for a younger child or a teenager: the pauses and the
    # checker are the same; only how much is said, and in which words, changes.
    "en-young": Audience(
        key="en-young",
        language="en-GB",
        name="English, ages 5 to 8",
        style=(
            "Describe an educational video for a blind or low-vision child aged 5 to 8. "
            "Write in English, present tense, in very short sentences of a few everyday words. "
            "Say only the one or two most important things on screen, and read short words and "
            "numbers on screen exactly. Leave out everything else. Never guess what is not "
            "visible. Do not describe people's skin colour or ethnicity. Never say 'we see'."
        ),
        extended=True,
    ),
    "en-teen": Audience(
        key="en-teen",
        language="en-GB",
        name="English, ages 14 to 18",
        style=(
            "Describe an educational video for a blind or low-vision student aged 14 to 18. "
            "Write in English, present tense, clearly and concisely. Use the subject's proper "
            "terms (for example waxing crescent, cubic metres, pH, orbit). Read text, numbers, "
            "units and formulas exactly and in full, the way a teacher says them aloud. For a "
            "diagram or graph, name its parts (axes, labels, scale, arrows) and how they relate. "
            "Never guess what is not visible. Do not describe people's skin colour or ethnicity. "
            "Never say 'we see'."
        ),
        extended=True,
    ),
    "it-young": Audience(
        key="it-young",
        language="it-IT",
        name="Italiano, 5-8 anni",
        style=(
            "Descrivi un video educativo per un bambino cieco o ipovedente di 5-8 anni. "
            "Scrivi in italiano, al presente, con frasi brevissime e parole di tutti i giorni. "
            "Dì solo le una o due cose più importanti sullo schermo e leggi esattamente le parole "
            "e i numeri brevi. Lascia fuori tutto il resto. Non indovinare ciò che non si vede. "
            "Non descrivere il colore della pelle o l'etnia delle persone. Non scrivere 'vediamo'."
        ),
        extended=True,
    ),
    "it-teen": Audience(
        key="it-teen",
        language="it-IT",
        name="Italiano, 14-18 anni",
        style=(
            "Descrivi un video educativo per uno studente cieco o ipovedente di 14-18 anni. "
            "Scrivi in italiano, al presente, in modo chiaro e conciso. Usa i termini propri della "
            "materia (per esempio luna crescente, metri cubi, pH, orbita). Leggi esattamente e per "
            "intero testi, numeri, unità di misura e formule, come li direbbe un insegnante ad alta "
            "voce. Per un diagramma o un grafico, nomina le parti (assi, etichette, scala, frecce) e "
            "come sono collegate. Non indovinare ciò che non si vede. Non descrivere il colore della "
            "pelle o l'etnia delle persone. Non scrivere 'vediamo'."
        ),
        extended=True,
    ),
}
