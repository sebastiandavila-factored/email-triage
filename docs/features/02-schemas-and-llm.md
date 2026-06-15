# Day 2 — Schemas and LLMService

## What it does

Defines the API data contract (what comes in, what goes out) with Pydantic models and implements the client that talks to Groq. After Day 2 you can instantiate `LLMService`, pass it a `TriageRequest` and receive a validated `TriageResponse`.

There are no endpoints yet — that's Day 3. Today's piece is the **pure logic** that any endpoint will use.

## How it works

```
TriageRequest  ──►  LLMService.triage()  ──►  HTTP POST to Groq  ──►  TriageResponse
   (validated)        (asyncio + httpx)       (/chat/completions)    (validated)
```

`LLMService` builds the prompt, POSTs to Groq requesting `response_format: json_object` (OpenAI-compatible mode), receives a JSON string, and parses it with `TriageResponse.model_validate_json`. If the JSON is malformed, Pydantic raises `ValidationError`. If Groq returns 5xx, httpx raises `HTTPStatusError` (we'll handle it on Day 3 when we build the endpoints).

## Files involved

| File | Role |
|---|---|
| `src/email_triage/schemas.py` | `Category`, `TriageRequest`, `TriageResponse` |
| `src/email_triage/services/llm.py` | `LLMService` with async httpx client |
| `src/email_triage/services/__init__.py` | Marks the directory as a subpackage |
| `scripts/smoke_llm.py` | Manual smoke test against real Groq |

## Schemas, decision by decision

### `Category(StrEnum)`

```python
class Category(StrEnum):
    STATUS = "status"
    REFUNDS = "refunds"
    AVAILABILITY = "availability"
    SHIPMENTS = "shipments"
    PRICES = "prices"
```

Five categories matching the five frequently asked questions from the original proposal: order status, refunds, availability, shipments, prices.

**Why `StrEnum` instead of `Literal["status", "refunds", ...]`:**
- In OpenAPI docs, `StrEnum` renders as a dropdown with values; `Literal` appears as a less readable anonymous schema.
- You can iterate (`list(Category)`) and use `.value`/`.name`, useful for building dynamic prompts.
- Pydantic accepts both `Category.STATUS` and the string `"status"` when constructing — interoperable with the JSON the LLM returns.

### `TriageRequest`

```python
class TriageRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    sender: EmailStr
    body: str = Field(min_length=1, max_length=20_000)
```

- **`EmailStr`**: Pydantic type that validates email format via `email-validator`. That's why we add `pydantic[email]` as a dep. If `sender: "not-an-email"` arrives, FastAPI responds 422 before the handler executes.
- **`min_length=1`**: rejects payloads with empty strings. Without this, an email with `body: ""` gets processed and we spend a Groq request for nothing.
- **`max_length=20_000`**: cap of 20k chars (~5k tokens) in the body. Protects Groq quota against abuse.

### `TriageResponse`

```python
class TriageResponse(BaseModel):
    category: Category
    draft_reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
```

- **`category: Category`** — if Groq returns `"category": "billing"` (invalid category), `model_validate_json` fails. This prevents passing garbage to the caller.
- **`confidence: float = Field(ge=0.0, le=1.0)`** — Pydantic validates the range. If the LLM hallucinated a `confidence: 1.5`, it raises `ValidationError`.

## LLMService — the async client

### Constructor

```python
def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
             base_url: str = GROQ_BASE_URL, timeout: float = 30.0) -> None:
    self._client = httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
```

- **Parameterized `base_url`**: the default is Groq, but by passing `https://api.openai.com/v1` (with adjustments) you can change providers without touching the rest of the code. That's the abstraction we need to migrate to Anthropic when the margin allows.
- **`httpx.AsyncClient` per instance**: today we create one per service. On Day 6 we replace it with a shared client via lifespan handler, reusing the connection pool across requests.
- **`timeout=30.0`**: Groq typically responds <3s, but sometimes it's slow. 30s is generous but not abusive.

### The `triage` method

```python
async def triage(self, req: TriageRequest) -> TriageResponse:
    user_msg = f"Subject: {req.subject}\nFrom: {req.sender}\n\n{req.body}"

    response = await self._client.post(
        "/chat/completions",
        json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        },
    )
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    content: str = data["choices"][0]["message"]["content"]
    return TriageResponse.model_validate_json(content)
```

**`response_format: json_object`**: Groq (like OpenAI) supports this. Guarantees the output is parseable JSON. Without it, the LLM may wrap JSON in triple-backticks (` ```json ... ``` `) and parsing fails.

**`temperature=0.2`**: low, not zero. Zero makes the output almost deterministic but sometimes the model "gets stuck" on repetitive responses. 0.2 gives consistency with a bit of variability so the draft doesn't sound robotic.

**`raise_for_status()`**: if Groq responds 4xx/5xx, raises `httpx.HTTPStatusError`. On Day 3 we catch it in the handler and convert it to `HTTPException(503)`.

**`model_validate_json`**: parses + validates in a single pass. If the JSON has `confidence: 1.5`, it raises `ValidationError` before the caller sees an invalid response.

### `aclose`

```python
async def aclose(self) -> None:
    await self._client.aclose()
```

Closes the connection pool. In the Day 6 lifespan handler we call it at app shutdown.

## The prompt

Kept in `SYSTEM_PROMPT` as a module constant. Decisions:

- **Define each category with a clear phrase.** The LLM doesn't guess from the name alone. `status` by itself is ambiguous; "question about the status of an order" is not.
- **"In the same language as the email".** The customer writes in Spanish or English, the draft comes out in the same language. If the LLM ignores this, we fix it in the prompt (not in the code).
- **Literal schema in the prompt.** Even though we request `response_format: json_object`, showing the exact schema reduces errors of missing fields or incorrect names.
- **No few-shot examples.** Llama 3.3 70B is capable enough. Adding examples would be ~500 more tokens per request. Reconsider if quality drops.
- **The word "JSON" appears several times.** Groq and OpenAI require the prompt to mention "json" if you request `response_format: json_object`, otherwise they return an error.

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| `StrEnum` for categories | `Literal[...]` | Better OpenAPI docs + iterability |
| `EmailStr` with `pydantic[email]` | Simple `str` | Validates format at the system boundary, not in the handler |
| `Field(max_length=20_000)` on body | No limit | Protects Groq quota against abuse |
| `httpx.AsyncClient` async | `requests` sync | Sync blocks the worker for 1-3s per request |
| `response_format: json_object` | Parse free text with regex | Guarantees parseable JSON |
| `temperature=0.2` | 0.0 or 0.7 | Balance between consistency and naturalness of the draft |
| Client per service | Global client from Day 2 | Lifespan handler on Day 6, don't anticipate |
| Llama 3.3 70B as default | Llama 4 / DeepSeek | Wide free tier and sufficient for classification |
| Prompt as module constant | Prompt in separate file | Single mental dependency; relocatable later if it grows |

## Gotchas / Edge cases

- **`response_format: json_object` requires "json" in the prompt.** Groq and OpenAI throw an error if you request JSON mode and the word "json" doesn't appear. Our prompt mentions "JSON" several times — OK.
- **`model_validate_json` is strict.** If the LLM returns `confidence: "0.8"` (string), it fails. Low `temperature` and `response_format` help but don't guarantee 100%. On Day 3 we wrap in `try/except` to return 502 when it happens.
- **`Authorization: Bearer <key>` cached in the client.** If you rotate `GROQ_API_KEY` in `.env`, recreate the service instance. The client doesn't re-read env.
- **No built-in retry.** If Groq returns 429 (rate limit), we don't retry. When we migrate to Pydantic AI (Day 5) retry comes built-in. For now we assume the caller (Zapier) retries.
- **`aclose` isn't called if it crashes first.** The smoke script uses `try/finally` to always close it. In the Day 6 lifespan, FastAPI guarantees orderly shutdown.
- **The smoke script reads `GROQ_API_KEY` from `os.environ`.** It needs `uv run --env-file .env python scripts/smoke_llm.py` to load `.env`.

## Testing

📋 [Testing guide](../testing/02-schemas-and-llm_testing.md)
