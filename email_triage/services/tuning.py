"""Triage tuning copilot — orchestrator agent (Plan 44).

Given a triage the owner flagged as wrong, an orchestrator agent (pydantic-ai) diagnoses it
(via Plan 43), proposes a change to the workspace **draft** (a negative counter-example, or a
category description tweak) using the existing Studio services, re-classifies a small **check-set**
against the draft, and iterates until the flagged email classifies correctly with no regressions
(or it hits the request cap). It returns a ``TuningProposal``; **the human publishes** (Plan 26).

Why an orchestrator (not a workflow): the number of refine↔check cycles is unpredictable and the
model decides which tool to call — so this is the agent that produces the real tool-call and
loop-iteration telemetry (Plan 42).

Isolation: every tool binds ``tenant_id`` from the (non-model-controllable) deps; a slug from
another workspace simply doesn't resolve. The copilot only ever edits the draft — there is no
publish tool.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from email_triage.db.repos.categories import CategoryRepo
from email_triage.db.repos.examples import ExampleRepo
from email_triage.observability import AGENT_E2E_LATENCY_MS
from email_triage.schemas import (
    DynamicTriageResponse,
    EvalScore,
    TraceDiagnosis,
    TriageRequest,
    TuningProposal,
)
from email_triage.services.agent_telemetry import instrument_agent_run
from email_triage.services.groq import build_groq_model
from email_triage.services.llm import LLMService
from email_triage.services.prompt_studio import PromptStudioError, PromptStudioService
from email_triage.services.trace_agent import build_diagnosis_service
from email_triage.services.triage_config import TriageConfigError, TriageConfigService

# Caps the agent's model requests so a stubborn loop can't run forever (~4-5 refine cycles).
_REQUEST_LIMIT = 12
_HOLDOUT_LIMIT = 5


class TuningError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Injectable collaborators (tests pass fakes; no Groq, no Logfire) ──────────────────


class DiagnosisProvider(Protocol):
    async def diagnose(self, tenant_id: str, trace_id: str) -> TraceDiagnosis: ...


class DraftClassifier(Protocol):
    async def classify(
        self, prompt: str, allowed_slugs: frozenset[str], req: TriageRequest
    ) -> str: ...


def _empty_changes() -> list[str]:
    return []


def _empty_scores() -> list[EvalScore]:
    return []


@dataclass
class TuningJournal:
    """Authoritative record of what happened, updated by the tools (not the model)."""

    diagnosis: TraceDiagnosis | None = None
    changes: list[str] = field(default_factory=_empty_changes)
    scores: list[EvalScore] = field(default_factory=_empty_scores)
    cycles: int = 0


@dataclass
class TuningDeps:
    """Per-request context handed to the tools. Not model-controllable."""

    factory: async_sessionmaker[AsyncSession]
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    trace_id: str
    diagnosis: DiagnosisProvider
    classifier: DraftClassifier
    target: TriageRequest
    expected_slug: str
    holdout: list[tuple[TriageRequest, str]]
    journal: TuningJournal


# ── Tools (each binds tenant_id from deps; writes go to the DRAFT only) ────────────────


async def diagnose(ctx: RunContext[TuningDeps], focus: str = "root cause") -> dict[str, Any]:
    """Diagnose why the flagged triage went wrong, from its Logfire traces. Call this FIRST.

    Returns the root cause plus a `suggested_fix_kind` and `target_slug` to act on.
    """
    d = ctx.deps
    verdict = await d.diagnosis.diagnose(str(d.tenant_id), d.trace_id)
    d.journal.diagnosis = verdict
    return {
        "root_cause": verdict.root_cause,
        "suggested_fix_kind": verdict.suggested_fix_kind,
        "target_slug": verdict.target_slug,
        "confidence": verdict.confidence,
    }


async def add_counter_example(
    ctx: RunContext[TuningDeps], slug: str, subject: str, body: str
) -> str:
    """Add a NEGATIVE few-shot (a counter-example: 'this email is NOT <slug>') to the draft,
    to stop the model over-picking `slug`."""
    d = ctx.deps
    async with d.factory() as session, session.begin():
        cat = await CategoryRepo().get_by_slug(session, d.tenant_id, slug)
        if cat is None:
            return f"error: no category with slug '{slug}' in this workspace"
        try:
            await PromptStudioService().add_example(
                session, d.tenant_id, cat.id, "negative", subject, body, None, d.user_id
            )
        except PromptStudioError as exc:
            return f"error: {exc.detail}"
    d.journal.changes.append(f"added counter-example to '{slug}'")
    return f"added a counter-example to '{slug}'"


async def tweak_category(ctx: RunContext[TuningDeps], slug: str, description: str) -> str:
    """Rewrite a category's description in the draft to disambiguate it (the slug is immutable)."""
    d = ctx.deps
    async with d.factory() as session, session.begin():
        cat = await CategoryRepo().get_by_slug(session, d.tenant_id, slug)
        if cat is None:
            return f"error: no category with slug '{slug}' in this workspace"
        try:
            await TriageConfigService().update_category(
                session, d.tenant_id, cat.id, description=description
            )
        except TriageConfigError as exc:
            return f"error: {exc.detail}"
    d.journal.changes.append(f"tweaked description of '{slug}'")
    return f"tweaked the description of '{slug}'"


