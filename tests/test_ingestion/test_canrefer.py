import re

from sqlalchemy import select

from gyn_kol.ingestion.canrefer import (
    _extract_slug,
    _parse_listing_page,
    _parse_profile_jsonld,
    fetch_canrefer_profiles,
)
from gyn_kol.models.canrefer_profile import CanreferProfile

MOCK_LISTING_HTML = """
<html>
<body>
<main>
  <h2>NSW</h2>
  <div class="specialist-card">
    <a href="/specialists/jane-smith">Dr Jane Smith</a>
    <span class="location">Randwick</span>
    <span>+61 2 9382 6250</span>
  </div>
  <div class="specialist-card">
    <a href="/specialists/john-doe">Prof John Doe</a>
    <span class="location">Westmead</span>
    <span>+61 2 9635 9655</span>
  </div>
  <h2>VIC</h2>
  <div class="specialist-card">
    <a href="/specialists/alice-jones">Dr Alice Jones</a>
    <span class="location">Parkville</span>
    <span>+61 3 9344 5088</span>
  </div>
</main>
</body>
</html>
"""

MOCK_PROFILE_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "http://schema.org",
  "@type": "WebPage",
  "name": "Dr Jane Smith - Canrefer",
  "mainEntity": {
    "@type": "Person",
    "familyName": "Smith",
    "givenName": "Jane",
    "name": "Dr Jane Smith",
    "gender": "Female",
    "honorificPrefix": "Dr",
    "jobTitle": ["Gynaecological Oncologist"],
    "knowsLanguage": ["English", "Mandarin"],
    "workLocation": [
      {
        "@type": "Hospital",
        "name": "Royal Hospital for Women",
        "address": "Barker Street, Randwick NSW 2031",
        "telephone": "(02) 9382 6250",
        "faxNumber": "(02) 9382 6251"
      }
    ],
    "memberOf": [
      {
        "@type": "MedicalOrganization",
        "name": "RHW Gynaecological Cancer MDT"
      }
    ],
    "worksFor": [
      {
        "@type": "Hospital",
        "name": "Royal Hospital for Women",
        "description": "Public Hospital in Randwick"
      }
    ]
  }
}
</script>
</head>
<body><div class="specialist-info">Dr Jane Smith</div></body>
</html>
"""

MOCK_PROFILE_HTML_NO_JSONLD = """
<html>
<head></head>
<body><div class="specialist-info">Dr Jane Smith</div></body>
</html>
"""


def test_extract_slug():
    assert _extract_slug("https://www.canrefer.org.au/specialists/jane-smith") == "jane-smith"
    assert _extract_slug("/specialists/john-doe") == "john-doe"
    assert _extract_slug("https://www.canrefer.org.au/about") is None
    assert _extract_slug("/specialists/Alice-Jones") == "alice-jones"


def test_parse_listing_page():
    specialists = _parse_listing_page(MOCK_LISTING_HTML)
    assert len(specialists) == 3

    nsw = [s for s in specialists if s["state"] == "NSW"]
    assert len(nsw) == 2

    vic = [s for s in specialists if s["state"] == "VIC"]
    assert len(vic) == 1

    jane = next(s for s in specialists if "jane" in s["slug"])
    assert jane["name"] == "Dr Jane Smith"
    assert jane["slug"] == "jane-smith"
    assert jane["state"] == "NSW"


def test_parse_listing_page_deduplicates():
    html = """
    <html><body><main>
    <h2>NSW</h2>
    <a href="/specialists/jane-smith">Dr Jane Smith</a>
    <a href="/specialists/jane-smith">Dr Jane Smith</a>
    </main></body></html>
    """
    specialists = _parse_listing_page(html)
    assert len(specialists) == 1


def test_parse_profile_jsonld():
    jsonld = _parse_profile_jsonld(MOCK_PROFILE_HTML)
    assert jsonld is not None
    assert jsonld["@type"] == "Person"
    assert jsonld["givenName"] == "Jane"
    assert jsonld["familyName"] == "Smith"
    assert jsonld["gender"] == "Female"
    assert jsonld["jobTitle"] == ["Gynaecological Oncologist"]
    assert "English" in jsonld["knowsLanguage"]
    assert len(jsonld["workLocation"]) == 1
    assert len(jsonld["memberOf"]) == 1
    assert len(jsonld["worksFor"]) == 1


def test_parse_profile_jsonld_no_data():
    jsonld = _parse_profile_jsonld(MOCK_PROFILE_HTML_NO_JSONLD)
    assert jsonld is None


async def test_fetch_canrefer_stores_records(db_session, httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*gynaecological-oncologists.*"),
        text=MOCK_LISTING_HTML,
    )
    # Profile page response for each specialist
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/jane-smith.*"),
        text=MOCK_PROFILE_HTML,
    )
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/john-doe.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/alice-jones.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )

    count = await fetch_canrefer_profiles(session=db_session)
    assert count == 3

    profiles = (await db_session.execute(select(CanreferProfile))).scalars().all()
    assert len(profiles) == 3

    # Check the one with JSON-LD was parsed fully
    jane = next(p for p in profiles if p.slug == "jane-smith")
    assert jane.given_name == "Jane"
    assert jane.family_name == "Smith"
    assert jane.gender == "Female"
    assert jane.job_titles == ["Gynaecological Oncologist"]
    assert jane.raw_payload is not None
    assert jane.name_normalised is not None
    assert jane.state == "NSW"


async def test_fetch_canrefer_state_filter(db_session, httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*gynaecological-oncologists.*"),
        text=MOCK_LISTING_HTML,
    )
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )

    count = await fetch_canrefer_profiles(session=db_session, state="VIC")
    assert count == 1

    profiles = (await db_session.execute(select(CanreferProfile))).scalars().all()
    assert len(profiles) == 1
    assert profiles[0].state == "VIC"


async def test_fetch_canrefer_deduplication(db_session, httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*gynaecological-oncologists.*"),
        text=MOCK_LISTING_HTML,
    )
    # Register one response per specialist profile fetch
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/jane-smith.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/john-doe.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*specialists/alice-jones.*"),
        text=MOCK_PROFILE_HTML_NO_JSONLD,
    )

    await fetch_canrefer_profiles(session=db_session)

    # Second run — same data (only listing page needed, profile fetches skipped by dedup)
    httpx_mock.add_response(
        url=re.compile(r".*canrefer.*gynaecological-oncologists.*"),
        text=MOCK_LISTING_HTML,
    )

    count = await fetch_canrefer_profiles(session=db_session)
    assert count == 0  # No new profiles

    profiles = (await db_session.execute(select(CanreferProfile))).scalars().all()
    assert len(profiles) == 3  # No duplicates
