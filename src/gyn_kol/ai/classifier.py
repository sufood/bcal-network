import asyncio
import logging

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gyn_kol.models.review_signal import ReviewSignal

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(10)

CLASSIFICATION_PROMPT = """Classify each review text below. For each review, identify:
1. Procedure type mentioned (if any): e.g., laparoscopy, hysterectomy, robotic surgery, IVF, etc.
2. Technology mentions: any medical devices, instruments, or techniques mentioned
3. Sentiment: positive, neutral, or negative

Return as JSON array with objects having keys: procedure_type, technology_mentions, sentiment

Reviews:
{reviews}"""


async def classify_reviews(
    session: AsyncSession, api_key: str, clinician_id: str
) -> dict | None:
    result = await session.execute(
        select(ReviewSignal).where(ReviewSignal.clinician_id == clinician_id)
    )
    signals = result.scalars().all()

    if not signals:
        return None

    # Collect review texts from raw payloads
    review_texts = []
    for signal in signals:
        if signal.raw_payload and "reviews" in signal.raw_payload:
            for r in signal.raw_payload["reviews"]:
                review_texts.append(r.get("text", ""))

    if not review_texts:
        return None

    client = AsyncAnthropic(api_key=api_key)

    async with _semaphore:
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": CLASSIFICATION_PROMPT.format(
                        reviews="\n---\n".join(review_texts[:20])  # Limit batch size
                    ),
                }],
            )
            return {"raw_classification": response.content[0].text}
        except Exception:
            logger.warning("Review classification failed for %s", clinician_id, exc_info=True)
            return None
