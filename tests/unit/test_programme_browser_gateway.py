"""Local bridge boundary checks without starting a listener or database."""

import io
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_browser_gateway as gateway
from tests.rehearsals import programme_https as https

RUN = "1234567890abcdef1234567890abcdef"
FILE_ID = "12345678-1234-1234-1234-123456789abc"
INTAKE = (
    f"/my/applications/programme/{FILE_ID}/{FILE_ID}/{FILE_ID}/"
    f"work/answer/{FILE_ID}/file/intake/"
)


def test_diagnostics_are_bounded_aggregate_copies_without_request_data():
    counts = gateway._RequestCounts()
    counts.record("POST")
    counts.record("POST", 200)
    counts.record("POST", 503)
    expected = [
        {"method": "POST", "state": "received", "count": 1},
        {"method": "POST", "state": "200", "count": 1},
        {"method": "POST", "state": "503", "count": 1},
    ]
    assert counts.snapshot() == expected
    changed = counts.snapshot()
    changed[0]["count"] = 999
    assert counts.snapshot() == expected
    for method, status in [
        ("private-url", 200),
        ("POST", "private-body"),
        ("GET", 999),
        ("GET", 200.0),
        ("GET", True),
    ]:
        with pytest.raises(ValueError, match="invalid_request_count"):
            counts.record(method, status)
    assert counts.snapshot() == expected
    assert gateway._RequestCounts().snapshot() == []


def test_diagnostic_counters_saturate_without_growing_the_key_space():
    counts = gateway._RequestCounts()
    counts._counts[("POST", 200)] = 2**31 - 1
    counts.record("POST", 200)
    assert counts.snapshot() == [{"method": "POST", "state": "200", "count": 2**31 - 1}]


def test_diagnostics_count_concurrent_requests_without_lost_increments():
    counts = gateway._RequestCounts()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: counts.record("GET", 200), range(200)))
    assert counts.snapshot() == [{"method": "GET", "state": "200", "count": 200}]


@pytest.mark.parametrize("refused", [False, True])
def test_handler_counts_received_and_response_without_logging_private_data(
    bridge, refused
):
    handler = object.__new__(gateway._Handler)
    handler.command = "POST"
    handler.server = SimpleNamespace(bridge=bridge)
    handler._read_request = Mock(return_value=(200, [], b"private-response"))
    if refused:
        handler._read_request.side_effect = gateway.ProgrammeBrowserGatewayError(
            "private-error"
        )
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = io.BytesIO()
    handler._handle()
    assert bridge.counts.snapshot() == [
        {"method": "POST", "state": "received", "count": 1},
        {"method": "POST", "state": "503" if refused else "200", "count": 1},
    ]
    assert b"private-error" not in handler.wfile.getvalue()


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_file_intake_preserves_original_intent_and_csrf(bridge, method):
    result = bridge.request_headers(
        method,
        INTAKE,
        headers(
            Host="127.0.0.1:50413",
            Origin=bridge.origin,
            Content_Type="application/pdf",
            X_Maru_File_Intent="original-signed-intent",
            X_CSRFToken="real-csrf-token",
        ),
        500 if method == "PUT" else 0,
    )
    assert result["X-Maru-File-Intent"] == "original-signed-intent"
    assert result["X-CSRFToken"] == "real-csrf-token"
    assert result["Origin"] == bridge.backend


@pytest.mark.parametrize(
    "path",
    [
        "/admin/",
        INTAKE + "?intent=x",
        INTAKE + "extra/",
        INTAKE[:-1],
        INTAKE.replace(FILE_ID, "not-a-uuid", 1),
    ],
)
def test_put_is_not_a_general_proxy_method(bridge, path):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="method_refused"):
        bridge.request_headers(
            "PUT",
            path,
            headers(
                Host="127.0.0.1:50413",
                Origin=bridge.origin,
                Content_Type="application/pdf",
            ),
            20,
        )


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.invalid"])
def test_upload_requires_exact_local_origin(bridge, origin):
    values = headers(Host="127.0.0.1:50413", Content_Type="application/pdf")
    if origin is not None:
        values["Origin"] = origin
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="origin_refused"):
        bridge.request_headers("PUT", INTAKE, values, 20)


