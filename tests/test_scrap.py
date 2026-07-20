import pytest

from discoger import scrap


class Resp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP %s" % self.status_code)


class Http:
    """Fake session returning queued responses; the last one repeats."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        resp = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(resp, Exception):
            raise resp
        return resp


LISTING_HTML = """
<table class="mpitems">
  <tr><th>header</th></tr>
  <tr>
    <td>
      <a class="item_description_title" href="/sell/item/123456">Pink Floyd - Animals (LP, Album)</a>
      <p class="item_condition">
        <span class="mplabel">Media Condition:</span>
        <span class="has-tooltip">?</span>
        <span>Very Good Plus (VG+)</span>
        <span class="item_sleeve_condition">Near Mint (NM or M-)</span>
      </p>
    </td>
    <td class="seller_info"><ul><li>Ships From:France</li></ul></td>
    <td><span class="price" data-currency="EUR" data-pricevalue="25.00">25,00 EUR</span></td>
  </tr>
</table>
"""


def test_parses_listing():
    sell = scrap.check_sales(Http(Resp(text=LISTING_HTML)), "https://x", True, "42", "release")
    assert sell == {
        "id": "123456",
        "price": "EUR 25.00",
        "url": "https://www.discogs.com/sell/item/123456",
        "media_condition": "Very Good Plus (VG+)",
        "sleeve_condition": "Near Mint (NM or M-)",
        "shipping_from": "France",
    }


def test_no_listing_returns_none():
    assert scrap.check_sales(Http(Resp(text="<html></html>")), "https://x", True, "42", "release") is None


def test_unofficial_skipped():
    html = LISTING_HTML.replace("Animals (LP, Album)", "Animals (LP, Unofficial Release)")
    assert scrap.check_sales(Http(Resp(text=html)), "https://x", True, "42", "release") is None
    sell = scrap.check_sales(Http(Resp(text=html)), "https://x", False, "42", "release")
    assert sell["id"] == "123456"


def test_cloudflare_403_raises_after_retries(monkeypatch):
    monkeypatch.setattr(scrap.time, "sleep", lambda s: None)
    http = Http(Resp(status=403, headers={"cf-mitigated": "challenge"}))
    with pytest.raises(scrap.ScrapeError) as exc:
        scrap.check_sales(http, "https://x", True, "42", "master")
    assert exc.value.cloudflare is True
    assert http.calls == 3


def test_cloudflare_retry_recovers(monkeypatch):
    monkeypatch.setattr(scrap.time, "sleep", lambda s: None)
    http = Http(Resp(status=403), Resp(text=LISTING_HTML))
    sell = scrap.check_sales(http, "https://x", True, "42", "release")
    assert sell["id"] == "123456"
    assert http.calls == 2


def test_transient_network_error_recovers(monkeypatch):
    monkeypatch.setattr(scrap.time, "sleep", lambda s: None)
    http = Http(ConnectionError("curl: (35) TLS connect error"), Resp(text=LISTING_HTML))
    sell = scrap.check_sales(http, "https://x", True, "42", "release")
    assert sell["id"] == "123456"
    assert http.calls == 2


def test_persistent_network_error_raises(monkeypatch):
    monkeypatch.setattr(scrap.time, "sleep", lambda s: None)
    http = Http(ConnectionError("curl: (35) TLS connect error"))
    with pytest.raises(scrap.ScrapeError) as exc:
        scrap.check_sales(http, "https://x", True, "42", "release")
    assert exc.value.cloudflare is False
    assert http.calls == 3


def test_non_cloudflare_error(monkeypatch):
    monkeypatch.setattr(scrap.time, "sleep", lambda s: None)
    with pytest.raises(scrap.ScrapeError) as exc:
        scrap.check_sales(Http(Resp(status=500)), "https://x", True, "42", "release")
    assert exc.value.cloudflare is False
