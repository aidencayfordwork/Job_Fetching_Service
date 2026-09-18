import pytest

from app.connectors import registry
from app.connectors.base import JobDraft, SourceConnector


class _FakeConnector(SourceConnector):
    name = "fake_source"
    kind = "aggregator_api"

    async def fetch(self, since):
        if False:
            yield {}

    def normalize(self, raw):
        return JobDraft(
            source=self.name,
            source_job_id=raw["id"],
            company_name=raw["company"],
            job_title=raw["title"],
            source_url=raw["url"],
        )


@pytest.fixture(autouse=True)
def _clean_registry():
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()


def test_register_and_get():
    connector = _FakeConnector()
    registry.register(connector)

    assert registry.get("fake_source") is connector
    assert registry.all_connectors() == {"fake_source": connector}


def test_register_duplicate_raises():
    registry.register(_FakeConnector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_FakeConnector())


def test_get_unknown_raises_key_error():
    with pytest.raises(KeyError, match="no connector registered"):
        registry.get("does_not_exist")


def test_normalize_produces_job_draft():
    connector = _FakeConnector()
    draft = connector.normalize(
        {"id": "123", "company": "Acme", "title": "Senior Backend Engineer", "url": "https://example.com/jobs/123"}
    )

    assert isinstance(draft, JobDraft)
    assert draft.source == "fake_source"
    assert draft.source_job_id == "123"
    assert draft.main_stack == []
    assert draft.requires_active_clearance is False
