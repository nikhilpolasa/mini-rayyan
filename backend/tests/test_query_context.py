"""Optional query selectors isolate machine results without changing defaults."""

import csv
import io

from backend.tests.test_pipeline import save, pull, run


def pmids(response):
    assert response.status_code == 200
    return {
        row["pmid"]
        for row in csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    }


def test_detail_export_and_list_use_selected_query_context(review):
    client, _, source = review
    source.ids.update(alpha=["1"], beta=["1", "2"], gamma=["1"])
    source.records["1"].update(
        title="Alpha controlled trial",
        abstract="Adults received alpha versus placebo. The primary outcome was symptom change.",
    )
    source.records["2"].update(
        title="Beta therapy evaluation",
        abstract="Adults received beta versus placebo. The primary outcome was symptom change.",
    )
    first = save(client, "alpha")
    pull(client, first)
    run(client, first)
    old = client.get(f"/api/records/1?query_id={first}").json()
    assert old["label"] == "include" and old["pico_spans"]
    second = save(client, "beta")
    pull(client, second)
    run(client, second)
    # Omitted selectors retain the latest-context behaviour.
    latest = client.get("/api/records/1").json()
    assert latest["label"] == "maybe" and latest["pico_spans"] == []
    selected = client.get(f"/api/records/1?query_id={first}").json()
    assert (
        selected["label"] == "include" and selected["pico_spans"] == old["pico_spans"]
    )
    assert client.get(f"/api/records/1?query_id={second}").json() == latest
    assert (
        client.get(f"/api/records?query_id={first}&label=include").json()["total"] == 1
    )
    assert pmids(client.get(f"/api/export.csv?query_id={first}")) == {"1"}
    assert pmids(client.get(f"/api/export.csv?query_id={second}")) == {"2"}
    assert pmids(client.get("/api/export.csv")) == {"2"}
    # A linked but unprocessed query must not fall back to another query.
    third = save(client, "gamma")
    pull(client, third)
    pending = client.get(f"/api/records/1?query_id={third}").json()
    assert pending["label"] == "maybe" and pending["reason"] == "Not screened yet."
    assert pending["pico_spans"] == []
    assert pmids(client.get(f"/api/export.csv?query_id={third}")) == set()
    assert client.get(f"/api/records/2?query_id={first}").status_code == 404
    for path in ["/api/records/1", "/api/export.csv"]:
        assert client.get(path + "?query_id=999").status_code == 404
        assert client.get(path + "?query_id=0").status_code == 422


def test_two_included_queries_keep_distinct_pico_run_provenance(review):
    client, _, source = review
    source.ids.update(alpha=["1"], **{"alpha OR beta": ["1"]})
    source.records["1"][
        "abstract"
    ] = "Adults received alpha versus placebo. The primary outcome was symptom change."
    snapshots = {}
    for text in ["alpha", "alpha OR beta"]:
        query = save(client, text)
        pull(client, query)
        run(client, query)
        snapshots[query] = client.get(f"/api/records/1?query_id={query}").json()[
            "pico_spans"
        ]
    first, second = snapshots
    assert snapshots[first] and snapshots[second]
    assert {row["run_id"] for row in snapshots[first]}.isdisjoint(
        row["run_id"] for row in snapshots[second]
    )
    for query, expected in snapshots.items():
        assert (
            client.get(f"/api/records/1?query_id={query}").json()["pico_spans"]
            == expected
        )
    assert client.get("/api/records/1").json()["pico_spans"] == snapshots[second]
