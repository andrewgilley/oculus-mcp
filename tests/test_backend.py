import json
from pathlib import Path

import pytest

from oculus_mcp.backend import DataError, FileBackend, MAX_FILE_BYTES

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def write_state(tmp_path, data):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(data))
    return FileBackend(path)


def test_nested_tracking_and_provider():
    result = FileBackend(EXAMPLES / "state.json", EXAMPLES / "tracking.json").list_tracked_projects()
    assert result.total == 3
    assert result.projects[0].groups == ["Oculus"]
    assert result.projects[-1].url == "https://codeberg.org/forgejo/forgejo"


def test_tracking_empty_is_authoritative(tmp_path):
    path = tmp_path / "tracking.json"
    path.write_text('{"version": 1, "projects": [], "users": []}')
    assert FileBackend(EXAMPLES / "state.json", path).list_tracked_projects().total == 0


def test_legacy_state_fallback():
    result = FileBackend(EXAMPLES / "state.json").list_tracked_projects()
    assert result.source == "state_file"
    assert result.total == 1


def test_explicit_missing_tracking_does_not_fallback(tmp_path):
    with pytest.raises(DataError, match="Tracking file is missing"):
        FileBackend(EXAMPLES / "state.json", tmp_path / "missing").list_tracked_projects()


def test_pagination():
    backend = FileBackend(EXAMPLES / "state.json", EXAMPLES / "tracking.json")
    first = backend.list_tracked_projects(limit=2)
    assert first.next_offset == 2
    assert len(backend.list_tracked_projects(offset=2, limit=2).projects) == 1
    assert backend.list_tracked_projects(offset=10).projects == []


@pytest.mark.parametrize("offset,limit", [(-1, 20), (0, 0), (0, 51), (True, 20)])
def test_invalid_pagination(offset, limit):
    with pytest.raises(DataError):
        FileBackend(EXAMPLES / "state.json").list_tracked_projects(offset, limit)


@pytest.mark.parametrize("data", [[], {"projects": {}}, {"projects": [{"repository": "../secret"}]},
    {"projects": [{"repository": "owner/repo", "provider": "other"}]},
    {"projects": [{"repository": "owner/repo", "path": "../secret"}]}])
def test_invalid_state(tmp_path, data):
    with pytest.raises(DataError):
        write_state(tmp_path, data).list_tracked_projects()


def test_oversized_input(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(DataError, match="4 MiB"):
        FileBackend(path).list_saved_items()


def test_projection_does_not_return_extra_private_fields(tmp_path):
    data = json.loads((EXAMPLES / "state.json").read_text())
    data["token"] = "secret-sentinel"
    data["saved_items"][0]["event"]["payload"]["private_data"] = "secret-sentinel"
    data["inspect_overviews"][next(iter(data["inspect_overviews"]))]["explanation_telemetry"] = "secret-sentinel"
    backend = write_state(tmp_path, data)
    assert "secret-sentinel" not in backend.list_saved_items().model_dump_json()
    assert "secret-sentinel" not in backend.get_inspection_context(next(iter(data["inspect_overviews"]))).model_dump_json()


def test_saved_metadata():
    item = FileBackend(EXAMPLES / "state.json").list_saved_items().items[0]
    assert item.repository == "andrewgilley/oculus.nvim"
    assert item.title.startswith("Synthetic fixture")


def test_url_scheme_is_filtered(tmp_path):
    data = {"saved_items": [{"key": "x", "event": {"url": "javascript:alert(1)"}}]}
    assert write_state(tmp_path, data).list_saved_items().items[0].url is None


def test_inspection_discovery_and_cache_limitation():
    backend = FileBackend(EXAMPLES / "state.json")
    key = backend.list_inspections().inspections[0].inspection_id
    context = backend.get_inspection_context(key)
    assert context.locations[0].path == "lua/oculus/inspect/overview.lua"
    assert "possibly stale" in context.limitations


def test_inspection_id_cannot_select_a_file():
    with pytest.raises(DataError, match="Inspection not found"):
        FileBackend(EXAMPLES / "state.json").get_inspection_context("../../etc/passwd")


def test_reads_refresh_without_writing(tmp_path):
    backend = write_state(tmp_path, {"projects": []})
    assert backend.list_tracked_projects().total == 0
    raw = '{"projects": [{"repository": "owner/repo"}]}'
    backend.state_file.write_text(raw)
    assert backend.list_tracked_projects().total == 1
    assert backend.state_file.read_text() == raw


def test_empty_lua_inspection_table(tmp_path):
    assert write_state(tmp_path, {"inspect_overviews": []}).list_inspections().total == 0
