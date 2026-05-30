from typing import Literal
from fastapi import FastAPI

app = FastAPI(
    title="Email Triage API",
    version="0.1.0",
    description="First-pass triage layer for support email.",
)


@app.get("/health")
def health() -> dict[str, Literal["ok"]]:
    return {"status": "ok"}
