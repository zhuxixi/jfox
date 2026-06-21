"""
测试类型: 单元测试
目标模块: jfox.cli (update 命令)
预估耗时: < 1 秒
依赖要求: 无外部依赖
"""

import json
import subprocess
from unittest.mock import patch

from typer.testing import CliRunner

from jfox.cli import (
    _detect_install_method,
    _get_installed_version,
    _is_pipx_installation,
    _is_uv_tool_installation,
    _path_has_contiguous_parts,
    _run_upgrade,
    _update_impl,
    app,
)

runner = CliRunner()


class TestDetectInstallMethod:
    """安装方式检测测试"""

    def test_dev_mode_with_git_and_pyproject(self, tmp_path):
        """源码目录 + .git + pyproject.toml 判定为 dev"""
        repo = tmp_path / "jfox"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "jfox-cli"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        package = repo / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            assert _detect_install_method() == "dev"

    def test_dev_mode_editable_install(self, tmp_path):
        """site-packages 下存在 jfox_cli.egg-link 判定为 dev"""
        site_packages = tmp_path / "lib" / "python3.11" / "site-packages"
        site_packages.mkdir(parents=True)
        (site_packages / "jfox_cli.egg-link").write_text("/path/to/src\n.", encoding="utf-8")
        package = site_packages / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            assert _detect_install_method() == "dev"

    def test_dev_mode_uv_sync_venv(self, tmp_path):
        """uv sync 场景：.venv/bin/python + 源码目录判定为 dev"""
        repo = tmp_path / "jfox"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "jfox-cli"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        venv_python = repo / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        package = repo / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli.sys.executable", str(venv_python)):
                assert _detect_install_method() == "dev"

    def test_uv_sync_venv_with_wrong_project_name_is_not_dev(self, tmp_path):
        """.venv 目录存在但 project.name 不是 jfox-cli 时不应误判为 dev"""
        repo = tmp_path / "some-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "other-project"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        venv_python = repo / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        package = repo / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli.sys.executable", str(venv_python)):
                # 没有正确的 project.name，应走默认 pip 分支
                assert _detect_install_method() == "pip"

    def test_uv_tool_installation(self, tmp_path):
        """uv tool 路径判定为 uv"""
        uv_tools = tmp_path / "uv" / "tools"
        package = uv_tools / "jfox-cli" / "lib" / "python3.11" / "site-packages" / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=uv_tools):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "uv"

    def test_pipx_installation(self, tmp_path):
        """pipx venv 路径判定为 pipx"""
        pipx_home = tmp_path / "pipx"
        package = (
            pipx_home
            / "venvs"
            / "jfox-cli"
            / "lib"
            / "python3.11"
            / "site-packages"
            / "jfox"
            / "cli.py"
        )
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=pipx_home):
                    assert _detect_install_method() == "pipx"

    def test_pip_installation_fallback(self, tmp_path):
        """普通 site-packages 路径回退为 pip"""
        site_packages = tmp_path / "site-packages"
        package = site_packages / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "pip"

    def test_dev_detection_stops_at_site_packages(self, tmp_path):
        """向上遍历时遇到 site-packages 即停止，避免误判 venv"""
        repo = tmp_path / "jfox"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "jfox-cli"\n',
            encoding="utf-8",
        )
        venv_site = repo / ".venv" / "lib" / "python3.11" / "site-packages"
        package = venv_site / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "pip"

    def test_uv_tool_installation_fallback_slice(self, tmp_path):
        """uv 二进制不可用时，通过连续路径切片判定为 uv tool"""
        uv_tools = tmp_path / "uv" / "tools"
        package = uv_tools / "jfox-cli" / "lib" / "python3.11" / "site-packages" / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "uv"

    def test_pipx_installation_fallback_slice(self, tmp_path):
        """pipx 二进制不可用时，通过连续路径切片判定为 pipx"""
        pipx_home = tmp_path / "pipx"
        package = (
            pipx_home
            / "venvs"
            / "jfox-cli"
            / "lib"
            / "python3.11"
            / "site-packages"
            / "jfox"
            / "cli.py"
        )
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "pipx"

    def test_non_contiguous_uv_path_does_not_match(self, tmp_path):
        """非连续的 uv 路径切片不应误判为 uv tool"""
        package = tmp_path / "uv" / "backup" / "tools" / "old" / "jfox-cli" / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "pip"

    def test_non_contiguous_pipx_path_does_not_match(self, tmp_path):
        """非连续的 pipx 路径切片不应误判为 pipx"""
        package = tmp_path / "pipx" / "backup" / "venvs" / "old" / "jfox-cli" / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli.__file__", str(package)):
            with patch("jfox.cli._get_uv_tool_dir", return_value=None):
                with patch("jfox.cli._get_pipx_home", return_value=None):
                    assert _detect_install_method() == "pip"


