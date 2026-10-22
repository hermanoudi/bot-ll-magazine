from productbot.conversation import build_handler


def test_handler_builds():
    h = build_handler()
    assert len(h.states) == 4 and h.entry_points
