import logging

from rapidfuzz import fuzz
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.ahpra_registration import AhpraRegistration
from gyn_kol.models.canrefer_profile import CanreferProfile
from gyn_kol.models.registration_verification import RegistrationVerification
from gyn_kol.resolution.normalise import normalise_name

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 88
STATE_BOOSTED_THRESHOLD = 82


def _names_match(name_a: str, name_b: str) -> float:
    """Return the fuzzy match score between two normalised names."""
    return fuzz.token_sort_ratio(name_a, name_b)


def _states_match(state_a: str | None, state_b: str | None) -> bool:
    """Check if two state values match (case-insensitive)."""
    if state_a and state_b:
        return state_a.upper() == state_b.upper()
    return False


async def verify_canrefer_against_ahpra(session: AsyncSession) -> dict[str, int]:
    """Cross-reference Canrefer profiles against AHPRA registrations.

    For each Canrefer profile, searches AHPRA records for name matches.
    Creates RegistrationVerification records for all results.

    Returns:
        Dict with counts: verified, unmatched_canrefer, unmatched_ahpra,
        total_canrefer, total_ahpra.
    """
    # Clear existing verification records for a clean run
    await session.execute(delete(RegistrationVerification))

    # Load all records
    canrefer_profiles = (await session.execute(select(CanreferProfile))).scalars().all()
    ahpra_registrations = (await session.execute(select(AhpraRegistration))).scalars().all()

    logger.info(
        "Verifying %d Canrefer profiles against %d AHPRA registrations",
        len(canrefer_profiles),
        len(ahpra_registrations),
    )

    # Track which AHPRA records have been matched
    matched_ahpra_ids: set[str] = set()
    verified_count = 0
    unmatched_canrefer_count = 0

    for cp in canrefer_profiles:
        cp_name = cp.name_normalised or normalise_name(cp.name_raw)
        best_match: AhpraRegistration | None = None
        best_score = 0.0

        for ar in ahpra_registrations:
            ar_name = ar.name_normalised or normalise_name(ar.name_raw)

            # Exact match — auto-verify
            if cp_name == ar_name:
                best_match = ar
                best_score = 100.0
                break

            score = _names_match(cp_name, ar_name)
            threshold = STATE_BOOSTED_THRESHOLD if _states_match(cp.state, ar.state) else MATCH_THRESHOLD

            if score >= threshold and score > best_score:
                best_match = ar
                best_score = score

        if best_match:
            method = "exact" if best_score == 100.0 else "fuzzy"
            verification = RegistrationVerification(
                canrefer_profile_id=cp.profile_id,
                ahpra_registration_id=best_match.registration_id,
                match_score=best_score,
                match_method=method,
                verification_status="verified",
                verified_by="auto",
            )
            session.add(verification)
            matched_ahpra_ids.add(best_match.registration_id)
            verified_count += 1
            logger.debug(
                "Verified: %s <-> %s (score=%.1f, method=%s)",
                cp.name_raw,
                best_match.name_raw,
                best_score,
                method,
            )
        else:
            verification = RegistrationVerification(
                canrefer_profile_id=cp.profile_id,
                ahpra_registration_id=None,
                match_score=None,
                match_method=None,
                verification_status="unmatched_canrefer",
                notes="No matching AHPRA registration found",
                verified_by="auto",
            )
            session.add(verification)
            unmatched_canrefer_count += 1
            logger.warning("Unmatched Canrefer: %s (%s)", cp.name_raw, cp.state)

    # Create records for AHPRA registrations not matched to any Canrefer profile
    unmatched_ahpra_count = 0
    for ar in ahpra_registrations:
        if ar.registration_id not in matched_ahpra_ids:
            verification = RegistrationVerification(
                canrefer_profile_id=None,
                ahpra_registration_id=ar.registration_id,
                match_score=None,
                match_method=None,
                verification_status="unmatched_ahpra",
                notes="AHPRA registrant not listed on Canrefer",
                verified_by="auto",
            )
            session.add(verification)
            unmatched_ahpra_count += 1

    await session.commit()

    result = {
        "verified": verified_count,
        "unmatched_canrefer": unmatched_canrefer_count,
        "unmatched_ahpra": unmatched_ahpra_count,
        "total_canrefer": len(canrefer_profiles),
        "total_ahpra": len(ahpra_registrations),
    }
    logger.info("Verification complete: %s", result)
    return result
