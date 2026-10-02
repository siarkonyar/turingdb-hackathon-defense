"""HTTP contract tests (docs/api.md) against the mock backend over the tiny fixture in conftest.py."""

from __future__ import annotations


def ids(nodes):
    return sorted(n["id"] for n in nodes)


def test_health_and_meta(client):
    assert client.get("/health").json() == {"status": "ok"}
    meta = client.get("/meta").json()
    assert meta["engine"] == "fixtures" and "cyber" in meta["layers"]


def test_nodes_filters_by_type_and_bbox_and_reports_latency(client):
    body = client.get("/nodes?types=plant,site").json()
    assert ids(body["nodes"]) == ["P1", "P2", "S1", "S2"]
    assert body["branch"] == "main" and body["engine"] == "fixtures" and body["latency_ms"] >= 0
    boxed = client.get("/nodes?types=site&bbox=-3,52,-1,54").json()
    assert ids(boxed["nodes"]) == ["S1"]
    assert boxed["nodes"][0]["exposure"] == 3000
    assert "status" not in boxed["nodes"][0]  # null fields are omitted


def test_nodes_rejects_bad_parameters(client):
    assert client.get("/nodes?types=tank").status_code == 422
    assert client.get("/nodes?bbox=1,2,3").status_code == 422
    assert client.get("/nodes?branch=nope").status_code == 422
    assert client.get("/nodes?branch=99").status_code == 404


def test_neighbours_groups_by_relationship(client):
    body = client.get("/node/S1/neighbours").json()
    groups = {(g["rel"], g["direction"]): g for g in body["groups"]}
    assert ids(groups[("POWERED_BY", "out")]["nodes"]) == ["P1", "P2"]
    assert ids(groups[("PATROLS", "in")]["nodes"]) == ["D1"]
    assert body["properties"]["name"] == "S1"
    assert client.get("/node/NOPE/neighbours").status_code == 404


def test_simulate_creates_branch_with_cascade_arcs_and_kpis(client):
    body = client.post("/simulate", json={"node_id": "P1"}).json()
    assert body["base_branch"] == "main" and body["branch"] == "2"  # hypothesis 1 already exists
    assert body["struck"]["status"] == "lost"
    affected = {a["node"]["id"]: (a["node"]["status"], a["hop"], a["via"]) for a in body["affected"]}
    assert affected == {"S1": ("at_risk", 1, "POWERED_BY"), "D1": ("at_risk", 2, "PATROLS")}
    assert [(a["source_id"], a["target_id"]) for a in body["arcs"]] == [("P1", "S1"), ("S1", "D1")]
    assert body["kpis"] == {"assets_at_risk": 2, "sites_without_power": 0, "suppliers_without_power": 0,
                            "parts_affected": 0}
    assert ids(client.get("/nodes?types=plant&branch=2").json()["nodes"]) == ["P2"]
    assert ids(client.get("/nodes?types=plant").json()["nodes"]) == ["P1", "P2"]  # main untouched


def test_stacked_strikes_escalate_to_no_power(client):
    branch = client.post("/simulate", json={"node_id": "P1"}).json()["branch"]
    body = client.post("/simulate", json={"node_id": "P2", "base_branch": branch}).json()
    assert body["branch"] == branch
    assert ids(body["lost"]) == ["P2", "S1"]
    assert body["kpis"]["sites_without_power"] == 1
    labels = {b["id"]: b["label"] for b in client.get("/branches").json()["branches"]}
    assert labels[branch] == "Strike · P1 + P2"


def test_simulate_errors(client):
    assert client.post("/simulate", json={"node_id": "NOPE"}).status_code == 404
    assert client.post("/simulate", json={"node_id": "P1", "base_branch": "1"}).status_code == 409
    assert client.post("/simulate", json={"node_id": ""}).status_code == 422


def test_supplier_strike_reaches_sites_through_parts(client):
    body = client.post("/simulate", json={"node_id": "U1"}).json()
    assert {a["node"]["id"] for a in body["affected"]} == {"X1", "S2"}
    assert [(a["source_id"], a["target_id"]) for a in body["arcs"]] == [("U1", "S2")]
    assert body["kpis"]["parts_affected"] == 1


def test_diff_between_branches_and_commits(client):
    branch = client.post("/simulate", json={"node_id": "P1"}).json()["branch"]
    diff = client.get(f"/diff?a=main&b={branch}").json()
    assert ids(diff["removed"]) == ["P1"] and diff["added"] == []
    assert {c["node"]["id"]: c["fields"]["status"] for c in diff["changed"]} == {
        "S1": [None, "at_risk"], "D1": [None, "at_risk"]}
    commits = client.get("/diff?a=main@aaaa&b=main@cccc").json()
    assert ids(commits["added"]) == ["R1", "R2"]
    assert client.get("/diff?a=main&b=main@dddd").status_code == 404


def test_branches_list_main_history_and_hypotheses(client):
    branches = client.get("/branches").json()["branches"]
    main, hyp = branches[0], branches[1]
    assert [c["hash"] for c in main["commits"]] == ["aaaa000000000000", "bbbb000000000000", "cccc000000000000"]
    assert [c["time"] for c in main["commits"]] == [None, "2026-09-29T06:00:00Z", "2026-09-29T08:00:00Z"]
    assert (hyp["kind"], hyp["confidence"]) == ("hypothesis", 0.6)
    on_h1 = client.get("/nodes?types=site&branch=1").json()["nodes"]
    assert {n["id"]: n.get("status") for n in on_h1} == {"S1": None, "S2": "at_risk"}


def test_discard_only_strike_branches(client):
    branch = client.post("/simulate", json={"node_id": "P1"}).json()["branch"]
    assert client.delete(f"/branches/{branch}").status_code == 204
    assert client.get(f"/nodes?branch={branch}").status_code == 404
    assert client.delete("/branches/1").status_code == 409
    assert client.delete("/branches/77").status_code == 404


def test_reports_until_and_links(client):
    early = client.get("/reports?until=2026-09-29T07:00:00Z").json()["reports"]
    assert [r["report_id"] for r in early] == ["R1"]
    both = client.get("/reports").json()["reports"]
    r2 = both[1]
    assert (r2["mentions"], r2["contradicts"], r2["claim"]) == (["U1"], "R1", "disrupted")
    at_commit = client.get("/reports?branch=main@bbbb").json()["reports"]
    assert [r["report_id"] for r in at_commit] == ["R1"]
    assert client.get("/reports?until=soon").status_code == 422


def test_tracks_hide_struck_drones(client):
    assert [t["id"] for t in client.get("/tracks").json()["tracks"]] == ["D1"]
    branch = client.post("/simulate", json={"node_id": "D1"}).json()["branch"]
    assert client.get(f"/tracks?branch={branch}").json()["tracks"] == []
