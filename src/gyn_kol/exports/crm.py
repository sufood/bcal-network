import csv
import io
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.clinician import MasterClinician

logger = logging.getLogger(__name__)

# Salesforce / HubSpot field mapping
CRM_FIELD_MAP = {
    "clinician_id": "External_ID__c",
    "name_display": "Full_Name",
    "primary_institution": "Company",
    "state": "State",
    "specialty": "Specialty__c",
    "influence_score": "KOL_Score__c",
    "early_adopter_score": "Early_Adopter_Score__c",
    "tier": "KOL_Tier__c",
}


async def generate_crm_csv(session: AsyncSession) -> io.BytesIO:
    result = await session.execute(
        select(MasterClinician).order_by(MasterClinician.influence_score.desc().nulls_last())
    )
    clinicians = result.scalars().all()

    output = io.BytesIO()
    writer_output = io.StringIO()
    writer = csv.DictWriter(writer_output, fieldnames=list(CRM_FIELD_MAP.values()))
    writer.writeheader()

    for c in clinicians:
        row = {}
        for attr, crm_field in CRM_FIELD_MAP.items():
            val = getattr(c, attr, "")
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val)
            row[crm_field] = val or ""
        writer.writerow(row)

    output.write(writer_output.getvalue().encode("utf-8"))
    output.seek(0)
    return output
