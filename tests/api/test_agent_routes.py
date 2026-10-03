"""Agent + wargame routes over a fake hub: background jobs, the SSE stream, injects, controls and replay.
No TuringDB and no LLM: the hub hands out the fake board and model from tests/agents/test_match.py."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.engine import Step
from agents.match import Match
from api.agent_routes import register_agent_routes
from api.main import create_app
from tests.agents.test_match import FakeBoard, FakeLLM, fake_injector


class GatedLLM(FakeLLM):
    """Blocks its first call until the test opens the gate (to act mid-match deterministically)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.first_call = threading.Event()

    def chat(self, messages, agent="agent", **kw):
        self.first_call.set()
        self.gate.wait(timeout=10)
        return super().chat(messages, agent=agent, **kw)


class FakeHub:
    def __init__(self, matches_dir: Path, llm=None, llm_error: str | None = None) -> None:
        self.matches_dir = matches_dir
        self.fake_board = FakeBoard()
        self.fake_board.add_base("50", [{"action": "wipe_bbox", "args": {}}])
        self.fake_llm = llm or FakeLLM()
        self.llm_error = llm_error

    def board(self):
        return self.fake_board

    def llm(self):
        if self.llm_error:
            from agents.llm import LLMUnavailable

            raise LLMUnavailable(self.llm_error)
        return self.fake_llm

    def injector(self):
        return fake_injector(self.fake_board)

    def status(self) -> dict:
        return {"available": not self.llm_error, "model": "fake-model", "reason": self.llm_error}

    def scenario(self, question, steps, on_step):
        on_step("scenario", Step("find the place", "places", {}, {"places": ["Manchester"]}))
        return {"branch": "77", "explanation": f"simulated: {question}", "steps": ["places", "finish"]}

    def threat(self, steps, on_step):
        raise RuntimeError("threat agent exploded")

    def defence(self, threat_branch, steps, on_step):
        return {"result": {"defence_branch": "9"}, "steps": [], "model": "fake-model"}

    def redblue(self, threat_steps, defence_steps, on_step):
        on_step("threat", Step("go", "scout_targets", {}, {"top": 1}))
        on_step("defence", Step("fix", "test_defence", {"label": "b"}, {"loss_pct": 2.0}))
        return {"headline": "1 countermeasure reduces the projected loss from 30% to 2%"}


def _client(hub: FakeHub, backend) -> TestClient:
    app = create_app(backend)  # the real app: its error handlers map ApiError/ValueError to 4xx
    register_agent_routes(app, hub=hub)
    return TestClient(app)


@pytest.fixture
def hub(tmp_path) -> FakeHub:
    return FakeHub(tmp_path)


@pytest.fixture
def client(hub, backend):
    with _client(hub, backend) as c:
        yield c


def events(client, url: str, last_event_id: str | None = None) -> list[tuple[int, str, dict]]:
    """Read an SSE stream to its end: (id, event, data) triples."""
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    out, current = [], {}
    with client.stream("GET", url, headers=headers) as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith(("id:", "event:", "data:")):
                key, _, value = line.partition(": ")
                current[key.rstrip(":")] = value
            elif not line and "data" in current:
                out.append((int(current["id"]), current["event"], json.loads(current["data"])))
                current = {}
    return out


def kinds(stream) -> list[str]:
    return [k for _, k, _ in stream]


# ---------------------------------------------------------------------- the wargame


def test_match_defaults_to_six_round_strategic_exercise():
    from api.agent_routes import MatchRequest

    request = MatchRequest()
    assert request.rounds == 6 and request.strategic and request.seed == 7


def test_match_runs_in_the_background_and_streams_every_turn(client, hub):
    resp = client.post("/match", json={"base_branch": "50", "rounds": 2, "strategic": False})
    assert resp.status_code == 202
    match_id = resp.json()["match_id"]

    stream = events(client, f"/match/{match_id}/events")
    assert kinds(stream) == ["job_started", "match_started",
                             "move_started", "move", "move_started", "move", "round_done",
                             "move_started", "move", "move_started", "move", "round_done",
                             "match_done", "done"]
    moves = [d for _, k, d in stream if k == "move"]
    assert [m["side"] for m in moves] == ["red", "blue", "red", "blue"]
    assert moves[0]["parent_id"] == "50" and moves[0]["loss_pct"] == 10.0
    assert {"llm_ms", "db_ms", "latency_ms", "rationale", "targets"} <= moves[0].keys()
    done = next(d for _, k, d in stream if k == "match_done")
    assert done["status"] == "done" and done["summary"]["final_loss_pct"] == moves[-1]["loss_pct"]
    assert [i for i, _, _ in stream] == list(range(len(stream)))

    snap = client.get(f"/match/{match_id}").json()
    assert snap["status"] == "done" and snap["head"] == moves[-1]["branch_id"] and len(snap["moves"]) == 4
    assert client.get("/matches").json()["matches"][0]["id"] == match_id


