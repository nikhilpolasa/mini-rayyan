"""Historical query projections use stored links and never modify evidence."""

from sqlalchemy import select, func

from app import models as m
from app.services import dedup


def _save(client, text):
    response = client.post("/api/queries", json={"text": text, "date_from": "2020-01-01", "date_to": "2026-01-01"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _fetch(client, id):
    assert client.post(f"/api/queries/{id}/approve").status_code == 200
    assert client.post(f"/api/queries/{id}/fetch").status_code == 200


def test_as_of_repeats_and_diff_after_new_query_and_human_label(review):
    client, factory, source = review
    first = _save(client, "first")
    _fetch(client, first)
    before = client.get(f"/api/queries/{first}/as-of").json()
    second = _save(client, "second")
    _fetch(client, second)
    assert client.post(f"/api/pipeline/run?query_id={second}").status_code == 200
    assert client.post("/api/decisions", json={"entity_type": "record", "entity_id": 2, "action": "set_label", "new_value": {"label": "exclude"}, "note": "reviewed"}).status_code == 200
    after = client.get(f"/api/queries/{first}/as-of").json()
    assert (before["record_ids"], before["groups"], before["state_hash"]) == (after["record_ids"], after["groups"], after["state_hash"])
    diff = client.get(f"/api/queries/{second}/diff").json()
    assert diff["records_added"] == [3]
    assert diff["records_removed"] == [1]
    assert diff["records_common"] == [2]
    assert diff["counts"] == {"added": 1, "removed": 1, "common": 1, "groups_newly_merged": 0}
    assert diff["common_with_human_decision"] == [2]
    assert client.get(f"/api/queries/{first}/diff").status_code == 400
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.QueryRecord)) == 4


def test_bridge_two_base_groups_and_empty_diff(review):
    client, factory, source = review
    source.records["5"] = {**source.records["1"], "pmid": "5", "doi": None, "title": "Bridge record"}
    source.records["2"]["doi"] = source.records["1"]["doi"] = "10.0/a"
    source.records["4"]["doi"] = source.records["3"]["doi"] = "10.0/b"
    source.ids = {"base": ["1", "2", "3", "4"], "later": ["1", "2", "3", "4", "5"], "same": ["1", "2", "3", "4", "5"]}
    base = _save(client, "base"); _fetch(client, base)
    later = _save(client, "later"); _fetch(client, later)
    with factory.begin() as session:
        for pair in ("2:5", "3:5"):
            session.add(m.Decision(entity_type="pair", entity_id=pair, action="confirm", old_value={"status": "pending"}, new_value={"status": "confirmed"}, note="reviewed"))
    diff = client.get(f"/api/queries/{later}/diff?base={base}").json()
    assert diff["records_added"] == [5]
    assert diff["groups_newly_merged"] == [{"representative_record_id": 1, "member_ids": [1, 2, 3, 4, 5], "base_group_ids": [1, 3]}]
    assert client.get(f"/api/queries/{base}/as-of").json()["groups"] == [
        {"representative_record_id": 1, "members": [1, 2], "hidden": [2]},
        {"representative_record_id": 3, "members": [3, 4], "hidden": [4]},
    ]
    same = _save(client, "same"); _fetch(client, same)
    empty = client.get(f"/api/queries/{same}/diff?base={later}").json()
    assert empty["records_added"] == empty["records_removed"] == empty["groups_newly_merged"] == []
    assert empty["counts"] == {"added": 0, "removed": 0, "common": 5, "groups_newly_merged": 0}
    assert dedup.compute_groups([], set(), set()) == []
