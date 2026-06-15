"""Manual smoke test for LLMService.

Usage:
    uv run --env-file .env python scripts/smoke_llm.py
"""

import asyncio
import os

from email_triage.schemas import TriageRequest
from email_triage.services.llm import LLMService

SAMPLE = TriageRequest(
    subject="When does my order arrive?",
    sender="customer@example.com",
    body=(
        "Hi, I placed order #12345 3 days ago and haven't received any updates. "
        "Can you tell me when it will arrive?"
    ),
)


async def main() -> None:
    api_key = os.environ["GROQ_API_KEY"]
    llm = LLMService(api_key=api_key)
    try:
        result = await llm.triage(SAMPLE)
        print(f"category   : {result.category}")
        print(f"confidence : {result.confidence}")
        print(f"draft_reply:\n{result.draft_reply}")
    finally:
        await llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