def test_inject_mid_match_lands_before_the_next_round(tmp_path, backend):
    hub = FakeHub(tmp_path, llm=GatedLLM())
    with _client(hub, backend) as client:
        match_id = client.post("/match", json={"base_branch": "50", "rounds": 2, "strategic": False}).json()["match_id"]
        assert hub.fake_llm.first_call.wait(5)  # red is thinking in round 1
        resp = client.post(f"/match/{match_id}/inject", json={"text": "the Liverpool port is closed"})
        assert resp.status_code == 202 and resp.json()["queued"] == 1
        hub.fake_llm.gate.set()
        stream = events(client, f"/match/{match_id}/events")

    order = [(k, d.get("side") or d.get("move", {}).get("side")) for _, k, d in stream if k in ("move", "inject")]
    assert order == [("move", "red"), ("move", "blue"), ("inject", "inject"), ("move", "red"), ("move", "blue")]
    assert next(d for _, k, d in stream if k == "inject")["text"] == "the Liverpool port is closed"
    assert kinds(stream).index("inject") > kinds(stream).index("round_done")


def test_pause_resume_and_stop(tmp_path, backend):
    hub = FakeHub(tmp_path, llm=GatedLLM())
    with _client(hub, backend) as client:
        match_id = client.post("/match", json={"base_branch": "main", "rounds": 3, "strategic": False}).json()["match_id"]
        assert hub.fake_llm.first_call.wait(5)
        assert client.post(f"/match/{match_id}/pause").status_code == 200
        assert client.post(f"/match/{match_id}/resume").status_code == 200
        assert client.post(f"/match/{match_id}/stop").status_code == 200
        hub.fake_llm.gate.set()
        stream = events(client, f"/match/{match_id}/events")
        assert client.post(f"/match/{match_id}/stop").status_code == 409  # already finished

    assert [d["state"] for _, k, d in stream if k == "status"] == ["paused", "running"]
    assert next(d for _, k, d in stream if k == "match_done")["status"] == "stopped"
    assert sum(k == "move" for k in kinds(stream)) == 1  # the move in flight completes, then it stops


def test_llm_unavailable_reports_and_offers_replay(tmp_path, backend):
    hub = FakeHub(tmp_path, llm_error="FEATHERLESS_API_KEY is not set")
    with _client(hub, backend) as client:
        assert client.get("/agent/status").json()["available"] is False
        match_id = client.post("/match", json={}).json()["match_id"]
        stream = events(client, f"/match/{match_id}/events")
    err = next(d for _, k, d in stream if k == "error")
    assert "FEATHERLESS_API_KEY" in err["message"] and err["replay_available"] is True
    assert kinds(stream)[-1] == "done" and stream[-1][2]["status"] == "error"


def test_replay_streams_a_saved_match_without_an_llm(client, hub):
    Match(hub.fake_board, "50", 1, llm=FakeLLM(), injector=fake_injector(hub.fake_board),
          directory=hub.matches_dir, save_as="demo").run()
    hub.llm_error = "no key"  # replay must not need the model

    assert [m["file"] for m in client.get("/matches").json()["matches"]] == ["demo"]
    match_id = client.post("/match/replay", json={"file": "demo", "speed": 20}).json()["match_id"]
    stream = events(client, f"/match/{match_id}/events")
    assert kinds(stream)[1:-1] == ["match_started", "move_started", "move", "move_started", "move",
                                   "round_done", "match_done"]
    assert all(d.get("replay") for _, k, d in stream[1:-1])
    assert client.post(f"/match/{match_id}/inject", json={"text": "nope"}).status_code == 409


