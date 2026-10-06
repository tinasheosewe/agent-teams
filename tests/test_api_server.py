"""Tests for the project file listing endpoint of the API server."""

import pytest

from agentagent.api.server import list_project_files

PROJECT_ID = "0123456789ab"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A working directory holding one project's files and a file outside workspace/."""
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "workspace" / PROJECT_ID
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n")
    (tmp_path / "outside.txt").write_text("not a project file\n")
    return tmp_path


async def test_lists_the_files_of_a_project(workspace):
    assert await list_project_files(PROJECT_ID) == [{"path": "src/main.py", "size": 12}]


async def test_unknown_project_has_no_files(workspace):
    assert await list_project_files("ba9876543210") == []


@pytest.mark.parametrize("project_id", ["..", ".", "", "0123456789AB", "0123456789ab/..", "not-a-project"])
async def test_ids_that_are_not_project_ids_list_nothing(workspace, project_id):
    assert await list_project_files(project_id) == []
