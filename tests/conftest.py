from datetime import UTC, datetime
import pytest
from gh_stars_organizer.models import Repository

@pytest.fixture
def repo():
    return Repository(id="R_1", name="num-solver", owner="research",
                      full_name="research/num-solver", description="Numerical solver for differential equations",
                      topics=["numerical-analysis", "ode"], primary_language="Python", languages=["Rust"],
                      url="https://github.com/research/num-solver", updated_at=datetime(2026, 1, 1, tzinfo=UTC))