async def preview_prompt(ctx: RunContext[TuningDeps], reason: str = "check") -> str:
    """Return the compiled XML system prompt of the current draft (to see the effect of edits)."""
    d = ctx.deps
    try:
        async with d.factory() as session:
            draft = await PromptStudioService().compile_draft(session, d.tenant_id)
    except PromptStudioError as exc:
        return f"error: {exc.detail}"
    return draft.prompt


async def run_check(ctx: RunContext[TuningDeps], note: str = "") -> dict[str, Any]:
    """Re-classify the check-set (the flagged email + hold-out few-shots) against the current
    draft. Returns whether the target is fixed and how many hold-out cases regressed."""
    d = ctx.deps
    try:
        async with d.factory() as session:
            draft = await PromptStudioService().compile_draft(session, d.tenant_id)
    except PromptStudioError as exc:
        return {"error": exc.detail}

    predicted = await d.classifier.classify(draft.prompt, draft.allowed_slugs, d.target)
    regressions = 0
    for req, slug in d.holdout:
        if await d.classifier.classify(draft.prompt, draft.allowed_slugs, req) != slug:
            regressions += 1

    score = EvalScore(
        target_fixed=predicted == d.expected_slug,
        target_predicted=predicted,
        regressions=regressions,
        checked=1 + len(d.holdout),
    )
    d.journal.scores.append(score)
    d.journal.cycles += 1
    return score.model_dump()


TUNING_SYSTEM_PROMPT = (
    "You are a triage-config copilot. A workspace owner flagged ONE triage as wrong; the correct "
    "category is given to you. Improve the workspace DRAFT so that email classifies correctly, "
    "without breaking others.\n"
    "- FIRST call `diagnose` to learn the root cause and the suggested fix.\n"
    "- Then apply a MINIMAL fix to the draft: `add_counter_example` (a negative example on the "
    "category the model wrongly picked) when it over-picks a category; `tweak_category` when a "
    "description is ambiguous. Use the `target_slug` the diagnosis gives you.\n"
    "- After each edit, call `run_check`. If `target_fixed` is false or `regressions` > 0, refine "
    "and check again. Stop when the target is fixed with zero regressions, or after a few cycles.\n"
    "- You edit the DRAFT only; you NEVER publish. End with a one-paragraph recommendation of what "
    "you changed and whether the human should publish it."
)


def build_tuning_agent(model: Model) -> Agent[TuningDeps, str]:
    toolset = FunctionToolset[TuningDeps](
        [diagnose, add_counter_example, tweak_category, preview_prompt, run_check]
    )
    return Agent(
        model, deps_type=TuningDeps, toolsets=[toolset], system_prompt=TUNING_SYSTEM_PROMPT
    )


