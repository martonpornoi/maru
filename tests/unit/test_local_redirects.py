"""Browser-ambiguous redirect targets never cross the local-origin boundary."""

from urllib.parse import urljoin, urlsplit

import pytest
from django.core.exceptions import SuspiciousOperation

from maru.core.redirects import local_redirect


@pytest.mark.parametrize(
    "destination",
    [
        "",
        "relative/path",
        "https://outside.example/",
        "http://testserver/admin/",
        "https:/outside.example/",
        "https:///outside.example/",
        "javascript:alert(1)",
        "data:text/html,example",
        "//outside.example/",
        "///outside.example/",
        "////outside.example/",
        "//user:secret@outside.example/",
        "//[::1]/",
        "//[invalid/",
        "\\\\outside.example/",
        "/\\outside.example/",
        "\\/outside.example/",
        "/admin/\\outside.example/",
        " //outside.example/",
        "\t//outside.example/",
        "\r\n//outside.example/",
        "/\t/outside.example/",
        "/\n/outside.example/",
        "/\r/outside.example/",
        "/admin/\r\nLocation: https://outside.example/",
        "/admin/\x00receipt/",
        "/admin/\x7freceipt/",
    ],
)
def test_external_ambiguous_and_control_targets_fail_closed(destination):
    with pytest.raises(SuspiciousOperation, match="absolute local path") as error:
        local_redirect(destination)
    assert str(error.value) == "Redirect destination must be an absolute local path."


@pytest.mark.parametrize(
    "destination",
    [
        "/",
        "/admin/programme/receipt/",
        "/my/programme/hosting/?notice=00000000-0000-0000-0000-000000000001",
        "/mounted/maru/admin/programme/receipt/#result",
        "/admin/receipt/?next=https%3A%2F%2Foutside.example%2F",
        "/admin/receipt/%2F%2Foutside.example/",
    ],
)
def test_local_targets_retain_exact_path_query_and_fragment(destination):
    response = local_redirect(destination)
    assert response.status_code == 302
    assert response["Location"] == destination
    assert urlsplit(response["Location"]).scheme == ""
    assert urlsplit(response["Location"]).netloc == ""
    assert urlsplit(
        urljoin("https://maru.example.test/", response["Location"])
    ).netloc == ("maru.example.test")