class TestIsUvToolInstallation:
    """_is_uv_tool_installation 测试"""

    def test_strict_uv_path_match(self, tmp_path):
        """主路径命中 uv tool 目录"""
        uv_tools = tmp_path / "uv" / "tools"
        package = uv_tools / "jfox-cli" / "lib" / "python3.11" / "site-packages" / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)

        with patch("jfox.cli._get_uv_tool_dir", return_value=uv_tools):
            assert _is_uv_tool_installation(package) is True

    def test_fallback_slice_match(self, tmp_path):
        """主路径失败但连续切片命中"""
        package = (
            tmp_path
            / "uv"
            / "tools"
            / "jfox-cli"
            / "lib"
            / "python3.11"
            / "site-packages"
            / "jfox"
            / "cli.py"
        )
        package.parent.mkdir(parents=True)

        with patch("jfox.cli._get_uv_tool_dir", return_value=None):
            assert _is_uv_tool_installation(package) is True


class TestIsPipxInstallation:
    """_is_pipx_installation 测试"""

    def test_strict_pipx_path_match(self, tmp_path):
        """主路径命中 pipx venv 目录"""
        pipx_home = tmp_path / "pipx"
        package = (
            pipx_home
            / "venvs"
            / "jfox-cli"
            / "lib"
            / "python3.11"
            / "site-packages"
            / "jfox"
            / "cli.py"
        )
        package.parent.mkdir(parents=True)

        with patch("jfox.cli._get_pipx_home", return_value=pipx_home):
            assert _is_pipx_installation(package) is True

    def test_fallback_slice_match(self, tmp_path):
        """主路径失败但连续切片命中"""
        package = (
            tmp_path
            / "pipx"
            / "venvs"
            / "jfox-cli"
            / "lib"
            / "python3.11"
            / "site-packages"
            / "jfox"
            / "cli.py"
        )
        package.parent.mkdir(parents=True)

        with patch("jfox.cli._get_pipx_home", return_value=None):
            assert _is_pipx_installation(package) is True


class TestPathHasContiguousParts:
    """_path_has_contiguous_parts 辅助函数测试"""

    def test_matches_contiguous_sequence(self, tmp_path):
        """完全匹配连续切片"""
        path = tmp_path / "a" / "b" / "c" / "d"
        path.mkdir(parents=True)
        assert _path_has_contiguous_parts(path, ("a", "b", "c")) is True

    def test_rejects_non_contiguous_sequence(self, tmp_path):
        """非连续切片不匹配"""
        path = tmp_path / "a" / "x" / "b" / "c"
        path.mkdir(parents=True)
        assert _path_has_contiguous_parts(path, ("a", "b", "c")) is False

    def test_rejects_longer_sequence_than_path(self, tmp_path):
        """切片长度超过路径部分数时不匹配"""
        path = tmp_path / "a"
        path.mkdir()
        assert _path_has_contiguous_parts(path, ("a", "b", "c")) is False

    def test_matches_case_insensitive(self, tmp_path):
        """大小写不一致时仍能命中"""
        path = tmp_path / "UV" / "Tools" / "JFOX-CLI"
        path.mkdir(parents=True)
        assert _path_has_contiguous_parts(path, ("uv", "tools", "jfox-cli")) is True


