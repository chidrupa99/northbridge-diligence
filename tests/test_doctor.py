"""Tests for the install-verification script.

These exist because of a real failure. A Windows install followed README.md
verbatim, `doctor.py` printed "All 10 checks passed. The install is good.", and
the skill never fired. The MCP server had been registered with Claude Desktop
while the skill sat in `~/.claude/skills/`, which is Claude Code's directory —
two different surfaces, each holding one half of a working install.

Every check that existed at the time ran in-process. They proved the package was
importable and the tools were registerable; none of them opened a client config
file, so none could tell that nothing would ever launch the server. That is the
same class of gap the test suite itself has and states plainly — it verifies
logic, not installation — except here the script whose entire job is verifying
the installation had it.

`inspect_client_config` is deliberately a pure function over a path so the
config-parsing states are testable without a real Claude install on the machine.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

# doctor.py is a script rather than part of the package — it has to run before
# the package is installed — so it is loaded by path instead of imported.
_DOCTOR_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "doctor.py"
_spec = importlib.util.spec_from_file_location("_doctor", _DOCTOR_PATH)
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


def write(tmp_path: pathlib.Path, payload, name: str = "config.json") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


class TestConfigStates:
    """Each state maps to a different thing the installer has to be told."""

    def test_missing_file_is_not_an_error(self, tmp_path):
        # Nobody is expected to have every client installed.
        assert doctor.inspect_client_config(tmp_path / "nope.json")["state"] == "absent"

    def test_config_with_no_mcpservers_key_at_all(self, tmp_path):
        # The real shape of a fresh ~/.claude.json: valid, populated, and with no
        # mcpServers key anywhere. It has to be added, not edited.
        path = write(tmp_path, {"machineID": "abc", "firstStartTime": "..."})
        assert doctor.inspect_client_config(path)["state"] == "no-servers"

    def test_config_with_other_servers_but_not_ours(self, tmp_path):
        path = write(tmp_path, {"mcpServers": {"some-other-tool": {"command": "x"}}})
        info = doctor.inspect_client_config(path)
        assert info["state"] == "not-listed"
        assert info["others"] == ["some-other-tool"]

    def test_malformed_json_is_reported_not_raised(self, tmp_path):
        # A client silently ignores the whole file when this happens, so it must
        # surface as its own diagnosis rather than as a traceback.
        path = write(tmp_path, '{"mcpServers": {"northbridge-diligence": ')
        assert doctor.inspect_client_config(path)["state"] == "unreadable"

    def test_json_that_is_not_an_object(self, tmp_path):
        assert doctor.inspect_client_config(write(tmp_path, [1, 2]))["state"] == "unreadable"


class TestRegisteredEntry:
    def test_fully_correct_entry(self, tmp_path):
        command = tmp_path / "edgar-mcp"
        command.write_text("#!/bin/sh\n")
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": str(command),
            "env": {"EDGAR_USER_AGENT": "Org me@example.com"},
        }}})
        info = doctor.inspect_client_config(path)
        assert info["state"] == "registered"
        assert info["command_exists"] and info["has_user_agent"]

    def test_command_path_that_does_not_exist_is_caught(self, tmp_path):
        # The commonest registration mistake: a stale or hand-typed venv path.
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": "/nope/edgar-mcp",
            "env": {"EDGAR_USER_AGENT": "Org me@example.com"},
        }}})
        assert doctor.inspect_client_config(path)["command_exists"] is False

    def test_missing_user_agent_in_env_is_caught(self, tmp_path):
        # A GUI-launched client inherits nothing from the shell, so an `export`
        # in a terminal does not help it. SEC returns 403.
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": "/x/edgar-mcp"}}})
        assert doctor.inspect_client_config(path)["has_user_agent"] is False

    def test_blank_user_agent_counts_as_missing(self, tmp_path):
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": "/x", "env": {"EDGAR_USER_AGENT": "   "}}}})
        assert doctor.inspect_client_config(path)["has_user_agent"] is False


class TestCheckClients:
    """The whole point: an unwired install must not report as healthy."""

    @pytest.fixture(autouse=True)
    def reset(self):
        doctor.results.clear()
        yield
        doctor.results.clear()

    def test_no_client_registered_fails(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(doctor, "client_configs",
                            lambda: [("Claude Code (user scope)", tmp_path / "absent.json")])
        assert doctor.check_clients() is False
        out = capsys.readouterr().out
        assert "no Claude client has this server registered" in out
        # The fix has to name where to put it, not just say it is missing.
        assert "~/.claude.json" in out

    def test_registered_client_passes(self, tmp_path, monkeypatch, capsys):
        command = tmp_path / "edgar-mcp"
        command.write_text("")
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": str(command), "env": {"EDGAR_USER_AGENT": "Org me@example.com"}}}})
        monkeypatch.setattr(doctor, "client_configs",
                            lambda: [("Claude Code (user scope)", path)])
        assert doctor.check_clients() is True
        assert "wired: Claude Code (user scope)" in capsys.readouterr().out

    def test_desktop_only_warns_that_cowork_does_not_read_the_skill_dir(
        self, tmp_path, monkeypatch, capsys
    ):
        """The exact Windows failure, reproduced.

        MCP server registered with Claude Desktop, skill copied to
        ~/.claude/skills/. Per the Claude Code skills docs, Cowork sessions --
        the Desktop chat surface -- do not read that directory at all; they load
        skills enabled for the claude.ai account. Both halves installed, and the
        surface in use sees only one of them.
        """
        command = tmp_path / "edgar-mcp"
        command.write_text("")
        path = write(tmp_path, {"mcpServers": {"northbridge-diligence": {
            "command": str(command), "env": {"EDGAR_USER_AGENT": "Org me@example.com"}}}})
        monkeypatch.setattr(doctor, "client_configs",
                            lambda: [("Claude Desktop", path)])
        skill_dir = tmp_path / "skills" / "company-screen"
        skill_dir.mkdir(parents=True)
        monkeypatch.setattr(doctor, "SKILL_DIR", skill_dir)

        assert doctor.check_clients() is True
        # Normalised: the note is word-wrapped, so phrases span line breaks.
        out = " ".join(capsys.readouterr().out.split())
        # Names the actual mechanism, not a vague "check your surfaces".
        assert "does NOT read ~/.claude/skills/" in out
        assert "claude.ai account" in out
        # And distinguishes the two Desktop session types rather than conflating them.
        assert "Claude Code session inside the Desktop app" in out

    def test_unreadable_config_fails_with_the_json_diagnosis(
        self, tmp_path, monkeypatch, capsys
    ):
        path = write(tmp_path, "{broken")
        monkeypatch.setattr(doctor, "client_configs",
                            lambda: [("Claude Desktop", path)])
        # Unreadable is a problem worth failing on: the client ignores the whole
        # file, so any other server in it is silently dead too.
        assert doctor.check_clients() is False
        out = " ".join(capsys.readouterr().out.split())
        assert "not valid JSON" in out
        # Must not be misdiagnosed as "simply not registered".
        assert "no Claude client has this server registered" not in out
