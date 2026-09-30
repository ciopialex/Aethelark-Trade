"""A brokerage account is connected with one command, not a hand-written .env.

`atrade portfolio` read Alpaca keys from ~/.aethelark/.env and nothing wrote
that file. `atrade broker <key> <secret>` does, readable by the user alone,
keeping any other lines in it, and checks the keys before saying "connected".
"""
import os
import stat

import pytest
from typer.testing import CliRunner

from aethelark_trade.engine import cli, fetchers


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".aethelark" / ".env"
    monkeypatch.setattr(fetchers, "ALPACA_ENV_PATH", path)
    for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_connecting_writes_a_private_file_and_keeps_other_lines(env_file, monkeypatch):
    env_file.parent.mkdir(parents=True)
    env_file.write_text("SOMETHING_ELSE=1\nALPACA_API_KEY=old\n")
    monkeypatch.setattr(fetchers, "fetch_alpaca_portfolio", lambda: {"paper": True})
    out = CliRunner().invoke(cli.app, ["broker", "KEY1", "SECRET1", "--json"])
    assert out.exit_code == 0, out.stdout
    text = env_file.read_text()
    assert "SOMETHING_ELSE=1" in text and "ALPACA_API_KEY=KEY1" in text
    assert "old" not in text and "paper-api" in text
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600


def test_keys_alpaca_refuses_are_not_called_connected(env_file, monkeypatch):
    def refuse():
        raise fetchers.BrokerNotConnected("forbidden")
    monkeypatch.setattr(fetchers, "fetch_alpaca_portfolio", refuse)
    out = CliRunner().invoke(cli.app, ["broker", "BAD", "KEYS", "--json"])
    assert out.exit_code == 1 and "refused" in out.stdout


def test_forget_removes_only_the_alpaca_lines(env_file):
    env_file.parent.mkdir(parents=True)
    env_file.write_text("KEEP=1\nALPACA_API_KEY=a\nALPACA_SECRET_KEY=b\n")
    out = CliRunner().invoke(cli.app, ["broker", "--forget", "--json"])
    assert out.exit_code == 0
    assert env_file.read_text() == "KEEP=1\n"


def test_the_not_connected_answer_says_how_to_connect(env_file):
    with pytest.raises(fetchers.BrokerNotConnected, match="atrade broker"):
        fetchers.fetch_alpaca_portfolio()