class TestUpdateImpl:
    """_update_impl 行为测试"""

    def test_dev_mode_returns_instruction(self):
        """dev 模式不执行升级命令，返回提示"""
        with patch("jfox.cli._detect_install_method", return_value="dev"):
            with patch("jfox.__version__", "1.0.0"):
                result = _update_impl()
                assert result["success"] is True
                assert result["method"] == "dev"
                assert "git pull" in result["message"]

    def test_uv_upgrade_success(self):
        """uv 模式下调用正确命令并返回版本对比"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["success"] is True
                        assert result["method"] == "uv"
                        assert result["command"] == "uv tool upgrade jfox-cli"
                        assert result["previous_version"] == "1.0.0"
                        assert result["current_version"] == "1.1.0"

    def test_pipx_upgrade_success(self):
        """pipx 模式下调用正确命令"""
        with patch("jfox.cli._detect_install_method", return_value="pipx"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["command"] == "pipx upgrade jfox-cli"

    def test_pip_upgrade_success(self):
        """pip 模式下调用正确命令"""
        with patch("jfox.cli._detect_install_method", return_value="pip"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert "pip install --upgrade jfox-cli" in result["command"]

    def test_pip_upgrade_in_user_site_adds_user_flag(self, tmp_path):
        """pip 用户级安装时追加 --user"""
        user_site = tmp_path / "user-site"
        user_site.mkdir(parents=True)
        package = user_site / "jfox" / "cli.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")

        with patch("jfox.cli._detect_install_method", return_value="pip"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        with patch(
                            "jfox.cli.site.getusersitepackages", return_value=str(user_site)
                        ):
                            with patch("jfox.cli.__file__", str(package)):
                                result = _update_impl()
                                assert "--user" in result["command"]

    def test_upgrade_failure_returns_manual_command(self):
        """升级失败时返回统一 schema：output/stderr/error 均存在"""
        error = subprocess.CalledProcessError(1, ["uv", "tool", "upgrade", "jfox-cli"])
        error.stderr = "network error"

        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", side_effect=error):
                    result = _update_impl()
                    assert result["success"] is False
                    assert "network error" in result["stderr"]
                    assert "network error" in result["error"]
                    assert "uv tool upgrade jfox-cli" in result["message"]

    def test_upgrade_timeout_returns_failure(self):
        """升级超时时返回统一 schema"""
        error = subprocess.TimeoutExpired(["uv", "tool", "upgrade", "jfox-cli"], timeout=300)

        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", side_effect=error):
                    result = _update_impl()
                    assert result["success"] is False
                    assert "stderr" in result
                    assert "error" in result
                    assert "uv tool upgrade jfox-cli" in result["message"]

    def test_success_separates_stdout_and_stderr(self):
        """成功路径保持统一 schema：output/stderr/error 均存在，error 为空"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "stdout msg", "stderr": "stderr msg"},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["success"] is True
                        assert result["output"] == "stdout msg"
                        assert result["stderr"] == "stderr msg"
                        assert result["error"] == ""

    def test_upgrade_already_latest_by_version(self):
        """升级前后版本一致时应标记 already_latest，不依赖工具输出文案"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.1.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Nothing to upgrade", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["success"] is True
                        assert result["already_latest"] is True
                        assert result["previous_version"] == "1.1.0"
                        assert result["current_version"] == "1.1.0"

    def test_pip_upgrade_already_latest_by_version(self):
        """pip 方式升级前后版本一致时也应正确标记 already_latest"""
        with patch("jfox.cli._detect_install_method", return_value="pip"):
            with patch("jfox.__version__", "1.1.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Requirement already satisfied", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["success"] is True
                        assert result["already_latest"] is True

    def test_pipx_upgrade_already_latest_by_version(self):
        """pipx 方式升级前后版本一致时也应正确标记 already_latest"""
        with patch("jfox.cli._detect_install_method", return_value="pipx"):
            with patch("jfox.__version__", "1.1.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "already up-to-date", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["success"] is True
                        assert result["already_latest"] is True


class TestRunUpgrade:
    """_run_upgrade 辅助函数测试"""

    def test_returns_stdout_and_stderr_separately(self):
        """分别返回 stdout 与 stderr，不合并"""
        mock_result = type(
            "obj",
            (object,),
            {"stdout": "standard output\n", "stderr": "standard error\n"},
        )()
        with patch("jfox.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = _run_upgrade(["uv", "tool", "upgrade", "jfox-cli"])
            assert result["stdout"] == "standard output"
            assert result["stderr"] == "standard error"
            mock_run.assert_called_once()


class TestUpdateCommand:
    """jfox update CLI 命令测试"""

    def test_dev_mode_shows_instruction(self):
        """dev 模式在 table 输出中显示提示"""
        with patch("jfox.cli._detect_install_method", return_value="dev"):
            with patch("jfox.__version__", "1.0.0"):
                result = runner.invoke(app, ["update"])
                assert result.exit_code == 0
                assert "开发模式" in result.output
                assert "git pull" in result.output

    def test_table_output_success(self):
        """table 输出显示版本对比"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update"])
                        assert result.exit_code == 0
                        assert "uv" in result.output
                        assert "1.0.0 → 1.1.0" in result.output

    def test_table_output_shows_stderr_separately(self):
        """成功时 stderr 在 table 输出中单独显示"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": "warning: old metadata"},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update"])
                        assert result.exit_code == 0
                        assert "Upgraded" in result.output
                        assert "warning: old metadata" in result.output

    def test_table_output_already_latest(self):
        """已是最新版本时 table 输出显示当前版本，而非升级完成"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.1.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "up-to-date", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update"])
                        assert result.exit_code == 0
                        assert "当前已是最新版本" in result.output
                        assert "1.1.0" in result.output
                        assert "→" not in result.output

    def test_table_output_failure(self):
        """升级失败时 table 输出显示错误和手动命令"""
        error = subprocess.CalledProcessError(1, ["uv", "tool", "upgrade", "jfox-cli"])
        error.stderr = "network error"

        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", side_effect=error):
                    result = runner.invoke(app, ["update"])
                    assert result.exit_code == 1
                    assert "升级失败" in result.output
                    assert "network error" in result.output
                    assert "uv tool upgrade jfox-cli" in result.output

    def test_json_output_already_latest(self):
        """已是最新版本时 --json 输出包含 already_latest"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.1.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "up-to-date", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update", "--json"])
                        assert result.exit_code == 0
                        data = json.loads(result.output)
                        assert data["success"] is True
                        assert data["already_latest"] is True
                        assert data["previous_version"] == "1.1.0"
                        assert data["current_version"] == "1.1.0"

    def test_json_output_success(self):
        """--json 输出合法 JSON 且 schema 统一"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch(
                    "jfox.cli._run_upgrade",
                    return_value={"stdout": "Upgraded", "stderr": ""},
                ):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update", "--json"])
                        assert result.exit_code == 0
                        data = json.loads(result.output)
                        assert data["success"] is True
                        assert data["method"] == "uv"
                        assert data["previous_version"] == "1.0.0"
                        assert data["current_version"] == "1.1.0"
                        assert "stderr" in data
                        assert data["error"] == ""

    def test_json_output_failure(self):
        """失败时 --json 输出 success=false"""
        error = subprocess.CalledProcessError(1, ["uv", "tool", "upgrade", "jfox-cli"])
        error.stderr = "network error"

        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", side_effect=error):
                    result = runner.invoke(app, ["update", "--json"])
                    assert result.exit_code == 1
                    data = json.loads(result.output)
                    assert data["success"] is False
                    assert "network error" in data["error"]

    def test_invalid_format_exits_with_error(self):
        """--format 传入非法值时返回非零退出码"""
        result = runner.invoke(app, ["update", "--format", "josn"])
        assert result.exit_code == 2
        assert "table" in result.output or "json" in result.output


