from __future__ import annotations

from pathlib import Path

import click
import pytest

from scripts.generate_docs import (
    NormalizedCommand,
    NormalizedParameter,
    extract_commands,
    load_descriptions,
    normalize_parameter,
    render_reference,
    validate_descriptions,
)


def test_command_tree_extract_includes_nested_paths_and_never_runs_callbacks():
    callback_calls: list[str] = []

    @click.command()
    def leaf():
        callback_calls.append("leaf")

    @click.command()
    def nested_leaf():
        callback_calls.append("nested-leaf")

    nested = click.Group("nested", commands={"leaf": nested_leaf})
    root = click.Group("root", commands={"z-leaf": leaf, "nested": nested})

    commands = extract_commands(root, root_name="jfox")

    assert [command.path for command in commands] == [
        "jfox",
        "jfox nested",
        "jfox nested leaf",
        "jfox z-leaf",
    ]
    assert commands[0].is_group is True
    assert commands[1].is_group is True
    assert commands[2].is_group is False
    assert callback_calls == []


def test_parameter_normalize_argument_uses_metavar_and_required_status():
    argument = click.Argument(["query"], required=True, metavar="QUERY")

    normalized = normalize_parameter(argument)

    assert normalized == NormalizedParameter(
        name="query",
        kind="argument",
        syntax="QUERY",
        type_name="TEXT",
        required=True,
        default="—",
        choices=(),
        multiple=False,
        is_flag=False,
    )


def test_parameter_normalize_option_preserves_aliases_type_default_and_choices():
    option = click.Option(
        ["--mode", "-m"],
        type=click.Choice(["fast", "slow"]),
        default="fast",
        show_default=True,
        required=True,
    )

    normalized = normalize_parameter(option)

    assert normalized.name == "mode"
    assert normalized.kind == "option"
    assert normalized.syntax == "--mode, -m"
    assert normalized.type_name == "CHOICE"
    assert normalized.required is True
    assert normalized.default == "fast"
    assert normalized.choices == ("fast", "slow")
    assert normalized.multiple is False
    assert normalized.is_flag is False


def test_parameter_normalize_boolean_option_renders_secondary_flag_and_boolean_default():
    option = click.Option(["--color/--no-color"], default=False)

    normalized = normalize_parameter(option)

    assert normalized.syntax == "--color / --no-color"
    assert normalized.type_name == "BOOL"
    assert normalized.default == "false"
    assert normalized.is_flag is True


def test_parameter_normalize_multiple_option_marks_multiple_values():
    option = click.Option(["--tag"], multiple=True, type=str)

    normalized = normalize_parameter(option)

    assert normalized.syntax == "--tag"
    assert normalized.multiple is True
    assert normalized.type_name == "TEXT"


def test_parameter_normalize_integer_default():
    option = click.Option(["--top"], type=int, default=5)

    normalized = normalize_parameter(option)

    assert normalized.type_name == "INTEGER"
    assert normalized.default == "5"


def test_parameter_normalize_boolean_option_with_extra_aliases():
    option = click.Option(["--color/--no-color", "-c"], default=False)

    normalized = normalize_parameter(option)

    assert normalized.syntax == "--color, -c / --no-color"
    assert normalized.type_name == "BOOL"
    assert normalized.is_flag is True


def test_command_usage_marks_optional_positional_arguments():
    @click.command()
    @click.argument("required_arg", required=True, metavar="REQUIRED")
    @click.argument("optional_arg", required=False, metavar="OPTIONAL")
    def command(required_arg, optional_arg):
        return required_arg, optional_arg

    commands = extract_commands(click.Group("root", commands={"command": command}))

    command_record = next(item for item in commands if item.path == "jfox command")
    assert command_record.usage == "jfox command REQUIRED [OPTIONAL]"


def test_description_load_reads_prose_only_catalog(tmp_path: Path):
    catalog = tmp_path / "descriptions.yaml"
    catalog.write_text(
        """commands:\n  jfox:\n    description: Manage notes.\n  jfox add:\n    description: Create a note.\n""",
        encoding="utf-8",
    )

    assert load_descriptions(catalog) == {
        "jfox": "Manage notes.",
        "jfox add": "Create a note.",
    }


