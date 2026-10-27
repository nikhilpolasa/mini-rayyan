"""PRD 15 API acceptance, in a new temporary DB with real rule functions.

Run: python -m pytest -c backend/pytest.ini backend/tests/test_acceptance.py -q -s
Only the external source is controlled. This is not a browser/Excel/live test.
"""

from contextlib import contextmanager
import csv
import io

from sqlalchemy import select, func

from app import models as m
from app.services.matching import pair_score


def test_prd_section_15_acceptance(review):
    client, factory, source = review
    first_text = "alpha[tiab] AND placebo[tiab]"
    second_text = "(alpha[tiab] OR beta[tiab]) AND placebo[tiab]"
    abstract = 'Adults received alpha versus placebo.\nThe primary outcome was "symptom, change" after eight weeks.'
    title = "Randomized evaluation of alpha treatment for chronic symptoms in adults"
    source.records = {
        str(index): {
            "pmid": str(index),
            "doi": f"10.0000/acceptance.{index}",
            "title": f"Controlled alpha placebo investigation {index}",
            "abstract": abstract,
            "authors": [f"Author{index} A"],
            "year": 2024,
            "journal": "Fictional Trials",
            "language": "eng",
            "pub_types": ["Journal Article"],
            "mesh": ["Humans", "Adult"],
            "source": "pubmed",
        }
        for index in range(1, 12)
    }
    source.records["2"]["doi"] = source.records["1"]["doi"]
    for index in [3, 4, 5]:
        source.records[str(index)].update(doi=None, title=title, authors=["Smith A"])
    source.records["4"]["title"] += "."
    source.records["5"]["title"] = title.replace("chronic", "persistent")
    source.records["6"].update(
        title="Laboratory alpha placebo study in mice", mesh=["Animals"]
    )
    source.records["7"].update(
        title="German alpha placebo investigation", language="deu"
    )
    source.records["8"].update(
        title="Alpha placebo clinical case report", pub_types=["Case Reports"]
    )
    source.records["9"].update(
        title="Alpha placebo computational model",
        abstract="A simulation compared alpha with placebo.",
    )
    source.records["10"].update(
        title="Alpha placebo metadata-only report", abstract=None
    )
    source.records["11"].update(
        title="Beta placebo controlled trial",
        abstract=abstract.replace("alpha", "beta"),
    )
    source.ids = {
        first_text: [str(i) for i in range(1, 11)],
        second_text: [str(i) for i in range(1, 12)],
    }
    results, counts = {}, []

    @contextmanager
    def step(number):
        try:
            yield
        except Exception:
            results[number] = "FAIL"
            raise
        else:
            results[number] = "PASS (automated API assertions)"

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, response.text
        with factory() as session:
            count = session.scalar(select(func.count()).select_from(m.Record))
        assert not counts or count >= counts[-1], "Record count decreased"
        counts.append(count)
        return response

    def save(text):
        return request(
            "POST",
            "/api/queries",
            json={
                "text": text,
                "date_from": "2016-01-01",
                "date_to": "2026-10-27",
            },
        ).json()

    def run(query_id):
        job = request("POST", f"/api/pipeline/run?query_id={query_id}").json()
        logs = request("GET", f"/api/runs?query_id={query_id}").json()
        assert (
            next(row for row in logs if row["id"] == job["run_id"])["status"]
            == "completed"
        )

    def decide(entity_type, entity_id, action, value):
        return request(
            "POST",
            "/api/decisions",
            json={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "new_value": value,
                "note": "Acceptance reviewer checked.",
            },
        ).json()

    try:
        with step(1):
            first = save(first_text)
            assert (
                first["version"] == 1
                and first["hit_count"] > 0
                and first["translation"]
            )
            first_before = request("GET", f"/api/queries/{first['id']}").json()
        with step(2):
            second = save(second_text)
            versions = request("GET", "/api/queries").json()
            assert [row["version"] for row in versions] == [1, 2]
            assert versions[1]["parent_id"] == first["id"]
            assert request("GET", f"/api/queries/{first['id']}").json() == first_before
        with step(3):
            for query in [first, second]:
                request("POST", f"/api/queries/{query['id']}/approve")
                request("POST", f"/api/queries/{query['id']}/fetch")
                assert (
                    request("GET", f"/api/queries/{query['id']}").json()["status"]
                    == "fetched"
                )
            assert source.fetches == [[str(i) for i in range(1, 11)], ["11"]]
            with factory() as session:
                assert session.scalar(select(func.count()).select_from(m.Record)) == 11
                assert (
                    session.scalar(select(func.count()).select_from(m.QueryRecord))
                    == 21
                )
        with step(4):
            assert pair_score(source.records["3"], source.records["4"])["score"] >= 0.95
            assert (
                0.85
                <= pair_score(source.records["3"], source.records["5"])["score"]
                < 0.95
            )
            run(second["id"])
            duplicates = request("GET", "/api/duplicates").json()
            assert len(duplicates["groups"]) == 2 and duplicates["uncertain_pairs"]
            assert {
                member["match_type"]
                for group in duplicates["groups"]
                for member in group["members"]
            } == {"exact", "fuzzy"}
            visible = request("GET", "/api/records").json()
            all_records = request("GET", "/api/records?show_hidden=true").json()
            assert all_records["total"] == 11 and visible["total"] == 9
            assert {
                row["id"] for row in all_records["items"] if row["hidden_duplicate"]
            } == {2, 4}
        with step(5):
            rows = {row["id"]: row for row in visible["items"]}
            assert {row["label"] for row in rows.values()} == {
                "include",
                "exclude",
                "maybe",
            }
            for index, criterion in [
                (6, "non_human"),
                (7, "non_english"),
                (8, "case_report"),
                (9, "simulation"),
            ]:
                assert rows[index]["label"] == "exclude"
                assert rows[index]["criterion"] == criterion and rows[index]["reason"]
            assert (
                rows[10]["label"] == "maybe" and rows[10]["criterion"] == "no_abstract"
            )
            with factory() as session:
                assert set(session.scalars(select(m.ScreenResult.record_id))) == set(
                    rows
                )
        with step(6):
            detail = request("GET", "/api/records/1").json()
            assert detail["label"] == "include" and detail["pico_spans"]
            assert {span["label"] for span in detail["pico_spans"]} >= {
                "P",
                "I",
                "C",
                "O",
            }
            for span in detail["pico_spans"]:
                assert detail["abstract"][span["start"] : span["end"]] == span["text"]
        with step(7):
            decide("record", 6, "set_label", {"label": "include"})
            decide("pair", "3:5", "confirm", {"status": "confirmed"})
            assert request("GET", "/api/records/5").json()["hidden_duplicate"] is True
            decide("pair", "3:5", "reject", {"status": "rejected"})
            assert request("GET", "/api/records/5").json()["hidden_duplicate"] is False
            span = detail["pico_spans"][0]
            new_label = "O" if span["label"] != "O" else "P"
            decide("pico_span", span["id"], "relabel", {"label": new_label})
            edited = request("GET", "/api/records/1").json()["pico_spans"]
            assert any(
                row["source"] == "human"
                and row["label"] == new_label
                and row["text"] == span["text"]
                for row in edited
            )
            audit = request("GET", "/api/decisions").json()
            assert {row["entity_type"] for row in audit} == {
                "record",
                "pair",
                "pico_span",
            }
            assert len(audit) == 4
        with step(8):
            for _ in range(2):
                run(second["id"])
                assert request("GET", "/api/decisions").json() == audit
                assert request("GET", "/api/records/1").json()["pico_spans"] == edited
                row = request("GET", "/api/records/6").json()
                assert row["label"] == "include" and row["source"] == "human"
                assert (
                    request("GET", "/api/records/5").json()["hidden_duplicate"] is False
                )
        with step(9):
            response = request("GET", "/api/export.csv")
            assert response.content.startswith(b"\xef\xbb\xbf")
            exported = list(
                csv.DictReader(
                    io.StringIO(response.content.decode("utf-8-sig"), newline="")
                )
            )
            included = request("GET", "/api/records?label=include").json()["items"]
            assert {row["pmid"] for row in exported} == {
                row["pmid"] for row in included
            }
            assert (
                next(row for row in exported if row["pmid"] == "1")["abstract"]
                == abstract
            )
            assert all(row["label"] == "include" for row in exported)
        with step(10):
            assert counts == sorted(counts) and counts[-1] == 11
            with factory() as session:
                assert session.scalar(select(func.count()).select_from(m.Record)) == 11
    finally:
        for number in range(1, 11):
            print(f"PRD 15 step {number}: {results.get(number, 'NOT RUN')}")
        print(
            "Browser interaction, live PubMed and opening CSV in Excel: NOT VERIFIED by this harness"
        )
