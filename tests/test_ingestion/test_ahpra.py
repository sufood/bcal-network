from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from gyn_kol.ingestion.ahpra import _parse_results_page, fetch_ahpra_registrations
from gyn_kol.models.ahpra_registration import AhpraRegistration

# Mock HTML matching the real AHPRA div-based DOM structure
MOCK_RESULTS_HTML = """
<html>
<body>
<div id="SearchResultsPage" class="main" data-page-num="1">
<div class="search-results-table">
<div class="search-results-table-body">
  <div class="search-results-table-row" data-practitioner-row-id="MED0001234567">
    <div class="search-results-table-col-wrap">
      <div class="search-results-table-col"><a href="/practitioners/jane-smith">Dr Jane Smith</a></div>
      <div class="search-results-table-col">Medical Practitioner</div>
      <div class="col-span-wrapper">
        <div class="col-span-row">
          <div class="col division"><div class="info"><div class="text">General</div></div></div>
          <div class="col reg-type"><div class="info"><div class="text"><p>General</p></div></div></div>
        </div>
        <div class="col-span-row">
          <div class="col division"><div class="info"><div class="text">Specialist</div></div></div>
          <div class="col reg-type"><div class="info"><div class="text">
            <p>Specialist</p>
            <span data-mobile-speciality>Specialty: Obstetrics and Gynaecology</span>
          </div></div></div>
        </div>
      </div>
    </div>
  </div>
  <div class="search-results-table-row" data-practitioner-row-id="MED0009876543">
    <div class="search-results-table-col-wrap">
      <div class="search-results-table-col"><a href="/practitioners/john-doe">Prof John Doe</a></div>
      <div class="search-results-table-col">Medical Practitioner</div>
      <div class="col-span-wrapper">
        <div class="col-span-row">
          <div class="col division"><div class="info"><div class="text">General</div></div></div>
          <div class="col reg-type"><div class="info"><div class="text"><p>General</p></div></div></div>
        </div>
        <div class="col-span-row">
          <div class="col division"><div class="info"><div class="text">Specialist</div></div></div>
          <div class="col reg-type"><div class="info"><div class="text">
            <p>Specialist</p>
            <span data-mobile-speciality>Specialty: Gynaecological Oncology</span>
          </div></div></div>
        </div>
      </div>
    </div>
  </div>
  <div class="search-results-table-row" data-practitioner-row-id="MED0005555555">
    <div class="search-results-table-col-wrap">
      <div class="search-results-table-col"><a href="/practitioners/alice-brown">Dr Alice Brown</a></div>
      <div class="search-results-table-col">Medical Practitioner</div>
      <div class="col-span-wrapper">
        <div class="col-span-row">
          <div class="col division"><div class="info"><div class="text">General</div></div></div>
          <div class="col reg-type"><div class="info"><div class="text"><p>General</p></div></div></div>
        </div>
      </div>
    </div>
  </div>
</div>
</div>
</div>
</body>
</html>
"""

MOCK_EMPTY_RESULTS_HTML = """
<html>
<body>
<div class="no-results">No results found</div>
</body>
</html>
"""


def test_parse_results_page():
    results = _parse_results_page(MOCK_RESULTS_HTML)
    assert len(results) == 3

    assert results[0]["name_raw"] == "Dr Jane Smith"
    assert results[0]["registration_number"] == "MED0001234567"
    assert results[0]["registration_type"] == "Specialist"
    assert results[0]["specialty"] == "Obstetrics and Gynaecology"

    assert results[1]["name_raw"] == "Prof John Doe"
    assert results[1]["registration_number"] == "MED0009876543"
    assert results[1]["specialty"] == "Gynaecological Oncology"

    # Alice has only General registration — no specialty
    assert results[2]["name_raw"] == "Dr Alice Brown"
    assert results[2]["registration_number"] == "MED0005555555"
    assert "specialty" not in results[2]