class TestGetInstalledVersion:
    """_get_installed_version 测试"""

    def test_prefers_sys_executable_module(self):
        """优先使用 sys.executable -m jfox --version"""
        with patch("jfox.cli.sys.executable", "/usr/bin/python3"):
            with patch("jfox.cli.shutil.which", return_value="/usr/local/bin/jfox"):
                with patch("jfox.cli.subprocess.run") as mock_run:
                    mock_run.return_value.stdout = "jfox 1.1.0\n"
                    version = _get_installed_version()
                    assert version == "1.1.0"
                    mock_run.assert_called_once()
                    assert mock_run.call_args[0][0] == [
                        "/usr/bin/python3",
                        "-m",
                        "jfox",
                        "--version",
                    ]

    def test_falls_back_to_path_jfox(self):
        """sys.executable 方式失败时回退到 PATH 中的 jfox"""
        with patch("jfox.cli.sys.executable", "/usr/bin/python3"):
            with patch("jfox.cli.shutil.which", return_value="/usr/local/bin/jfox"):
                with patch("jfox.cli.subprocess.run") as mock_run:
                    mock_run.side_effect = [
                        subprocess.CalledProcessError(1, ["python3", "-m", "jfox"]),
                        type("obj", (object,), {"stdout": "jfox 1.2.0\n"})(),
                    ]
                    version = _get_installed_version()
                    assert version == "1.2.0"
                    assert mock_run.call_count == 2

    def test_returns_unknown_when_all_fail(self):
        """所有方式均失败时返回 unknown"""
        with patch("jfox.cli.sys.executable", "/usr/bin/python3"):
            with patch("jfox.cli.shutil.which", return_value=None):
                with patch(
                    "jfox.cli.subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, ["python3"]),
                ):
                    assert _get_installed_version() == "unknown"
