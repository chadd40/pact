import pytest

from pact.sidecar import _server_config


def test_defaults():
    assert _server_config({}) == {"host": "127.0.0.1", "port": 8000}


def test_port_override():
    assert _server_config({"PACT_PORT": "8765"})["port"] == 8765


def test_host_override():
    assert _server_config({"PACT_HOST": "0.0.0.0"})["host"] == "0.0.0.0"


def test_bad_port_raises():
    with pytest.raises(ValueError):
        _server_config({"PACT_PORT": "abc"})