@pytest.mark.parametrize(
    ("size", "content_type"),
    [
        (0, "application/pdf"),
        (10 * 1024 * 1024 + 1, "application/pdf"),
        (10, "application/json"),
        (10, "application/pdf; charset=utf-8"),
    ],
)
def test_upload_shape_and_budget_remain_closed(bridge, size, content_type):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.request_headers(
            "PUT",
            INTAKE,
            headers(
                Host="127.0.0.1:50413", Origin=bridge.origin, Content_Type=content_type
            ),
            size,
        )


def test_full_contract_pdf_budget_does_not_expand_form_budget(bridge):
    values = headers(
        Host="127.0.0.1:50413", Origin=bridge.origin, Content_Type="application/pdf"
    )
    bridge.request_headers("PUT", INTAKE, values, gateway.MAX_PDF)
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="body_refused"):
        bridge.request_headers("POST", "/accounts/login/", values, gateway.MAX_PDF)


@pytest.mark.parametrize("intent", ["", "x" * 2049, "nonascii-\u00e9", "line\r\nbreak"])
def test_file_intent_is_bounded_without_rewriting(bridge, intent):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.request_headers(
            "GET",
            INTAKE,
            headers(Host="127.0.0.1:50413", X_Maru_File_Intent=intent),
            0,
        )


def test_file_intent_is_never_forwarded_to_other_routes(bridge):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="file_intent"):
        bridge.request_headers(
            "GET",
            "/admin/",
            headers(Host="127.0.0.1:50413", X_Maru_File_Intent="original"),
            0,
        )


def test_encoded_upload_is_refused_before_body_read(bridge):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="framing"):
        bridge.request_headers(
            "PUT",
            INTAKE,
            headers(
                Host="127.0.0.1:50413",
                Origin=bridge.origin,
                Content_Type="application/pdf",
                Content_Encoding="gzip",
            ),
            20,
        )


def test_full_size_pdf_response_is_unchanged_but_other_budget_stays(bridge):
    content = b"%PDF" + b"x" * (gateway.MAX_PDF - 4)
    _, _, result = bridge.response(
        200, headers(Content_Type="application/pdf"), content
    )
    assert result == content
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="response_refused"):
        bridge.response(200, headers(Content_Type="application/json"), content)
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="response_refused"):
        bridge.response(200, headers(Content_Type="application/pdf"), content + b"x")


def test_handler_dispatches_put_through_the_same_guard(bridge):
    handler = object.__new__(gateway._Handler)
    handler._handle = Mock()
    handler.do_PUT()
    handler._handle.assert_called_once_with()


