from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_auth_off_unit_cannot_silently_reload_agent_token():
    installer = (ROOT / "deploy" / "install-worker-agent.sh").read_text(
        encoding="utf-8"
    )

    assert 'if [ "$AUTH_MODE" = "off" ]; then' in installer
    assert 'AGENT_ENV_DIRECTIVE=""' in installer
    assert 'AGENT_TOKEN_UNSET="BRIDGE_AGENT_TOKEN "' in installer
    assert "$AGENT_ENV_DIRECTIVE" in installer
    assert "UnsetEnvironment=${AGENT_TOKEN_UNSET}OPENCODE" in installer


def test_trusted_lan_reference_unit_is_explicitly_auth_off():
    unit = (ROOT / "deploy" / "bridge-worker-agent.service").read_text(
        encoding="utf-8"
    )

    assert "EnvironmentFile=-/home/nathan/.config/codeartsbridge/agent.env" not in unit
    assert "UnsetEnvironment=BRIDGE_AGENT_TOKEN OPENCODE" in unit
    assert "EnvironmentFile=-/home/nathan/.config/codeartsbridge/codearts.env" in unit