def test_replay_input_is_validated(client):
    assert client.post("/match/replay", json={"file": "../../etc/passwd"}).status_code == 422
    assert client.post("/match/replay", json={"file": "missing"}).status_code == 404
    assert client.post("/match", json={"base_branch": "main@abcd1234"}).status_code == 422
    assert client.post("/match", json={"base_branch": "drop table"}).status_code == 422
    assert client.post("/match", json={"rounds": 0}).status_code == 422
    assert client.get("/match/nope/events").status_code == 404


def test_last_event_id_resumes_without_duplicates(client):
    match_id = client.post("/match", json={"rounds": 1, "strategic": False}).json()["match_id"]
    full = events(client, f"/match/{match_id}/events")
    assert events(client, f"/match/{match_id}/events", last_event_id="3") == full[4:]


# ---------------------------------------------------------------------- the one-shot agents are jobs too


def test_scenario_agent_is_a_job_with_live_steps(client):
    resp = client.post("/agent/scenario", json={"question": "everything in Manchester is destroyed"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    stream = events(client, f"/agent/jobs/{job_id}/events")
    assert kinds(stream) == ["job_started", "step", "result", "done"]
    step = stream[1][2]
    assert step["agent"] == "scenario" and step["action"] == "places" and "Manchester" in step["observation"]
    assert stream[2][2]["branch"] == "77"
    assert client.get(f"/agent/jobs/{job_id}").json()["status"] == "done"


def test_redblue_job_streams_both_agents(client):
    job_id = client.post("/agent/redblue", json={}).json()["job_id"]
    stream = events(client, f"/agent/jobs/{job_id}/events")
    assert [d["agent"] for _, k, d in stream if k == "step"] == ["threat", "defence"]
    assert "countermeasure" in next(d for _, k, d in stream if k == "result")["headline"]


def test_failing_agent_job_reports_an_error_event(client):
    job_id = client.post("/agent/threat", json={}).json()["job_id"]
    stream = events(client, f"/agent/jobs/{job_id}/events")
    assert kinds(stream) == ["job_started", "error", "done"]
    assert "exploded" in stream[1][2]["message"]


def test_defence_validates_the_branch_id(client):
    assert client.post("/agent/defence", json={"threat_branch": "1; DROP"}).status_code == 422
    assert client.post("/agent/defence", json={"threat_branch": "9"}).status_code == 202


def test_mock_backend_does_not_mount_agent_routes(backend):
    with TestClient(create_app(backend)) as c:
        assert c.post("/match", json={}).status_code in (404, 405)


def test_download_match_script_and_full_replay(client, hub):
    match = Match(hub.board(), "main", 1, llm=hub.llm(), directory=hub.matches_dir, save_as="share")
    assert match.run()["status"] == "done"
    script = client.get("/matches/share/download")
    assert script.status_code == 200
    assert 'filename="wargame-share.md"' in script.headers["content-disposition"]
    assert "Round 1 · RED" in script.text and "Round 1 · BLUE" in script.text
    assert "hit the top supplier" in script.text
    assert '"strike_supplier"' in script.text and "Loss:" in script.text
    recording = client.get("/matches/share/download?format=json")
    assert recording.status_code == 200
    assert recording.json() == match.to_file()
    assert recording.headers["content-type"].startswith("application/json")
    assert client.get("/matches/missing/download").status_code == 404
    assert client.get("/matches/share/download?format=exe").status_code == 422
    assert client.get("/matches/bad%22name/download").status_code == 422


def test_download_stopped_match_includes_injects_base_and_breakdown(client, hub):
    from agents.match import load_match

    match = Match(hub.board(), "50", 1, llm=hub.llm(), directory=hub.matches_dir, save_as="partial")
    match.run()
    data = load_match("partial", hub.matches_dir)
    data["status"] = "stopped"
    move = data["moves"][0]
    move["side"] = "inject"
    move["breakdown"] = {"deep_pct": 12.5, "legacy_pct": 4.0}
    data["events"].append({"type": "error", "data": {"message": "Test interruption"}})
    (hub.matches_dir / "partial.json").write_text(json.dumps(data))
    script = client.get("/matches/partial/download").text
    assert "Status: stopped" in script and "## Base scenario" in script
    assert "INJECT" in script and "Deep network: 12.5%; parts layer: 4.0%" in script
    assert "Test interruption" in script
