import os

import pytest

from .support import Client


@pytest.fixture
def address() -> str:
    """Get the IP address of the gateway/ingress from the environment."""
    address = os.environ.get("GATEWAY_ADDRESS")
    if address is None:
        raise RuntimeError("GATEWAY_ADDRESS must be defined in the enviroment")
    return address


@pytest.fixture
def host() -> str:
    """Get the hostname that matches the gateway/ingress from the environment.

    This
    """
    address = os.environ.get("GATEWAY_HOST")
    if address is None:
        raise RuntimeError("GATEWAY_HOST must be defined in the enviroment")
    return address


@pytest.fixture
def client(address: str, host: str) -> Client:
    return Client(address, host)
