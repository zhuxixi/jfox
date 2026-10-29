"""init 默认切库语义（#584）：显式 flag 优先，未指定时仅 default 库切换。"""

from jfox.kb_manager import should_switch_default


class TestShouldSwitchDefault:
    def test_default_kb_without_flag_switches(self):
        assert should_switch_default("default", None) is True

    def test_named_kb_without_flag_does_not_switch(self):
        assert should_switch_default("test_abc123", None) is False

    def test_named_kb_with_explicit_default_switches(self):
        assert should_switch_default("work", True) is True

    def test_named_kb_with_explicit_no_default_does_not_switch(self):
        assert should_switch_default("work", False) is False

    def test_canonical_default_with_explicit_no_default_does_not_switch(self):
        assert should_switch_default("default", False) is False


class TestInitCliWiring:
    def test_named_kb_without_flag_keeps_current(self, cli, temp_kb):
        before = cli.kb_current().json()["name"]
        other = temp_kb.parent / "other_kb"
        result = cli._run("init", "--name", "other_kb", "--path", str(other))
        assert result.success
        assert cli.kb_current().json()["name"] == before
        cli._run("kb", "remove", "other_kb", "--force")

    def test_named_kb_with_default_flag_switches(self, cli, temp_kb):
        other = temp_kb.parent / "other_kb2"
        result = cli._run("init", "--name", "other_kb2", "--path", str(other), "--default")
        assert result.success
        assert cli.kb_current().json()["name"] == "other_kb2"
        cli._run("kb", "remove", "other_kb2", "--force")
