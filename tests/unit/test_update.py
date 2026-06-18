"""
测试类型: 单元测试
目标模块: jfox.cli (update 命令)
预估耗时: < 1 秒
依赖要求: 无外部依赖
"""

import json
import subprocess
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.cli import _detect_install_method, _update_impl, app

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
                with patch("jfox.cli._run_upgrade", return_value="Upgraded"):
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
                with patch("jfox.cli._run_upgrade", return_value="Upgraded"):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert result["command"] == "pipx upgrade jfox-cli"

    def test_pip_upgrade_success(self):
        """pip 模式下调用正确命令"""
        with patch("jfox.cli._detect_install_method", return_value="pip"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", return_value="Upgraded"):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = _update_impl()
                        assert "pip install --upgrade jfox-cli" in result["command"]

    def test_upgrade_failure_returns_manual_command(self):
        """升级失败时返回手动执行命令"""
        error = subprocess.CalledProcessError(1, ["uv", "tool", "upgrade", "jfox-cli"])
        error.stderr = "network error"

        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", side_effect=error):
                    result = _update_impl()
                    assert result["success"] is False
                    assert "network error" in result["error"]
                    assert "uv tool upgrade jfox-cli" in result["message"]


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
                with patch("jfox.cli._run_upgrade", return_value="Upgraded"):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update"])
                        assert result.exit_code == 0
                        assert "uv" in result.output
                        assert "1.0.0 → 1.1.0" in result.output

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

    def test_json_output_success(self):
        """--json 输出合法 JSON"""
        with patch("jfox.cli._detect_install_method", return_value="uv"):
            with patch("jfox.__version__", "1.0.0"):
                with patch("jfox.cli._run_upgrade", return_value="Upgraded"):
                    with patch("jfox.cli._get_installed_version", return_value="1.1.0"):
                        result = runner.invoke(app, ["update", "--json"])
                        assert result.exit_code == 0
                        data = json.loads(result.output)
                        assert data["success"] is True
                        assert data["method"] == "uv"
                        assert data["previous_version"] == "1.0.0"
                        assert data["current_version"] == "1.1.0"

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
