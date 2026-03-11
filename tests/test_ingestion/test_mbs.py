import re

from sqlalchemy import select

from gyn_kol.ingestion.mbs import TARGET_ITEMS, _parse_mbs_xml, fetch_mbs_items
from gyn_kol.ingestion.mbs_linkage import _is_gynaecologist, link_mbs_to_clinicians
from gyn_kol.models.clinician import MasterClinician
from gyn_kol.models.clinician_mbs import ClinicianMbs
from gyn_kol.models.mbs_item import MbsItem

# Minimal MBS XML fixture matching the real mbsonline.gov.au schema
MOCK_MBS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<MBS_XML>
  <Data>
    <Item>
      <ItemNum>35723</ItemNum>
      <Description>Para-aortic lymph node dissection (unilateral) for staging of gynaecological malignancy</Description>
      <Category>3 - THERAPEUTIC PROCEDURES</Category>
      <Group>T8 - SURGICAL OPERATIONS</Group>
      <SubGroup>4 - Gynaecological</SubGroup>
      <ScheduleFee>1618.10</ScheduleFee>
      <Benefit75>1213.60</Benefit75>
      <Benefit85>1533.65</Benefit85>
      <ItemStartDate>01121991</ItemStartDate>
      <ItemEndDate></ItemEndDate>
    </Item>
    <Item>
      <ItemNum>35724</ItemNum>
      <Description>Para-aortic lymph node dissection after prior treatment for malignancy</Description>
      <Category>3 - THERAPEUTIC PROCEDURES</Category>
      <Group>T8 - SURGICAL OPERATIONS</Group>
      <SubGroup>4 - Gynaecological</SubGroup>
      <ScheduleFee>2434.35</ScheduleFee>
      <Benefit75>1825.80</Benefit75>
      <Benefit85>2349.90</Benefit85>
      <ItemStartDate>01032022</ItemStartDate>
    </Item>
    <Item>
      <ItemNum>104</ItemNum>
      <Description>Professional attendance at consulting rooms by a specialist</Description>
      <Category>1 - PROFESSIONAL ATTENDANCES</Category>
      <Group>A3 - SPECIALIST ATTENDANCES</Group>
      <ScheduleFee>101.30</ScheduleFee>
      <Benefit75>76.00</Benefit75>
      <Benefit85>86.15</Benefit85>
      <ItemStartDate>01111990</ItemStartDate>
    </Item>
    <Item>
      <ItemNum>99999</ItemNum>
      <Description>Some unrelated item that should not be captured</Description>
      <Category>99 - OTHER</Category>
      <ScheduleFee>50.00</ScheduleFee>
    </Item>
  </Data>
