from aiify.profile import Profile, When
from aiify.prompting import active_rules, build_message, command_for


def test_first_message_has_orientation_then_state_rules_text():
    p = Profile(instructions="Be brief about genotypes.")
    rules = [When(lambda s: s["view"] == "plots", "Plots are open; prefer plot.* actions."),
             When(lambda s: s["view"] == "files", "never shown")]
    msg = build_message("make a bar plot", app="CW", profile=p, state={"view": "plots"},
                        first=True, rules=rules, guide="CW analyses PER2 recordings.",
                        command="aiify --app CW")
    order = [msg.index(x) for x in ("built into the app CW", "Be brief", "aiify --app CW action.run",
                                    "CW analyses PER2", "[App state now]", "Plots are open",
                                    "make a bar plot")]
    assert order == sorted(order)
    assert "never shown" not in msg and "ui tree" not in msg
    assert "--confirm" in msg


def test_later_messages_skip_orientation():
    msg = build_message("again", app="CW", profile=Profile(instructions="X-INSTR"), state={"n": 1})
    assert "X-INSTR" not in msg and "built into" not in msg
    assert msg.startswith('[App state now] {"n":1}') and msg.endswith("again")


def test_profile_rules_and_callable_instructions():
    p = Profile(instructions=lambda s: f"view is {s['view']}",
                rules=[When(lambda s: True, "profile rule")])
    msg = build_message("t", app="A", profile=p, state={"view": "v"}, first=True, command="c")
    assert "view is v" in msg and "- profile rule" in msg


def test_broken_rule_counts_as_false_and_ui_help_optional():
    assert active_rules([When(lambda s: s["missing"], "x")], {}) == []
    msg = build_message("t", app="A", profile=Profile(), first=True, command="c", ui=True)
    assert "c ui tree" in msg


def test_long_state_is_cut():
    msg = build_message("t", app="A", profile=Profile(), state={"rows": list(range(5000))})
    assert "...(cut)" in msg


def test_command_uses_full_python_path():
    cmd = command_for("CW", python=r"C:\Program Files\Py\python.exe")
    assert cmd == '"C:\\Program Files\\Py\\python.exe" -m aiify --app CW'