def headers(**values):
    result = Message()
    for name, value in values.items():
        result[name.replace("_", "-")] = value
    return result


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    request = SimpleNamespace(run_id=RUN, lease_seconds=600)
    monkeypatch.setattr(gateway, "require_programme_rehearsal_request", lambda: request)
    monkeypatch.setattr(https, "require_programme_rehearsal_request", lambda: request)
    monkeypatch.setattr(https.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(https, "ROOT", tmp_path)
    monkeypatch.setenv(gateway.OPT_IN, "synthetic-loopback-only")
    directory = tmp_path / ".tools" / f"programme-https-{RUN}-unit"
    directory.mkdir(parents=True)
    fingerprint = https.create_loopback_certificate(directory, deadline=400.0)
    return SimpleNamespace(
        run_id=RUN,
        runtime=request,
        deadline=400.0,
        url="https://127.0.0.1:50412",
        material=SimpleNamespace(web_port=50412),
        certificate_path=directory / "certificate.pem",
        certificate_sha256=fingerprint,
    )


@pytest.fixture
def bridge(fixture):
    result = gateway._Bridge(fixture)
    result.origin = "http://127.0.0.1:50413"
    return result


def test_pin_and_default_tls_verification_remain_real(bridge):
    assert bridge.context.verify_mode == ssl.CERT_REQUIRED
    assert bridge.context.check_hostname
    assert bridge.context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert bridge.context.get_ca_certs() == []  # only the exact leaf, not a CA


@pytest.mark.parametrize(
    "mutation", ["opt_in", "run", "runtime", "scheme", "host", "port", "pin", "path"]
)
def test_changed_fixture_or_absent_permission_refuses_before_listener(
    fixture, monkeypatch, mutation
):
    if mutation == "opt_in":
        monkeypatch.delenv(gateway.OPT_IN)
    elif mutation == "run":
        fixture.run_id = "b" * 32
    elif mutation == "runtime":
        fixture.runtime = SimpleNamespace(run_id="b" * 32)
    elif mutation in {"scheme", "host", "port"}:
        fixture.url = {
            "scheme": "http://127.0.0.1:50412",
            "host": "https://remote.invalid:50412",
            "port": "https://127.0.0.1:50414",
        }[mutation]
    elif mutation == "pin":
        fixture.certificate_sha256 = "0" * 64
    else:
        fixture.certificate_path = fixture.certificate_path.parent / "private-key.pem"
    server = Mock()
    monkeypatch.setattr(gateway, "_Server", server)
    with (
        pytest.raises(
            (gateway.ProgrammeBrowserGatewayError, https.ProgrammeHttpsError)
        ),
        gateway.local_programme_browser(fixture),
    ):
        pytest.fail("An invalid fixture cannot be exposed.")
    server.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "//elsewhere.invalid/",
        "https://elsewhere.invalid/",
        "/\\elsewhere",
        "/x\r\ny",
        "/x#fragment",
        "relative",
        "/" + "x" * gateway.MAX_PATH,
    ],
)
def test_nonlocal_or_ambiguous_paths_are_refused(bridge, path):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="path_refused"):
        bridge.request_headers("GET", path, headers(Host="127.0.0.1:50413"), 0)


@pytest.mark.parametrize(
    "values",
    [
        {"Host": "localhost:50413"},
        {"Host": "127.0.0.1:50414"},
        {"Host": "127.0.0.1:50413", "Origin": "null"},
        {"Host": "127.0.0.1:50413", "Origin": "https://elsewhere.invalid"},
        {"Host": "127.0.0.1:50413", "Sec_Fetch_Site": "cross-site"},
        {"Host": "127.0.0.1:50413", "Referer": "http://127.0.0.1:504130/"},
        {"Host": "127.0.0.1:50413", "Transfer_Encoding": "chunked"},
        {"Host": "127.0.0.1:50413", "Expect": "100-continue"},
    ],
)
def test_origin_host_and_framing_refusal(bridge, values):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.request_headers("GET", "/", headers(**values), 0)


def test_unsafe_request_still_needs_browser_origin_and_real_csrf(bridge):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="origin_refused"):
        bridge.request_headers(
            "POST", "/accounts/login/", headers(Host="127.0.0.1:50413"), 0
        )
    result = bridge.request_headers(
        "POST",
        "/accounts/login/",
        headers(
            Host="127.0.0.1:50413",
            Origin=bridge.origin,
            Referer=bridge.origin + "/accounts/login/",
            X_CSRFToken="real-form-token",
            Authorization="do-not-forward",
            X_Forwarded_Host="elsewhere.invalid",
        ),
        20,
    )
    assert result == {
        "Host": "127.0.0.1:50412",
        "Origin": bridge.backend,
        "Referer": bridge.backend + "/accounts/login/",
        "Accept-Encoding": "identity",
        "X-CSRFToken": "real-form-token",
    }


@pytest.mark.parametrize(
    "name",
    [
        "Host",
        "Cookie",
        "Origin",
        "Referer",
        "Content-Length",
        "Content-Type",
        "Content-Encoding",
        "X-CSRFToken",
        "X-Maru-File-Intent",
    ],
)
def test_ambiguous_duplicate_headers_refused(bridge, name):
    values = headers(Host="127.0.0.1:50413")
    if name != "Host":
        values[name] = "first"
    values[name] = "second"
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.request_headers("GET", "/", values, 0)


