from productbot.conversation import build_handler


def test_handler_builds():
    h = build_handler()
    assert len(h.states) == 5 and h.entry_points