def test_parse_results_page_empty():
    results = _parse_results_page(MOCK_EMPTY_RESULTS_HTML)
    assert len(results) == 0


def test_parse_results_page_table_fallback():
    """Legacy table-based layout still works as fallback."""
    table_html = """
    <html><body>
    <table class="search-results">
    <thead><tr><th>Name</th><th>Profession</th><th>Reg#</th><th>Type</th><th>Specialty</th></tr></thead>
    <tbody>
      <tr>
        <td>Dr Test User</td>
        <td>Medical Practitioner</td>
        <td>MED0001111111</td>
        <td>Specialist</td>
        <td>Ophthalmology</td>
      </tr>
    </tbody>
    </table>
    </body></html>
    """
    results = _parse_results_page(table_html)
    assert len(results) == 1
    assert results[0]["name_raw"] == "Dr Test User"
    assert results[0]["registration_number"] == "MED0001111111"
    assert results[0]["specialty"] == "Ophthalmology"


def test_parse_results_page_card_fallback():
    """Card-based layout with data-mobile-speciality span."""
    card_html = """
    <html><body>
    <div class="search-result">
      <h3 class="practitioner-name">Dr Card User</h3>
      <span class="registration-number">MED0002222222</span>
      <span class="profession">Medical Practitioner</span>
      <span data-mobile-speciality>Specialty: General practice</span>
    </div>
    </body></html>
    """
    results = _parse_results_page(card_html)
    assert len(results) == 1
    assert results[0]["name_raw"] == "Dr Card User"
    assert results[0]["specialty"] == "General practice"


def _make_playwright_mocks(html):
    """Create a full Playwright mock chain returning the given HTML."""
    mock_page = AsyncMock()
    mock_page.content.return_value = html

    mock_locator = AsyncMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_locator.fill = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.is_visible = AsyncMock(return_value=False)
    mock_locator.first = mock_locator
    mock_page.locator = MagicMock(return_value=mock_locator)

    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm


@patch("gyn_kol.ingestion.ahpra.async_playwright")
async def test_fetch_ahpra_stores_records(mock_playwright_fn, db_session):
    mock_playwright_fn.return_value = _make_playwright_mocks(MOCK_RESULTS_HTML)

    count = await fetch_ahpra_registrations(
        session=db_session,
        search_terms=["Gynaecologist"],
        states=["NSW"],
    )

    assert count == 3

    registrations = (await db_session.execute(select(AhpraRegistration))).scalars().all()
    assert len(registrations) == 3

    jane = next(r for r in registrations if "Jane" in r.name_raw)
    assert jane.registration_number == "MED0001234567"
    assert jane.state == "NSW"
    assert jane.search_profession == "Gynaecologist"
    assert jane.name_normalised is not None
    assert jane.specialty == "Obstetrics and Gynaecology"

    john = next(r for r in registrations if "John" in r.name_raw)
    assert john.specialty == "Gynaecological Oncology"

    alice = next(r for r in registrations if "Alice" in r.name_raw)
    assert alice.specialty is None


@patch("gyn_kol.ingestion.ahpra.async_playwright")
async def test_fetch_ahpra_deduplication(mock_playwright_fn, db_session):
    mock_playwright_fn.return_value = _make_playwright_mocks(MOCK_RESULTS_HTML)

    # First run
    await fetch_ahpra_registrations(
        session=db_session,
        search_terms=["Gynaecologist"],
        states=["NSW"],
    )

    # Reset mock for second run
    mock_playwright_fn.return_value = _make_playwright_mocks(MOCK_RESULTS_HTML)

    # Second run — same data
    count = await fetch_ahpra_registrations(
        session=db_session,
        search_terms=["Gynaecologist"],
        states=["NSW"],
    )
    assert count == 0  # No new records

    registrations = (await db_session.execute(select(AhpraRegistration))).scalars().all()
    assert len(registrations) == 3  # No duplicates