async def run_tuning(*, agent: Agent[TuningDeps, str], deps: TuningDeps) -> TuningProposal:
    """Run the orchestrator and assemble the proposal from the journal (authoritative) plus the
    model's final recommendation."""
    instruction = (
        f"The triage for trace {deps.trace_id} was wrong; the correct category is "
        f"'{deps.expected_slug}'. Diagnose it, improve the draft, and re-check until it is fixed "
        f"with no regressions. Never publish."
    )
    t0 = time.perf_counter()
    try:
        result = await instrument_agent_run(
            "tuning",
            agent.run(
                instruction, deps=deps, usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT)
            ),
        )
    except Exception as exc:  # noqa: BLE001 — model/tool/transport failure → graceful 503
        raise TuningError(503, "The tuning copilot could not complete; please retry.") from exc
    AGENT_E2E_LATENCY_MS.record((time.perf_counter() - t0) * 1000, {"agent": "tuning"})

    j = deps.journal
    score_before = j.scores[0] if j.scores else None
    score_after = j.scores[-1] if j.scores else None
    gate_passed = bool(score_after and score_after.target_fixed and score_after.regressions == 0)
    return TuningProposal(
        diagnosis=j.diagnosis,
        changes=list(j.changes),
        score_before=score_before,
        score_after=score_after,
        gate_passed=gate_passed,
        cycles=j.cycles,
        recommendation=result.output,
    )


# ── Check-set loading + production classifier + runner ────────────────────────────────


async def load_holdout(
    session: AsyncSession, tenant_id: uuid.UUID, *, limit: int = _HOLDOUT_LIMIT
) -> list[tuple[TriageRequest, str]]:
    """A small regression guard: up to ``limit`` of the tenant's positive few-shots, each with
    the category it should classify as."""
    out: list[tuple[TriageRequest, str]] = []
    for cat in await CategoryRepo().list_for_tenant(session, tenant_id, active_only=True):
        for ex in await ExampleRepo().list_for_category(session, tenant_id, cat.id):
            if ex.kind == "positive" and ex.subject and ex.body:
                req = TriageRequest(subject=ex.subject, sender="holdout@example.com", body=ex.body)
                out.append((req, cat.slug))
                if len(out) >= limit:
                    return out
    return out


class LLMDraftClassifier:
    """Production ``DraftClassifier``: classifies against a compiled draft prompt via a dynamic
    ``LLMService`` (the same wiring the live triage path uses)."""

    def __init__(self, groq_model: str, groq_api_key: str) -> None:
        self._model = groq_model
        self._key = groq_api_key

    async def classify(self, prompt: str, allowed_slugs: frozenset[str], req: TriageRequest) -> str:
        svc = LLMService(
            api_key=self._key,
            model=self._model,
            system_prompt=prompt,
            output_type=DynamicTriageResponse,
            allowed_slugs=allowed_slugs,
        )
        result = await svc.triage(req)
        return str(result.category)


@dataclass
class TuningRunner:
    """Bundles the config-dependent pieces (agent, diagnosis, classifier). Overridden in tests
    with fakes."""

    agent: Agent[TuningDeps, str]
    diagnosis: DiagnosisProvider
    classifier: DraftClassifier

    async def run(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        trace_id: str,
        email: TriageRequest,
        expected_slug: str,
    ) -> TuningProposal:
        async with factory() as session:
            holdout = await load_holdout(session, tenant_id)
        deps = TuningDeps(
            factory=factory,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            diagnosis=self.diagnosis,
            classifier=self.classifier,
            target=email,
            expected_slug=expected_slug,
            holdout=holdout,
            journal=TuningJournal(),
        )
        return await run_tuning(agent=self.agent, deps=deps)


def build_tuning_runner(
    *, groq_model: str, groq_api_key: str, read_token: str, base_url: str | None = None
) -> TuningRunner:
    return TuningRunner(
        agent=build_tuning_agent(build_groq_model(groq_model, groq_api_key)),
        diagnosis=build_diagnosis_service(
            groq_model=groq_model,
            groq_api_key=groq_api_key,
            read_token=read_token,
            base_url=base_url,
        ),
        classifier=LLMDraftClassifier(groq_model, groq_api_key),
    )
