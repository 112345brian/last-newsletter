from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from semantic_support import DifflibIndex, SimilarIndex

from last_newsletter_adapter_semantic import HashedNgramIndex

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture(params=["semantic", "difflib"])
def make_index(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[], SimilarIndex]:
    if request.param == "difflib":
        return DifflibIndex
    return lambda: HashedNgramIndex(tmp_path / "idx.sqlite")
