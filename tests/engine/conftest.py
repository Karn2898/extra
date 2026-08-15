"""Fixtures shared by the engine tests."""

from __future__ import annotations

import pytest

from tests.engine.usage_models import AllToolsThenAnswerModel


@pytest.fixture
def models() -> dict[str, AllToolsThenAnswerModel]:
    """One deterministic model per node of the two-agent supervisor fixture."""
    return {
        "root-model": AllToolsThenAnswerModel("synthesized"),
        "planner-model": AllToolsThenAnswerModel("planned"),
        "developer-model": AllToolsThenAnswerModel("developed"),
    }
