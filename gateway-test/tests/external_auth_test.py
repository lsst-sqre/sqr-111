import random
import string
from uuid import uuid4

from .support import (
    AUTH_DOWNSTREAM_HEADER_ALLOWED,
    AUTH_DOWNSTREAM_HEADER_DENIED,
    AUTH_UPSTREAM_HEADER_ALLOWED,
    CLIENT_AUTH_HEADER,
    Client,
    Timer,
    assert_client_response_header,
    assert_not_upstream_request_header,
    assert_upstream_request_header,
    timed,
)


def test_allowed(client: Client) -> None:
    """The auth server allows a request to go through to the upstream."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/foo/bar", headers=headers)
    assert res.status_code == 200


def test_allowed_strips_original_auth_header(client: Client) -> None:
    """The auth server strips the original auth header before sending to upstream."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/foo/bar", headers=headers)
    assert_not_upstream_request_header(res, CLIENT_AUTH_HEADER, "allowed")


def test_allowed_upstream_auth_header(client: Client) -> None:
    """The auth server can inject a header into the request to the upstream."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/foo/bar", headers=headers)
    assert_upstream_request_header(res, AUTH_UPSTREAM_HEADER_ALLOWED)


def test_allowed_client_custom_auth_header(client: Client) -> None:
    """The auth server can inject a header into the client response."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/foo/bar", headers=headers)
    assert_client_response_header(res, AUTH_DOWNSTREAM_HEADER_ALLOWED)


def test_allowed_filters_cookie_single(client: Client) -> None:
    headers = {
        CLIENT_AUTH_HEADER: "allowed",
        "cookie": "filterme=yes",
    }
    res = client.get("/foo/bar", headers=headers)
    assert res.status_code == 200
    assert "cookie" not in res.text.lower()


def test_allowed_filters_cookie_multiple(client: Client) -> None:
    headers = {
        CLIENT_AUTH_HEADER: "allowed",
        "cookie": "foo=bar;filterme=yes",
    }
    res = client.get("/foo/bar", headers=headers)
    assert res.status_code == 200
    assert_upstream_request_header(res, "cookie", "foo=bar")


def test_custom_denied_status(client: Client) -> None:
    """The auth server can set the client response status code when denied."""
    headers = {CLIENT_AUTH_HEADER: "custom-403"}
    res = client.get("/foo/bar", headers=headers)
    assert res.status_code == 403


def test_custom_denied_body(client: Client) -> None:
    """The auth server can put a custom body in the denied response to the client."""
    headers = {CLIENT_AUTH_HEADER: "custom-403"}
    res = client.get("/foo/bar", headers=headers)
    lines = res.text.splitlines()
    expected = "custom 403 body from auth server"
    assert expected in lines


def test_multiple_auth_headers_returns_400(client: Client) -> None:
    """The auth server returns a 400 client response for multiple auth headers."""
    headers = [
        (CLIENT_AUTH_HEADER, "what"),
        (CLIENT_AUTH_HEADER, "ever"),
        (CLIENT_AUTH_HEADER, "allowed"),
    ]
    res = client.get_multiple("/foo/bar", headers=headers)
    assert res.status_code == 400


def test_status(client: Client) -> None:
    """A request with no auth header returns 401 client response."""
    res = client.get("/foo/bar")
    assert res.status_code == 401


def test_body(client: Client) -> None:
    """A request with no auth header returns body from auth server response."""
    res = client.get("/foo/bar")
    lines = res.text.splitlines()
    expected = "custom 401 body no auth header"
    assert expected in lines


def test_denied_sends_custom_header(client: Client) -> None:
    """The auth server can set a header in a denied client response."""
    res = client.get("/foo/bar")
    assert_client_response_header(res, AUTH_DOWNSTREAM_HEADER_DENIED)


def test_no_session_affinity(client: Client) -> None:
    """The gateway proxy can spreads requests against multiple replicas."""
    # If we're not doing session affinity, we shouldn't get the same pod all the
    # time
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    indexes: list[str] = []
    for i in range(10):
        res = client.get("/foo/bar", headers=headers)
        index = res.headers.get("x-pod-index")
        assert index is not None
        indexes.append(index)

    assert len(set(indexes)) > 1


def test_session_affinity(client: Client) -> None:
    """The gateway proxy can hash a particular cookie for session affinity."""
    # If we ARE doing session affinity, we SHOULD get the same pod all the
    # time
    affinity_key = "abcdef"
    headers = {
        CLIENT_AUTH_HEADER: "allowed",
        "x-use-session-affinity": "true",
        "cookie": f"cookie1=foo;gafaelfawr={affinity_key};cookie3=bar",
    }
    indexes: list[str] = []
    for i in range(10):
        res = client.get("/foo/bar", headers=headers)
        index = res.headers.get("x-pod-index")
        assert index is not None
        indexes.append(index)
        seen_affinity_key = res.headers.get("x-debug-affinity-key")
        assert seen_affinity_key == affinity_key

    assert len(set(indexes)) == 1


def test_caching(client: Client) -> None:
    """The auth server can inject a header into the client response."""
    cookie_val = uuid4()
    headers = {
        CLIENT_AUTH_HEADER: "allowed",
        "x-delay-auth": "true",
        "cookie": f"gafaelfawr={cookie_val}",
    }

    # The first request should not be cached
    with timed() as timer:
        res = client.get("/caching-foo/bar", headers=headers)
    assert res.status_code == 200
    assert timer.elapsed > 1

    # The second request should be cached
    with timed() as timer:
        res = client.get("/caching-foo/bar", headers=headers)
    assert res.status_code == 200
    assert timer.elapsed < 0.5

    # A request with a changed cookie value should not be cached
    cookie_val = uuid4()
    headers = {
        CLIENT_AUTH_HEADER: "allowed",
        "x-delay-auth": "true",
        "cookie": f"gafaelfawr={cookie_val}",
    }
    with timed() as timer:
        res = client.get("/caching-foo/bar", headers=headers)
    assert res.status_code == 200
    assert timer.elapsed > 0.1
