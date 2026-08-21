"""Wire-contract coverage for stateless engine API schemas."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_engine.api.schemas import InvokeResponse, RunStatusResponse
from agent_engine.approvals.models import RunStatus


def test_status_fields_use_run_status_without_changing_json_serialization() -> None:
    response = InvokeResponse.model_validate(
        {
            "system_name": "test",
            "answer": "done",
            "visited": [],
            "used_tools": [],
            "run_id": "run-1",
            "status": "completed",
        }
    )

    assert response.status is RunStatus.COMPLETED
    assert response.model_dump(mode="json")["status"] == "completed"

    with pytest.raises(ValidationError):
        RunStatusResponse.model_validate({"run_id": "run-1", "status": "not-a-run-status"})


@pytest.mark.parametrize("schema", [InvokeResponse, RunStatusResponse])
def test_status_openapi_shape_remains_an_unrestricted_string(schema: type[BaseModel]) -> None:
    properties = schema.model_json_schema()["properties"]

    assert properties["status"] == {
        **({"default": "completed"} if schema is InvokeResponse else {}),
        "title": "Status",
        "type": "string",
    }
