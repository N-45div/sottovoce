import random

from sottovoce.bench import Trial, plant_error, summarize


def test_a_known_word_is_swapped_for_something_not_on_screen():
    line, change = plant_error("Un uomo punta un fucile dal balcone.", "it", random.Random(1))
    assert line != "Un uomo punta un fucile dal balcone."
    assert change.split(" -> ")[0] in {"uomo", "fucile", "balcone"}
    assert change.split(" -> ")[1] in line


def test_a_line_with_no_known_word_gets_an_object_added():
    line, change = plant_error("Schermo vuoto.", "en", random.Random(1))
    assert line == "Schermo vuoto. A white dog sleeps nearby."
    assert change == "inserted an object"


def test_english_swaps_respect_word_boundaries():
    line, _ = plant_error("A manager waves at the woman.", "en", random.Random(3))
    assert "manager" in line


def test_summary_counts_catches_and_false_alarms():
    trials = [
        Trial(1.0, "original", "a", "", False, []),
        Trial(1.0, "planted", "b", "x", True, ["p"]),
        Trial(5.0, "original", "c", "", True, ["p"]),
        Trial(5.0, "planted", "d", "y", False, []),
    ]
    assert summarize(trials) == {
        "lines": 2, "planted_errors": 2, "caught": 1, "catch_rate": 0.5,
        "false_alarms": 1, "false_alarm_rate": 0.5,
    }