</MBS_XML>
"""


# ------------------------------------------------------------------
# XML parsing tests
# ------------------------------------------------------------------

def test_parse_mbs_xml_extracts_target_items(tmp_path):
    xml_file = tmp_path / "mbs.xml"
    xml_file.write_text(MOCK_MBS_XML)

    items = _parse_mbs_xml(xml_file, {"35723", "35724", "104"})
    assert len(items) == 3

    nums = {i["item_number"] for i in items}
    assert nums == {"35723", "35724", "104"}

    item_35723 = next(i for i in items if i["item_number"] == "35723")
    assert item_35723["schedule_fee"] == 1618.10
    assert item_35723["benefit_75"] == 1213.60
    assert "gynaecological" in item_35723["description"].lower()
    assert item_35723["category"] == "3 - THERAPEUTIC PROCEDURES"


def test_parse_mbs_xml_ignores_non_target_items(tmp_path):
    xml_file = tmp_path / "mbs.xml"
    xml_file.write_text(MOCK_MBS_XML)

    items = _parse_mbs_xml(xml_file, {"35723"})
    assert len(items) == 1
    assert items[0]["item_number"] == "35723"


def test_parse_mbs_xml_empty_file(tmp_path):
    xml_file = tmp_path / "mbs.xml"
    xml_file.write_text("<MBS_XML></MBS_XML>")

    items = _parse_mbs_xml(xml_file, {"35723"})
    assert len(items) == 0


# ------------------------------------------------------------------
# MBS ingestion integration tests
# ------------------------------------------------------------------

async def test_fetch_mbs_items_with_xml(db_session, httpx_mock, tmp_path):
    """Test ingestion via XML download path."""
    # Mock the downloads page with a link to the XML file
    httpx_mock.add_response(
        url=re.compile(r".*mbsonline.*downloads.*"),
        text='<html><body><a href="https://example.com/MBS-XML-20260301.XML">XML</a></body></html>',
    )
    # Mock the XML download
    httpx_mock.add_response(
        url="https://example.com/MBS-XML-20260301.XML",
        text=MOCK_MBS_XML,
    )

    count = await fetch_mbs_items(db_session)
    assert count == 3

    items = (await db_session.execute(select(MbsItem))).scalars().all()
    assert len(items) == 3

    item_104 = next(i for i in items if i.item_number == "104")
    assert item_104.schedule_fee == 101.30
    assert "specialist consultation" in (item_104.gynaecology_relevance or "").lower()


async def test_fetch_mbs_items_deduplication(db_session, httpx_mock):
    """Second run should not create duplicates."""
    httpx_mock.add_response(
        url=re.compile(r".*mbsonline.*downloads.*"),
        text='<html><body><a href="https://example.com/MBS-XML.XML">XML</a></body></html>',
    )
    httpx_mock.add_response(
        url="https://example.com/MBS-XML.XML",
        text=MOCK_MBS_XML,
    )

    await fetch_mbs_items(db_session)

    # Add mocks again for second call
    httpx_mock.add_response(
        url=re.compile(r".*mbsonline.*downloads.*"),
        text='<html><body><a href="https://example.com/MBS-XML.XML">XML</a></body></html>',
    )
    httpx_mock.add_response(
        url="https://example.com/MBS-XML.XML",
        text=MOCK_MBS_XML,
    )

    count = await fetch_mbs_items(db_session)
    assert count == 0

    items = (await db_session.execute(select(MbsItem))).scalars().all()
    assert len(items) == 3


# ------------------------------------------------------------------
# Linkage helper tests
# ------------------------------------------------------------------

def test_is_gynaecologist_positive():
    assert _is_gynaecologist("Obstetrics and Gynaecology")
    assert _is_gynaecologist("Gynaecological Oncology")
    assert _is_gynaecologist("O&G")
    assert _is_gynaecologist("obstetrics")


def test_is_gynaecologist_negative():
    assert not _is_gynaecologist(None)
    assert not _is_gynaecologist("")
    assert not _is_gynaecologist("Ophthalmology")
    assert not _is_gynaecologist("General practice")
    assert not _is_gynaecologist("Cardiology")


# ------------------------------------------------------------------
# Linkage integration tests
# ------------------------------------------------------------------

async def _seed_mbs_items(session) -> dict[str, MbsItem]:
    """Insert test MBS items and return them keyed by item_number."""
    items = {}
    for item_num, relevance in TARGET_ITEMS.items():
        item = MbsItem(
            item_number=item_num,
            description=f"Test description for {item_num}",
            gynaecology_relevance=relevance,
        )
        session.add(item)
        items[item_num] = item
    await session.flush()
    return items


async def _seed_clinician(session, name: str, specialty: str | None) -> MasterClinician:
    """Insert a test clinician."""
    import uuid

    clinician = MasterClinician(
        clinician_id=str(uuid.uuid4()),
        name_display=name,
        name_normalised=name.lower(),
        specialty=specialty,
    )
    session.add(clinician)
    await session.flush()
    return clinician


async def test_link_procedure_items_to_gyn_clinicians(db_session):
    await _seed_mbs_items(db_session)
    gyn = await _seed_clinician(db_session, "Dr Gynaecologist", "Obstetrics and Gynaecology")
    cardio = await _seed_clinician(db_session, "Dr Cardiologist", "Cardiology")
    await db_session.commit()

    result = await link_mbs_to_clinicians(db_session)

    # Only the gynaecologist should be linked (3 items)
    assert result["clinicians_linked"] == 1
    assert result["total_mappings"] == 3  # 35723 + 35724 + 104
    assert result["procedure_links"] == 2  # 35723 + 35724
    assert result["consultation_links"] == 1  # 104

    # Verify the cardiologist has no mappings
    cardio_mappings = (await db_session.execute(
        select(ClinicianMbs).where(ClinicianMbs.clinician_id == cardio.clinician_id)
    )).scalars().all()
    assert len(cardio_mappings) == 0

    # Verify gyn has all 3
    gyn_mappings = (await db_session.execute(
        select(ClinicianMbs).where(ClinicianMbs.clinician_id == gyn.clinician_id)
    )).scalars().all()
    assert len(gyn_mappings) == 3


async def test_linkage_deduplication(db_session):
    await _seed_mbs_items(db_session)
    await _seed_clinician(db_session, "Dr Gynaecologist", "Gynaecological Oncology")
    await db_session.commit()

    result1 = await link_mbs_to_clinicians(db_session)
    assert result1["total_mappings"] == 3

    # Running again should produce no new mappings
    result2 = await link_mbs_to_clinicians(db_session)
    assert result2["total_mappings"] == 0

    # Total in DB should still be 3
    all_mappings = (await db_session.execute(select(ClinicianMbs))).scalars().all()
    assert len(all_mappings) == 3


async def test_link_no_mbs_items(db_session):
    """Linkage with no MBS items in DB returns zeros."""
    result = await link_mbs_to_clinicians(db_session)
    assert result["total_mappings"] == 0
    assert result["clinicians_linked"] == 0