def test_description_load_rejects_duplicate_command_keys(tmp_path: Path):
    catalog = tmp_path / "descriptions.yaml"
    catalog.write_text(
        """commands:\n  jfox:\n    description: First.\n  jfox:\n    description: Second.\n""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate YAML key.*jfox"):
        load_descriptions(catalog)


def test_description_load_rejects_malformed_or_non_prose_schema(tmp_path: Path):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("commands: [", encoding="utf-8")
    with pytest.raises(ValueError, match="failed to parse"):
        load_descriptions(malformed)

    extra_field = tmp_path / "extra.yaml"
    extra_field.write_text(
        """commands:\n  jfox:\n    description: Manage notes.\n    options: []\n""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields.*jfox"):
        load_descriptions(extra_field)


def test_description_load_rejects_missing_or_invalid_descriptions(tmp_path: Path):
    missing_root = tmp_path / "missing-root.yaml"
    missing_root.write_text("other: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="top-level 'commands'"):
        load_descriptions(missing_root)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        """commands:\n  jfox:\n    description: \"\"\n  jfox add:\n    description: 42\n""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-empty string.*jfox"):
        load_descriptions(invalid)


def test_description_validate_reports_missing_and_unknown_paths():
    with pytest.raises(ValueError, match="Missing English CLI descriptions: jfox add"):
        validate_descriptions(["jfox", "jfox add"], {"jfox": "Manage notes."})

    with pytest.raises(ValueError, match="Unknown CLI description entries: jfox old"):
        validate_descriptions(["jfox"], {"jfox": "Manage notes.", "jfox old": "Old."})


def test_description_validate_accepts_complete_catalog():
    validate_descriptions(
        ["jfox", "jfox add"],
        {"jfox": "Manage notes.", "jfox add": "Create a note."},
    )


def test_description_load_rejects_unknown_top_level_keys(tmp_path: Path):
    catalog = tmp_path / "unknown-top-level.yaml"
    catalog.write_text(
        """commands:\n  jfox:\n    description: Manage notes.\nmetadata: {}\n""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported top-level fields.*metadata"):
        load_descriptions(catalog)


def _sample_commands() -> tuple[NormalizedCommand, ...]:
    return (
        NormalizedCommand(
            path="jfox",
            is_group=True,
            usage="jfox [OPTIONS] COMMAND [ARGS]...",
            description_key="jfox",
            parameters=(),
        ),
        NormalizedCommand(
            path="jfox search",
            is_group=False,
            usage="jfox search [OPTIONS] QUERY",
            description_key="jfox search",
            parameters=(
                NormalizedParameter(
                    name="query",
                    kind="argument",
                    syntax="QUERY",
                    type_name="TEXT",
                    required=True,
                    default="—",
                    choices=(),
                    multiple=False,
                    is_flag=False,
                ),
                NormalizedParameter(
                    name="mode",
                    kind="option",
                    syntax="--mode, -m",
                    type_name="TEXT",
                    required=False,
                    default="hybrid",
                    choices=("hybrid", "keyword"),
                    multiple=False,
                    is_flag=False,
                ),
            ),
        ),
    )


def test_render_reference_is_english_and_deterministic():
    commands = _sample_commands()
    descriptions = {
        "jfox": "Manage a local-first knowledge base.",
        "jfox search": "Search notes by keyword or meaning.",
    }

    first = render_reference(commands, descriptions)
    second = render_reference(commands, descriptions)

    assert first == second
    assert first.startswith("<!--\nThis file is generated by scripts/generate_docs.py.")
    assert "uv run python scripts/generate_docs.py" in first
    assert "# JFox CLI Reference" in first
    assert "## `jfox search`" in first
    assert "Search notes by keyword or meaning." in first
    assert "```text\njfox search [OPTIONS] QUERY\n```" in first
    assert "| Parameter | Syntax | Type | Required | Default | Choices | Multiple | Flag |" in first
    assert (
        "| `mode` | `--mode, -m` | TEXT | no | `hybrid` | `hybrid`, `keyword` | no | no |" in first
    )
    assert "—" in first
    assert "\x1b[" not in first
    assert "/home/" not in first
    assert "2026-" not in first
    assert "搜索" not in first


def test_render_reference_uses_stable_command_order_and_newlines():
    commands = tuple(reversed(_sample_commands()))
    descriptions = {
        "jfox": "Manage notes.",
        "jfox search": "Search notes.",
    }

    rendered = render_reference(commands, descriptions)

    assert rendered.index("## `jfox`") < rendered.index("## `jfox search`")
    assert "\r" not in rendered
    assert rendered.endswith("\n")