@pytest.mark.parametrize(
    ("method", "size"),
    [
        ("CONNECT", 0),
        ("DELETE", 0),
        ("POST", gateway.MAX_REQUEST + 1),
        ("GET", 1),
        ("POST", -1),
    ],
)
def test_closed_methods_and_body_budget(bridge, method, size):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.request_headers(
            method, "/", headers(Host="127.0.0.1:50413", Origin=bridge.origin), size
        )


def test_cookie_namespace_does_not_adopt_other_local_sessions(bridge):
    result = bridge.request_headers(
        "GET",
        "/",
        headers(
            Host="127.0.0.1:50413",
            Cookie=(
                "sessionid=foreign; csrftoken=foreign; "
                f"{bridge.cookie_prefix}sessionid=own; "
                f"maru_rehearsal_other_sessionid=other; "
                f"{bridge.cookie_prefix}csrftoken=csrf"
            ),
        ),
        0,
    )
    assert "sessionid=own" in result["Cookie"]
    assert "csrftoken=csrf" in result["Cookie"]
    assert "foreign" not in result["Cookie"]
    assert "other" not in result["Cookie"]
    response = headers(
        Set_Cookie="sessionid=own; Path=/; Secure; HttpOnly; SameSite=Lax"
    )
    _, mapped, _ = bridge.response(200, response, b"body")
    cookie = dict(mapped)["Set-Cookie"]
    assert bridge.cookie_prefix + "sessionid=own" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie
    assert "Secure" in response["Set-Cookie"]  # upstream is not modified


def test_success_message_cookie_survives_redirect_and_is_consumed(bridge):
    status, mapped, _ = bridge.response(
        302,
        headers(
            Location="/admin/",
            Set_Cookie="messages=signed-notice; Path=/; Secure; HttpOnly; SameSite=Lax",
        ),
        b"",
    )
    assert status == 302
    assert dict(mapped)["Location"] == "/admin/"
    cookie = dict(mapped)["Set-Cookie"]
    assert bridge.cookie_prefix + "messages=signed-notice" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie
    forwarded = bridge.request_headers(
        "GET",
        "/admin/",
        headers(
            Host="127.0.0.1:50413",
            Cookie=(
                "messages=foreign; maru_rehearsal_other_messages=other; "
                f"{bridge.cookie_prefix}messages=signed-notice"
            ),
        ),
        0,
    )
    assert forwarded["Cookie"] == "messages=signed-notice"
    _, consumed, _ = bridge.response(
        200,
        headers(Set_Cookie='messages=""; Max-Age=0; Path=/; SameSite=Lax'),
        b"",
    )
    assert 'messages=""' in dict(consumed)["Set-Cookie"]
    assert "Max-Age=0" in dict(consumed)["Set-Cookie"]


@pytest.mark.parametrize(
    "cookie",
    [
        "unknown=value; Path=/",
        "messages=value; Path=/private/",
        "messages=value; Path=/; Domain=foreign.invalid",
    ],
)
def test_success_messages_do_not_expand_cookie_scope(bridge, cookie):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="cookie_scope"):
        bridge.response(302, headers(Set_Cookie=cookie, Location="/admin/"), b"")


@pytest.mark.parametrize(
    "location",
    [
        "https://other.invalid/",
        "//other.invalid/",
        "https://127.0.0.1:504120/",
        "/\\other",
    ],
)
def test_backend_cannot_redirect_browser_to_another_origin(bridge, location):
    with pytest.raises(gateway.ProgrammeBrowserGatewayError):
        bridge.response(302, headers(Location=location), b"")


@pytest.mark.parametrize(
    "content_type", ["application/json", "application/zip", "text/calendar"]
)
def test_downloads_and_signed_bytes_are_never_rewritten(bridge, content_type):
    content = (bridge.backend + "/private/opaque").encode()
    _, _, actual = bridge.response(200, headers(Content_Type=content_type), content)
    assert actual == content


