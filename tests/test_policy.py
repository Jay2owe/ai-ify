from aiify.policy import Policy


def test_default_runs_everything_but_destructive_asks():
    p = Policy()
    assert p.check("plot.bar") == "run"
    assert p.check("clear_output", {"destructive": True}) == "confirm"


def test_design_example_profiles():
    quick = Policy.from_lists(allow=["inspect.*"])
    assert quick.check("inspect.recordings") == "run"
    assert quick.check("plot.bar") == "deny"
    analyst = Policy.from_lists(allow=["*"], confirm=["*.delete", "batch.*"])
    assert analyst.check("samples.delete") == "confirm"
    assert analyst.check("batch.run") == "confirm"
    assert analyst.check("plot.bar") == "run"


def test_deny_beats_allow():
    p = Policy.from_lists(allow=["*"], deny=["admin.*"])
    assert p.check("admin.reset") == "deny"
    assert not p.visible("admin.reset")
