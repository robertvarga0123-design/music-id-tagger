from music_id_tagger.judge import Vote, combine, parse_decision, review


def test_parse_decision_reads_json_object():
    parsed = parse_decision(
        'szöveg {"accept": true, "artist": "Marie Vaunt", "title": "Rave Generator", "reason": "egyezik"} utána'
    )
    assert parsed == (True, "Marie Vaunt", "Rave Generator", "egyezik")
    assert parse_decision("nem json") is None
    assert parse_decision('{"artist": "Marie Vaunt"}') is None


def test_both_accept_the_same_recording():
    verdict = combine(
        "Marie Vaunt",
        "Rave Generator",
        [
            Vote("Grok", True, "Marie Vaunt", "Rave Generator", "ok"),
            Vote("Gemini", True, "Marie Vaunt", "Rave Generator (Extended Mix)", "ok"),
        ],
    )
    assert verdict.used is True
    assert verdict.accept is True
    assert verdict.confirmed == 2


def test_one_reject_vetoes():
    verdict = combine(
        "Marie Vaunt",
        "Rave Generator",
        [
            Vote("Grok", True, "Marie Vaunt", "Rave Generator", "ok"),
            Vote("Gemini", False, "", "", "más mix"),
        ],
    )
    assert verdict.accept is False
    assert verdict.confirmed == 0


def test_two_named_accepts_that_disagree_reject():
    verdict = combine(
        "Marie Vaunt",
        "Rave Generator",
        [
            Vote("Grok", True, "Vaunt", "Generator", "a"),
            Vote("Gemini", True, "Marie", "Rave", "b"),
        ],
    )
    assert verdict.accept is False
    assert verdict.confirmed == 0


def test_accept_of_a_different_artist_rejects():
    verdict = combine(
        "Marie Vaunt",
        "Rave Generator",
        [
            Vote("Grok", True, "Markus Schulz", "Mainstage", "máshogy hallja"),
            Vote("Gemini", True, "Marie Vaunt", "Rave Generator", "egyezik"),
        ],
    )
    assert verdict.accept is False


def test_no_votes_keeps_the_old_rules():
    verdict = combine("Marie Vaunt", "Rave Generator", [])
    assert verdict.used is False
    assert verdict.accept is True
    assert verdict.confirmed == 0


def test_unparsed_answers_do_not_veto():
    verdict = combine(
        "Marie Vaunt",
        "Rave Generator",
        [
            Vote("Grok", None, reason="nem érthető válasz"),
            Vote("Gemini", None, reason="nem válaszolt"),
        ],
    )
    assert verdict.used is True
    assert verdict.accept is True
    assert verdict.confirmed == 0


def test_review_without_keys_does_not_call_out(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("a hálózatot nem szabad hívni")

    monkeypatch.setattr("music_id_tagger.judge._chat_json", boom)
    verdict = review("Marie Vaunt - Rave Generator.mp3", {}, {"artist": "Marie Vaunt", "title": "Rave Generator"}, 320, "", "")
    assert verdict.used is False
