"""Offline parser and transport checks. All HTTP uses httpx.MockTransport."""

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs
from xml.etree.ElementTree import ParseError

import httpx
import pytest

from app.services import pubmed as p

FIXTURES = Path(__file__).parent / "fixtures"
START, END = date(2016, 1, 1), date(2026, 10, 27)


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    """Set fake credentials and replace timing, without changing global time."""
    monkeypatch.setenv("NCBI_EMAIL", "unit-test@example.org")
    monkeypatch.setenv("NCBI_TOOL", "unit-tests")
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.setenv("FETCH_CAP", "500")
    monkeypatch.setattr(p, "load_dotenv", lambda *args: None)
    monkeypatch.setattr(p, "_last_request", None)
    clock = {"now": 0.0, "sleeps": []}

    def sleep(seconds):
        clock["sleeps"].append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(p, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(p, "sleep", sleep)
    return clock


def test_parse_saved_xml():
    records = p.parse_records((FIXTURES / "pubmed_articles.xml").read_bytes())
    assert [record["pmid"] for record in records] == [
        "100001",
        "100002",
        "100003",
        "100004",
        "100005",
    ]
    assert records[0] == {
        "pmid": "100001",
        "doi": "10.0000/example.1",
        "title": "Exercise with guided practice and H2O.",
        "abstract": "Adults with sleep difficulties were enrolled.\nWe compared walking & usual care.\nMean score changed by 22 points.",
        "authors": ["García Ana", "Example Study Group", "Lee JK Jr", "Mononym"],
        "year": 2024,
        "journal": "Fictional Trials Journal",
        "language": "eng",
        "pub_types": ["Randomized Controlled Trial", "Journal Article"],
        "mesh": ["Humans", "Adult"],
        "source": "pubmed",
    }
    assert records[1]["year"] == 2021
    assert records[1]["journal"] == "Fict J"
    assert records[1]["title"] == "非英語の架空研究"
    assert records[1]["language"] == "jpn"
    assert records[1]["abstract"] is None
    assert records[2]["year"] == 2018
    assert records[2]["abstract"] is None
    assert records[2]["title"] == ""
    assert records[3]["year"] is None
    assert records[3]["abstract"] == "One unstructured abstract."
    assert records[4] == {
        "pmid": "100005",
        "doi": None,
        "title": "",
        "abstract": None,
        "authors": [],
        "year": None,
        "journal": None,
        "language": None,
        "pub_types": [],
        "mesh": [],
        "source": "pubmed",
    }


def test_parser_errors_and_empty_set():
    with pytest.raises(ValueError, match="EFetch error"):
        p.parse_records((FIXTURES / "pubmed_error.xml").read_bytes())
    with pytest.raises(ParseError):
        p.parse_records("<broken")
    with pytest.raises(ValueError, match="PubmedArticleSet"):
        p.parse_records("<unexpected/>")
    assert p.parse_records("<PubmedArticleSet/>") == []


def test_search_count_contract_and_parameters(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "fake-test-key")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "esearchresult": {"count": "42", "querytranslation": "translated query"}
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with p.LiveSourceClient(client=http) as client:
            assert client.search_count("exercise", START, END) == {
                "hit_count": 42,
                "translation": "translated query",
            }
        assert not http.is_closed  # Caller-owned HTTP clients are not closed.
    request = requests[0]
    assert str(request.url).startswith(p.BASE_URL + "/esearch.fcgi?")
    assert request.method == "GET"
    assert dict(request.url.params) == {
        "term": "exercise",
        "db": "pubmed",
        "retmode": "json",
        "retmax": "0",
        "retstart": "0",
        "datetype": "pdat",
        "mindate": "2016-01-01",
        "maxdate": "2026-10-27",
        "tool": "unit-tests",
        "email": "unit-test@example.org",
        "api_key": "fake-test-key",
    }


def test_search_ids_pages_cap_and_pacing(offline_environment, monkeypatch):
    monkeypatch.setenv("FETCH_CAP", "450")
    requests, times = [], []

    def handler(request):
        requests.append(request)
        times.append(offline_environment["now"])
        start = int(request.url.params["retstart"])
        size = int(request.url.params["retmax"])
        return httpx.Response(
            200,
            json={
                "esearchresult": {
                    "count": "9000",
                    "idlist": [str(i) for i in range(start, start + size)],
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with p.LiveSourceClient(client=http) as client:
            ids = client.search_ids("exercise", START, END, limit=700, offset=10)
    assert ids == [str(i) for i in range(10, 460)]
    assert [(r.url.params["retmax"], r.url.params["retstart"]) for r in requests] == [
        ("200", "10"),
        ("200", "210"),
        ("50", "410"),
    ]
    assert times == pytest.approx([0, 0.34, 0.68])
    assert all(
        r.url.params["datetype"] == "pdat" and "api_key" not in r.url.params
        for r in requests
    )


@pytest.mark.parametrize("count,ids", [("0", []), ("3", ["1", "2", "3"]), ("900", [])])
def test_search_stops_on_empty_or_short_page(count, ids):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"esearchresult": {"count": count, "idlist": ids}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert p.LiveSourceClient(client=http).search_ids("example", START, END) == ids
    assert len(calls) == 1


def test_search_ceiling_and_noop_inputs(monkeypatch):
    monkeypatch.setenv("FETCH_CAP", "20000")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"esearchresult": {"count": "50000", "idlist": ["1", "2"]}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = p.LiveSourceClient(client=http)
        assert client.search_ids("example", START, END, limit=500, offset=9998) == [
            "1",
            "2",
        ]
        assert calls[0].url.params["retmax"] == "2"
        assert client.search_ids("example", START, END, offset=10000) == []
        assert client.search_ids("example", START, END, limit=0) == []
        assert client.fetch_records([]) == []
        assert len(calls) == 1


def test_fetch_post_batches_and_parse(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "fake-test-key")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, content=(FIXTURES / "pubmed_articles.xml").read_bytes()
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        records = p.LiveSourceClient(client=http).fetch_records(
            [str(i) for i in range(1, 402)]
        )
    assert len(records) == 15
    batches = []
    for request in calls:
        assert request.method == "POST"
        assert str(request.url) == p.BASE_URL + "/efetch.fcgi"
        form = parse_qs(request.content.decode())
        batches.append(form["id"][0].split(","))
        assert form["retmode"] == ["xml"]
        assert form["db"] == ["pubmed"]
        assert form["tool"] == ["unit-tests"]
        assert form["email"] == ["unit-test@example.org"]
        assert form["api_key"] == ["fake-test-key"]
    assert [len(batch) for batch in batches] == [200, 200, 1]
    assert sum(batches, []) == [str(i) for i in range(1, 402)]


@pytest.mark.parametrize("post", [False, True])
def test_retry_429_5xx_backoff_and_shared_pacing(post, offline_environment):
    times = []
    statuses = iter([429, 503, 500, 200])

    def handler(request):
        times.append(offline_environment["now"])
        return httpx.Response(
            next(statuses), json={"esearchresult": {"count": "0"}}, content=None
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = p.LiveSourceClient(client=http)
        assert (
            client._request(
                "efetch.fcgi" if post else "esearch.fcgi", {}, post=post
            ).status_code
            == 200
        )
        # A second instance shares pacing with the first.
        times_before = offline_environment["now"]
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ) as second:
            p.LiveSourceClient(client=second)._request("esearch.fcgi", {})
        assert offline_environment["now"] - times_before == pytest.approx(0.34)
    assert times == [0.0, 1.0, 3.0, 7.0]


@pytest.mark.parametrize(
    "status,attempts", [(400, 1), (401, 1), (404, 1), (429, 4), (500, 4), (599, 4)]
)
def test_terminal_http_errors(status, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(httpx.HTTPStatusError):
            p.LiveSourceClient(client=http).search_count("example", START, END)
    assert len(calls) == attempts


@pytest.mark.parametrize("retry_after,expected", [("5", 5.0), ("invalid", 1.0)])
def test_retry_after(retry_after, expected, offline_environment):
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": retry_after}), httpx.Response(200)]
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as http:
        p.LiveSourceClient(client=http)._request("esearch.fcgi", {})
    assert offline_environment["sleeps"] == [expected]


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "invalid"},
        {"esearchresult": {"ERROR": "invalid"}},
        {"esearchresult": {"errorlist": {"FieldNotFound": ["bad"]}}},
        {},
    ],
)
def test_esearch_payload_errors(payload):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(ValueError):
            p.LiveSourceClient(client=http).search_count("example", START, END)


def test_validation_before_network(monkeypatch):
    def unexpected(request):
        pytest.fail("Invalid inputs must not issue HTTP requests")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as http:
        client = p.LiveSourceClient(client=http)
        for text, start, end in [(" ", START, END), ("query", END, START)]:
            with pytest.raises(ValueError):
                client.search_count(text, start, end)
        for limit, offset in [(-1, 0), (1, -1)]:
            with pytest.raises(ValueError):
                client.search_ids("query", START, END, limit, offset)
        for pmids in [[""], ["1,2"], ["DEMO-1"], [None], ["１２"]]:
            with pytest.raises(ValueError):
                client.fetch_records(pmids)
        monkeypatch.setenv("FETCH_CAP", "0")
        assert p.LiveSourceClient(client=http).search_ids("example", START, END) == []
        monkeypatch.setenv("FETCH_CAP", "-1")
        with pytest.raises(ValueError, match="FETCH_CAP"):
            p.LiveSourceClient(client=http)
        monkeypatch.setenv("NCBI_EMAIL", "")
        with pytest.raises(ValueError, match="NCBI_EMAIL"):
            p.LiveSourceClient(client=http)


def test_default_tool_and_owned_client(monkeypatch):
    monkeypatch.delenv("NCBI_TOOL", raising=False)
    client = p.LiveSourceClient()
    assert client.tool == "mini-rayyan"
    with client:
        assert not client._client.is_closed
    assert client._client.is_closed


@pytest.mark.parametrize("client_class", [p.SourceClient, p.SnapshotSourceClient])
def test_unimplemented_sources(client_class):
    client = client_class()
    for method, args in [
        (client.search_count, ("example", START, END)),
        (client.search_ids, ("example", START, END)),
        (client.fetch_records, ([],)),
    ]:
        with pytest.raises(NotImplementedError):
            method(*args)
