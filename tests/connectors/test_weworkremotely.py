import respx
from httpx import Response

from app.connectors.weworkremotely import WeWorkRemotelyConnector

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Acme: Senior Full-Stack Engineer</title>
  <region>Anywhere in the World</region>
  <category>Full-Stack Programming</category>
  <description>&lt;p&gt;Great role, pays $130,000 - $160,000 a year.&lt;/p&gt;</description>
  <link>https://weworkremotely.com/remote-jobs/acme-senior-full-stack-engineer</link>
  <guid>https://weworkremotely.com/remote-jobs/acme-senior-full-stack-engineer</guid>
  <pubDate>Wed, 19 Aug 2026 20:37:20 +0000</pubDate>
</item>
</channel></rss>
"""


@respx.mock
async def test_fetch_and_normalize():
    respx.get("https://weworkremotely.com/remote-jobs.rss").mock(
        return_value=Response(200, text=_RSS)
    )

    connector = WeWorkRemotelyConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Full-Stack Engineer"
    assert draft.source_job_id == "acme-senior-full-stack-engineer"
    assert draft.original_location == "Anywhere in the World"
    assert draft.salary_min == 130000
    assert draft.salary_max == 160000
