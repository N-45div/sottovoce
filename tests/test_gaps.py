import pytest

from sottovoce.gaps import Gap, Span, find_gaps, speech_spans, split_long


def test_close_words_join_into_one_span():
    words = [(1.0, 1.4), (1.5, 1.9), (2.0, 2.6)]
    assert speech_spans(words) == [Span(1.0, 2.6)]


def test_a_real_pause_splits_speech():
    words = [(1.0, 1.4), (1.5, 1.9), (4.0, 4.5)]
    assert speech_spans(words) == [Span(1.0, 1.9), Span(4.0, 4.5)]


def test_words_out_of_order_are_sorted_first():
    words = [(4.0, 4.5), (1.0, 1.4)]
    assert speech_spans(words) == [Span(1.0, 1.4), Span(4.0, 4.5)]


def test_word_ending_before_it_starts_is_rejected():
    with pytest.raises(ValueError):
        speech_spans([(2.0, 1.0)])


def test_silent_video_is_one_gap():
    assert find_gaps([], 10.0) == [Gap(0.0, 10.0, 25)]


def test_gaps_keep_clear_of_dialogue():
    speech = [Span(3.0, 5.0), Span(9.0, 12.0)]
    gaps = find_gaps(speech, 20.0)
    assert gaps == [
        Gap(0.0, 2.65, 6),
        Gap(5.25, 8.65, 8),
        Gap(12.25, 20.0, 19),
    ]


def test_pause_too_short_for_min_words_is_dropped():
    speech = [Span(0.0, 4.0), Span(5.0, 9.0)]
    assert find_gaps(speech, 9.0) == []


def test_overlapping_speakers_count_until_the_last_one_stops():
    speech = [Span(1.0, 6.0), Span(2.0, 4.0), Span(10.0, 11.0)]
    gaps = find_gaps(speech, 11.0)
    assert [g.start for g in gaps] == [6.25]


def test_slower_voice_gets_fewer_words():
    fast = find_gaps([], 4.0, words_per_second=3.0)
    slow = find_gaps([], 4.0, words_per_second=2.0)
    assert fast[0].words == 12
    assert slow[0].words == 8


def test_bad_arguments_are_rejected():
    with pytest.raises(ValueError):
        find_gaps([], -1.0)
    with pytest.raises(ValueError):
        find_gaps([], 5.0, words_per_second=0)


def test_short_pauses_are_left_alone():
    gaps = [Gap(0.0, 8.0, 20)]
    assert split_long(gaps) == gaps


def test_long_pause_is_split_with_rests_between_lines():
    pieces = split_long([Gap(0.0, 25.0, 62)], max_len=10.0, rest=1.5, words_per_second=2.0)
    assert len(pieces) == 3
    assert pieces[0].start == 0.0
    assert pieces[-1].end == 25.0
    assert all(b.start - a.end == pytest.approx(1.5, abs=0.01) for a, b in zip(pieces, pieces[1:]))
    assert pieces[0].words == int((25 / 3 - 1.5) * 2.0)