def test_only_html_fixture_origin_and_local_redirect_are_mapped(bridge):
    content = f'<a href="{bridge.backend}/admin/">work</a><a href="https://other.invalid/">other</a>'.encode()
    status, values, body = bridge.response(
        302,
        headers(
            Content_Type="text/html; charset=utf-8", Location=bridge.backend + "/admin/"
        ),
        content,
    )
    assert status == 302
    assert dict(values)["Location"] == "/admin/"
    expected = (
        f'<a href="{bridge.origin}/admin/">work</a>'
        '<a href="https://other.invalid/">other</a>'
    ).encode()
    assert body == expected
    assert dict(values)["Cache-Control"] == "private, no-store"
    assert int(dict(values)["Content-Length"]) == len(body)


def test_upstream_connection_is_fixed_and_closed(bridge, monkeypatch):
    connection = Mock()
    connection.getresponse.return_value = SimpleNamespace(
        status=200,
        headers=headers(Content_Type="text/plain"),
        read=Mock(return_value=b"ok"),
    )
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(gateway.http.client, "HTTPSConnection", constructor)
    bridge.exchange("GET", "/health/ready", headers(Host="127.0.0.1:50413"), b"")
    constructor.assert_called_once_with(
        "127.0.0.1", 50412, context=bridge.context, timeout=15
    )
    connection.close.assert_called_once_with()
    connection.getresponse.return_value.read.assert_called_once_with(
        gateway.MAX_PDF + 1
    )


def test_peer_and_incomplete_body_fail_before_upstream(bridge):
    handler = object.__new__(gateway._Handler)
    handler.client_address = ("192.0.2.1", 12345)
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="peer_refused"):
        handler._read_request()
    handler.client_address = ("127.0.0.1", 12345)
    handler.command, handler.path = "POST", "/accounts/login/"
    handler.headers = headers(
        Host="127.0.0.1:50413", Origin=bridge.origin, Content_Length="10"
    )
    handler.rfile = io.BytesIO(b"short")
    handler.server = SimpleNamespace(bridge=bridge)
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="body_incomplete"):
        handler._read_request()


def test_deadline_and_opt_in_rechecked_on_each_request(bridge, monkeypatch):
    monkeypatch.delenv(gateway.OPT_IN)
    with pytest.raises(gateway.ProgrammeBrowserGatewayError, match="opt_in_required"):
        bridge.request_headers("GET", "/", headers(Host="127.0.0.1:50413"), 0)
    monkeypatch.setenv(gateway.OPT_IN, "synthetic-loopback-only")
    monkeypatch.setattr(https.time, "monotonic", lambda: 400.0)
    with pytest.raises(https.ProgrammeHttpsError, match="expired"):
        bridge.request_headers("GET", "/", headers(Host="127.0.0.1:50413"), 0)


def test_listener_and_expiry_are_owned_and_cleanup_runs_on_failure(
    fixture, monkeypatch
):
    server = Mock(server_address=("127.0.0.1", 50501))
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=server)
    worker = Mock()
    timer = Mock()
    monkeypatch.setattr(gateway, "_Server", constructor)
    monkeypatch.setattr(gateway.threading, "Thread", Mock(return_value=worker))
    monkeypatch.setattr(gateway.threading, "Timer", Mock(return_value=timer))

    def fail_inside_listener():
        with gateway.local_programme_browser(fixture) as browser:
            assert browser.url == "http://127.0.0.1:50501"
            assert browser.deadline == fixture.deadline
            raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError, match="synthetic failure"):
        fail_inside_listener()
    constructor.assert_called_once_with(("127.0.0.1", 0), gateway._Handler)
    gateway.threading.Timer.assert_called_once_with(300.0, server.shutdown)
    worker.start.assert_called_once_with()
    timer.start.assert_called_once_with()
    timer.cancel.assert_called_once_with()
    server.shutdown.assert_called_once_with()
    worker.join.assert_called_once_with(timeout=5)
