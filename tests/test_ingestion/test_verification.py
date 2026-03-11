from sqlalchemy import select

from gyn_kol.ingestion.verification import verify_canrefer_against_ahpra
from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.models.canrefer_profile import CanreferProfile
from gyn_kol.models.registration_verification import RegistrationVerification
from gyn_kol.resolution.normalise import normalise_name


async def _insert_canrefer(session, name, state="NSW", slug=None):
    slug = slug or name.lower().replace(" ", "-").replace(".", "")
    cp = CanreferProfile(
        name_raw=name,
        name_normalised=normalise_name(name),
        state=state,
        slug=slug,
    )
    session.add(cp)
    await session.flush()
    return cp


async def _insert_ahpra(session, name, reg_number, state="NSW"):
    ar = AhpraRegistration(
        name_raw=name,
        name_normalised=normalise_name(name),
        registration_number=reg_number,
        state=state,
        profession="Medical Practitioner",
        registration_status="Registered",
    )
    session.add(ar)
    await session.flush()
    return ar


async def test_exact_name_match(db_session):
    await _insert_canrefer(db_session, "Dr Jane Smith")
    await _insert_ahpra(db_session, "Dr Jane Smith", "MED0001234567")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    assert result["verified"] == 1
    assert result["unmatched_canrefer"] == 0
    assert result["unmatched_ahpra"] == 0

    verifications = (await db_session.execute(select(RegistrationVerification))).scalars().all()
    verified = [v for v in verifications if v.verification_status == "verified"]
    assert len(verified) == 1
    assert verified[0].match_method == "exact"
    assert verified[0].match_score == 100.0


async def test_fuzzy_name_match(db_session):
    await _insert_canrefer(db_session, "Dr Jane Smith")
    await _insert_ahpra(db_session, "Jane A Smith", "MED0001234567")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    assert result["verified"] == 1
    verifications = (await db_session.execute(select(RegistrationVerification))).scalars().all()
    verified = [v for v in verifications if v.verification_status == "verified"]
    assert len(verified) == 1
    assert verified[0].match_method == "fuzzy"
    assert verified[0].match_score >= 88


async def test_no_match(db_session):
    await _insert_canrefer(db_session, "Dr Jane Smith")
    await _insert_ahpra(db_session, "Prof Robert Jones", "MED0009876543")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    assert result["verified"] == 0
    assert result["unmatched_canrefer"] == 1
    assert result["unmatched_ahpra"] == 1


async def test_state_boost(db_session):
    # Names that are similar but below the 88 threshold,
    # but should match with same-state boost (threshold 82)
    await _insert_canrefer(db_session, "Dr J Smith", state="NSW")
    await _insert_ahpra(db_session, "Jane Smith", "MED0001234567", state="NSW")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    # "j smith" vs "jane smith" — should get boosted by state match
    assert result["verified"] == 1


async def test_unmatched_ahpra_records(db_session):
    await _insert_canrefer(db_session, "Dr Jane Smith")
    await _insert_ahpra(db_session, "Dr Jane Smith", "MED0001234567")
    await _insert_ahpra(db_session, "Dr Robert Jones", "MED0009876543")
    await _insert_ahpra(db_session, "Dr Alice Brown", "MED0005555555")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    assert result["verified"] == 1
    assert result["unmatched_ahpra"] == 2
    assert result["total_canrefer"] == 1
    assert result["total_ahpra"] == 3


async def test_verification_summary_counts(db_session):
    await _insert_canrefer(db_session, "Dr Jane Smith", slug="jane-smith")
    await _insert_canrefer(db_session, "Dr Unknown Person", slug="unknown-person")
    await _insert_ahpra(db_session, "Dr Jane Smith", "MED0001234567")
    await _insert_ahpra(db_session, "Dr Other Doctor", "MED0009999999")
    await db_session.commit()

    result = await verify_canrefer_against_ahpra(db_session)

    assert result["verified"] == 1
    assert result["unmatched_canrefer"] == 1
    assert result["unmatched_ahpra"] == 1
    assert result["total_canrefer"] == 2
    assert result["total_ahpra"] == 2
