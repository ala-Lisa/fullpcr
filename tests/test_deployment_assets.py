"""Tests for deployment assets (systemd unit, env example).

These tests are read-only checks on the template files.  They never call
systemctl, sudo, or start any service.
"""

from __future__ import annotations

import re
from pathlib import Path


_DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy" / "systemd"
_SERVICE_FILE = _DEPLOY_DIR / "fullpcr.service"
_ENV_FILE = _DEPLOY_DIR / "fullpcr.env.example"


# ── helpers ────────────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── file existence ─────────────────────────────────────────────────────────


class TestDeploymentFilesExist:
    """Both deployment template files must be present."""

    def test_service_file_exists(self):
        assert _SERVICE_FILE.is_file(), f"Missing {_SERVICE_FILE}"

    def test_env_file_exists(self):
        assert _ENV_FILE.is_file(), f"Missing {_ENV_FILE}"


# ── systemd unit ───────────────────────────────────────────────────────────


class TestSystemdUnitStructure:
    """Structural checks on the systemd unit template."""

    @staticmethod
    def _section_names(text: str) -> list[str]:
        return re.findall(r"^\[([A-Z][a-zA-Z]*)\]", text, re.MULTILINE)

    def test_has_three_required_sections(self):
        text = _read(_SERVICE_FILE)
        sections = self._section_names(text)
        assert "Unit" in sections, f"Missing [Unit]; sections: {sections}"
        assert "Service" in sections, f"Missing [Service]; sections: {sections}"
        assert "Install" in sections, f"Missing [Install]; sections: {sections}"

    def test_user_and_group_are_fullpcr_not_root(self):
        text = _read(_SERVICE_FILE)
        assert re.search(r"^User=fullpcr$", text, re.MULTILINE), "Missing or wrong User="
        assert re.search(r"^Group=fullpcr$", text, re.MULTILINE), "Missing or wrong Group="
        assert not re.search(r"^User=root$", text, re.MULTILINE), "User must not be root"

    def test_environment_file_path(self):
        text = _read(_SERVICE_FILE)
        assert re.search(
            r"^EnvironmentFile=/etc/fullpcr/fullpcr\.env$", text, re.MULTILINE
        ), "Missing or wrong EnvironmentFile="

    def test_execstart_contains_python_fullpcr_gui(self):
        text = _read(_SERVICE_FILE)
        assert re.search(
            r"^ExecStart=.*python -m fullpcr gui\b", text, re.MULTILINE
        ), "ExecStart must contain 'python -m fullpcr gui'"

    def test_execstart_contains_host_port_data_dir(self):
        text = _read(_SERVICE_FILE)
        assert "--host" in text, "ExecStart missing --host"
        assert "--port" in text, "ExecStart missing --port"
        assert "--data-dir" in text, "ExecStart missing --data-dir"

    def test_restart_on_failure(self):
        text = _read(_SERVICE_FILE)
        assert re.search(
            r"^Restart=on-failure$", text, re.MULTILINE
        ), "Missing Restart=on-failure"

    def test_no_new_privileges(self):
        text = _read(_SERVICE_FILE)
        assert re.search(
            r"^NoNewPrivileges=true$", text, re.MULTILINE
        ), "Missing NoNewPrivileges=true"

    def test_no_shell_constructs(self):
        text = _read(_SERVICE_FILE)
        forbidden = ["bash -c", "sh -c", "nohup", "sudo", "shell=True"]
        for token in forbidden:
            assert token not in text, f"Forbidden token in unit: {token!r}"


# ── env example ────────────────────────────────────────────────────────────


class TestEnvExample:
    """Checks on the environment variable template."""

    def test_contains_required_variables(self):
        text = _read(_ENV_FILE)
        for var in ["FULLPCR_HOST", "FULLPCR_PORT", "FULLPCR_DATA_DIR", "PATH"]:
            assert re.search(
                rf"^{var}=", text, re.MULTILINE
            ), f"Missing required variable: {var}"

    def test_default_host_is_localhost(self):
        text = _read(_ENV_FILE)
        match = re.search(r"^FULLPCR_HOST=(.*)$", text, re.MULTILINE)
        assert match is not None, "FULLPCR_HOST not found"
        assert match.group(1).strip() == "127.0.0.1", (
            f"Default FULLPCR_HOST must be 127.0.0.1, got: {match.group(1)!r}"
        )

    def test_no_credentials_or_secrets(self):
        text = _read(_ENV_FILE)
        # Exclude comment lines.
        lines = [l for l in text.splitlines() if not l.strip().startswith("#")]
        body = "\n".join(lines)
        suspicious = [
            "PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY",
            "PRIVATE_KEY", "CERT", "passwd", "secret", "token",
        ]
        for token in suspicious:
            assert token not in body, (
                f"Env example must not contain credential-like token: {token!r}"
            )


# ── README cross-reference ─────────────────────────────────────────────────


class TestReadmeReferencesDeploymentAssets:
    """README must reference the actual template paths."""

    def test_readme_references_service_path(self):
        readme = Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        assert "deploy/systemd/fullpcr.service" in text, (
            "README should reference deploy/systemd/fullpcr.service"
        )

    def test_readme_references_env_example_path(self):
        readme = Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        assert "deploy/systemd/fullpcr.env.example" in text, (
            "README should reference deploy/systemd/fullpcr.env.example"
        )


class TestReadmeMigrationDocs:
    """Phase 4C-2: README migration and acceptance checklist."""

    @staticmethod
    def _readme():
        return (Path(__file__).resolve().parent.parent / "README.md").read_text(
            encoding="utf-8")

    def test_does_not_require_same_absolute_path(self):
        text = self._readme()
        assert "绝对路径可以不同" in text

    def test_mentions_data_dir_and_env_var(self):
        text = self._readme()
        assert "--data-dir" in text
        assert "FULLPCR_DATA_DIR" in text

    def test_mentions_stcore_health(self):
        text = self._readme()
        assert "/_stcore/health" in text

    def test_mentions_http_200(self):
        text = self._readme()
        assert "200" in text

    def test_acceptance_checks_both_obipcr_and_mfeprimer(self):
        text = self._readme()
        assert "obipcr" in text
        assert "mfeprimer" in text

    def test_health_not_equal_full_analysis(self):
        text = self._readme()
        assert "health" in text
        assert "完整分析" in text

    def test_retains_no_auth_no_tls_warning(self):
        text = self._readme()
        assert "没有登录认证和 TLS 加密" in text or "无内置登录认证和 TLS" in text
        assert "禁止" in text


class TestReadmeEnvironmentRequirements:
    """Phase 4C-2 Fix A: README 环境要求 must document venv/pip prerequisites."""

    @staticmethod
    def _env_section() -> str:
        """Extract the 环境要求 subsection from the 迁移 section onward.

        Returns only the lines between '### 环境要求' and the next heading or
        code block, whichever comes first.
        """
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
            encoding="utf-8")
        lines = readme.splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip() == "### 环境要求":
                start = i
                break
        assert start is not None, "README must contain '### 环境要求' subsection"
        section_lines: list[str] = []
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("###") or lines[j].startswith("```"):
                break
            section_lines.append(lines[j])
        return "\n".join(section_lines)

    def test_requires_virtualenv_capability(self):
        text = self._env_section()
        assert "虚拟环境" in text or "venv" in text, (
            "环境要求 must mention virtualenv / venv capability"
        )

    def test_requires_pip_or_ensurepip_or_python3_venv_package(self):
        text = self._env_section()
        tokens = ["ensurepip", "python3-venv", "pip"]
        found = any(t in text for t in tokens)
        assert found, (
            f"环境要求 must mention pip, ensurepip, or python3-venv; "
            f"section content: {text!r}"
        )
