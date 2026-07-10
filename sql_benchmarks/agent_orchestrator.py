"""Orchestrator + specialist role definitions.

Explicit state machine: `discover_and_build → poll → analyze`. Each
state is a specialist. State transitions are gated by predicates on
the specialist output (e.g., `discover_and_build → poll` only after
config_builder returns a valid `experiment_id`).

Design principle (see scratch/reducing_agent_search_scope.md): each
specialist has a tiny tool inventory (3–5) and a focused prompt. This
IS progressive disclosure applied to the agent's structure, not just
to the tool interface.

Polling is intentionally deterministic Python (no LLM). Rationale:
polling is a fixed-outcome procedure; wasting an LLM on it strips
signal from the measurement — every LLM call would look the same. If
we later want to measure "does model X know when to stop polling",
that's a separate `llm_poller` specialist; not shipped here.
"""
from dataclasses import dataclass
import json
import re
import time
from typing import Optional

import httpx

from .agent_specialist import SpecialistRole, SpecialistResult, run_specialist
from .agent_tools import _get_client
from .agent_trace import AgentTrace


# --- Specialist role definitions --------------------------------------------

_CONFIG_BUILDER_PROMPT = """\
You are the config-builder specialist. You have ONE job: turn the user
goal into a valid submitted experiment.

IMPORTANT: "config-builder" is your ROLE, not a tool. Never call it as
a tool. Only call tools that appear in your tool list.

Workflow:
1. `list_categories` — pick 1–2 categories matching the goal.
2. `list_suites(category=<name>)` — narrow the suite space. DO NOT call
   `list_suites` unfiltered.
3. `list_templates` → `get_template <name>` — adapt an existing valid
   template. Do not write YAML from scratch.
4. `submit_experiment` — submit the adapted YAML. If it 422s, read the
   error, fix the specific field, retry.

When you get back a valid `experiment_id`, produce a final message with
EXACTLY this format (no extra prose):

    HANDOFF: experiment_id=<8-hex>

If the goal CANNOT be satisfied with the engines and suites this lab
actually has (e.g. it names a database that is not in the catalog, or
asks for a workload no suite covers), DO NOT substitute something else
and do not force a submission. Produce instead:

    HANDOFF: impossible reason=<one line naming exactly what is missing>

That is a successful outcome — an honest refusal is worth more than a
silently substituted experiment.

That signals you're done. Do not analyze results — that's a different
specialist. Do not produce a narrative — just the HANDOFF line.
"""


_ANALYZER_PROMPT = """\
You are the analyzer specialist. The experiment has already completed
and you have its `experiment_id`. Your job: read the results and
produce a final analysis.

IMPORTANT: "analyzer" is your ROLE, not a tool. Never call it as a
tool. Only call tools that appear in your tool list.

Workflow:
1. `get_experiment_summary` — ALWAYS start here. Compact digest of the
   run: means, scaling, narrative.
2. Reach for a specific projection only if the question needs it:
     - `get_means_by_partition` — per-partition speeds
     - `get_scaling_factor` — scaling ratios (adjacent + overall)
     - `get_replication_stability` — noise / CV per (partition, engine)
     - `compare_engines`, `compare_engines_by_partition` — rankings
     - `get_experiment_result` — raw fragments (last resort; expensive)
3. When ready, produce a final analysis starting with "FINAL ANSWER:"
   followed by a Markdown report — numbers with units, provenance
   references (fragment_keys from the projections' `provenance` block),
   and any caveats.
"""


CONFIG_BUILDER = SpecialistRole(
    name="config_builder",
    tool_names=[
        # search_published_capsules is deliberately in the SCHEMA but not in
        # the prompt workflow — edge-case 6 measures UNPROMPTED adoption:
        # does the model check the lab's literature before re-running an
        # experiment the corpus already answers? (Findings 5–7: frontier
        # models derive workflow from schema alone; this tests whether that
        # extends to knowledge reuse.)
        "list_categories", "list_suites", "search_published_capsules",
        "list_templates", "get_template", "submit_experiment",
    ],
    system_prompt=_CONFIG_BUILDER_PROMPT,
    max_turns=15,
    parse_output=lambda content, tool_calls: _parse_handoff(content),
    # Mechanical gate: no submission until a template has been fetched.
    # Live-fire (llama3, 2026-07-05): the model invented a config schema
    # from priors and 422'd four times without ever calling get_template,
    # despite the prompt saying "adapt a template". Exhortation doesn't
    # bind; a gate does — same lesson as the pre-push hook (SBD-3).
    tool_preconditions={
        "submit_experiment": (
            "get_template",
            "REFUSED: you must call `get_template` and adapt a working template "
            "before submitting. Hand-written configs are rejected by this workflow "
            "— fetch `quickstart` (DuckDB-only) or another template from "
            "`list_templates` first.",
        ),
    },
)


ANALYZER = SpecialistRole(
    name="analyzer",
    tool_names=[
        "get_experiment_summary", "get_means_by_partition", "get_means_by_benchmark",
        "get_scaling_factor", "get_replication_stability", "compare_engines",
        "compare_engines_by_partition", "get_experiment_result",
    ],
    system_prompt=_ANALYZER_PROMPT,
    max_turns=15,
    parse_output=lambda content, tool_calls: _parse_analyzer_final(content),
)


_LIBRARIAN_PROMPT = """\
You are the reference librarian for this benchmarking lab. Users and
other agents come to you with questions. Your job: answer from the
lab's PUBLISHED knowledge whenever it can, and route to experiment-
building only when it genuinely cannot.

IMPORTANT: "librarian" is your ROLE, not a tool. Only call tools that
appear in your tool list.

Your reference desk:
- `search_published_capsules` (optional category filter) — sealed,
  verified experiment results. Read any hit with
  `get_experiment_summary`, `get_scaling_factor`, etc. — published
  results are read directly, nothing needs to run.
- `list_lab_docs` / `get_lab_doc` — README, FAQ, methodology docs, and
  the generated experiment catalog.

Decide, then close with EXACTLY one of:

1. The question is answerable from published capsules/docs — produce a
   final message starting with "FINAL ANSWER:" containing the answer,
   citing capsule ids and doc names you drew from. Statements like
   "yes, capsules X and Y cover this; here is what they found" are
   exactly your job.
2. The question truly requires a NEW measurement (no published capsule
   covers it) — produce:

       HANDOFF: build reason=<one line: what is missing from the corpus>

3. The question cannot be satisfied by this lab at all (names an
   engine/workload the lab does not have) — produce:

       HANDOFF: impossible reason=<one line naming what is missing>

Never route to build for something the corpus already answers — a
verified published result is strictly better than a re-run.
"""


LIBRARIAN = SpecialistRole(
    name="librarian",
    tool_names=[
        "search_published_capsules", "list_lab_docs", "get_lab_doc",
        "list_categories",
        "get_experiment_summary", "get_means_by_partition",
        "get_means_by_benchmark", "get_scaling_factor",
        "get_replication_stability",
    ],
    system_prompt=_LIBRARIAN_PROMPT,
    max_turns=12,
    parse_output=lambda content, tool_calls: _parse_librarian(content),
)


_HANDOFF_RE = re.compile(r"HANDOFF:\s*experiment_id=([0-9a-f]{8})", re.IGNORECASE)
_REFUSAL_RE = re.compile(r"HANDOFF:\s*impossible\s+reason=(.+)", re.IGNORECASE)


def _parse_handoff(content: str) -> Optional[dict]:
    """config_builder completion signals: `HANDOFF: experiment_id=<8hex>`
    (built) or `HANDOFF: impossible reason=<text>` (structured refusal —
    the state edge-3 showed was missing: without it, honest models thrash
    through mechanical failures to say 'can't')."""
    m = _HANDOFF_RE.search(content or "")
    if m:
        return {"experiment_id": m.group(1)}
    r = _REFUSAL_RE.search(content or "")
    if r:
        return {"impossible": r.group(1).strip()}
    return None


def _parse_analyzer_final(content: str) -> Optional[dict]:
    """Analyzer signals completion with 'FINAL ANSWER:' at the top of a
    substantive message. Returns the analysis text."""
    if not content:
        return None
    if "final answer" in content.lower() and len(content.strip()) > 100:
        return {"analysis": content}
    return None


_BUILD_RE = re.compile(r"HANDOFF:\s*build\s+reason=(.+)", re.IGNORECASE)


def _parse_librarian(content: str) -> Optional[dict]:
    """Librarian closes one of three ways: an answer from the published
    corpus (FINAL ANSWER:), a routing handoff to config_builder
    (HANDOFF: build reason=...), or a structured refusal
    (HANDOFF: impossible reason=...)."""
    if not content:
        return None
    b = _BUILD_RE.search(content)
    if b:
        return {"build": b.group(1).strip()}
    r = _REFUSAL_RE.search(content)
    if r:
        return {"impossible": r.group(1).strip()}
    if "final answer" in content.lower() and len(content.strip()) > 100:
        return {"analysis": content}
    return None


# --- Poller (pure Python, no LLM) -------------------------------------------

def poll_until_terminal(experiment_id: str,
                        max_polls: int = 60,
                        interval_seconds: float = 3.0) -> dict:
    """Poll `/status` until it returns `complete` or `failed`, or until
    `max_polls * interval_seconds` seconds have elapsed. No LLM; this
    is a deterministic procedure and using an LLM here would waste
    tokens on a fixed-outcome task."""
    client = _get_client()
    for i in range(1, max_polls + 1):
        try:
            r = client.get(f"/v1/experiments/{experiment_id}/status", timeout=30)
            body = r.json()
            status = body.get("status", "unknown")
        except Exception as e:
            return {"status": "poll_error", "polls": i, "error": str(e)}
        if status in ("complete", "failed"):
            return {"status": status, "polls": i, "detail": body.get("detail")}
        time.sleep(interval_seconds)
    return {"status": "timeout", "polls": max_polls}


# --- Orchestrator: threads specialists into a state machine ----------------

@dataclass
class OrchestratorResult:
    outcome: str  # "complete" | "answered" | "refused" | "needs_experiment" | "suspended" | "config_builder_failed" | "poll_failed" | "analyzer_failed" | "librarian_failed"
    experiment_id: Optional[str]
    analysis: Optional[str]
    orchestrator_run_id: str
    sub_run_ids: dict  # {stage_name: sub_run_id_or_None}
    error: Optional[str] = None


class Orchestrator:
    """Runs the state machine: config_builder → poll → analyzer, with a
    REFUSED terminal state (config_builder judged the goal unsatisfiable
    with the lab's actual engines/suites — a first-class honest outcome,
    not a failure).

    Each stage's specialist gets its own JSONL trace. The orchestrator's
    own trace records `delegate` events pointing at each specialist's
    `sub_run_id`, so a reader can walk the multi-agent tree by opening
    the orchestrator trace and following the sub_run_ids.

    `poll_budget_seconds` is contract-declarable: edge-4 showed the fixed
    180s default silently kills legitimately slow suites (sort_spill) —
    uniform cross-model 'failure' that was actually a harness defect."""

    def __init__(self, goal: str, model: str, poll_budget_seconds: float = 180.0):
        self.goal = goal
        self.model = model
        self.poll_budget_seconds = poll_budget_seconds
        self.trace = AgentTrace(
            goal=f"[orchestrator] {goal}", model=model,
            agents_md_loaded=False, max_turns=0,
        )

    def ask(self) -> OrchestratorResult:
        """Reference-desk mode: librarian ONLY — answer from published
        capsules + docs, never execute. The user-delegation use case:
        'are there published capsules for X?', 'what does the FAQ say
        about Y?'. A build-worthy question comes back as outcome
        'needs_experiment' with the librarian's reason — the caller
        decides whether to spend on a run."""
        sub_ids: dict = {}
        lib = run_specialist(LIBRARIAN, brief=self.goal, model=self.model)
        sub_ids["librarian"] = lib.sub_run_id
        self.trace.delegate(
            stage="librarian", sub_run_id=lib.sub_run_id,
            input_summary=self.goal[:200], outcome=lib.outcome,
            output_summary=(str(lib.output)[:200] if lib.output else None),
        )
        if lib.outcome == "ok" and lib.output and "analysis" in lib.output:
            self.trace.run_end("answered", turns_used=0)
            return OrchestratorResult(
                outcome="answered", experiment_id=None,
                analysis=lib.output["analysis"],
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if lib.outcome == "ok" and lib.output and "impossible" in lib.output:
            self.trace.run_end("refused", turns_used=0)
            return OrchestratorResult(
                outcome="refused", experiment_id=None,
                analysis=f"REFUSED: {lib.output['impossible']}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if lib.outcome == "ok" and lib.output and "build" in lib.output:
            self.trace.run_end("needs_experiment", turns_used=0)
            return OrchestratorResult(
                outcome="needs_experiment", experiment_id=None,
                analysis=f"NEEDS EXPERIMENT: {lib.output['build']}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        self.trace.run_end("librarian_failed", turns_used=0, error=lib.error)
        return OrchestratorResult(
            outcome="librarian_failed", experiment_id=None, analysis=None,
            orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            error=lib.error or "librarian produced no parseable close",
        )

    def run(self) -> OrchestratorResult:
        sub_ids: dict = {}

        # Stage 0: reference librarian — check the lab's own literature
        # BEFORE building anything. This is the structural fix for
        # Finding 21 (0/5 unprompted library adoption: schema-only
        # exposure doesn't bind; a workflow stage does). Three exits:
        # answered-from-corpus (terminal, cheap), impossible (terminal,
        # honest), build (continue to config_builder).
        lib = run_specialist(LIBRARIAN, brief=self.goal, model=self.model)
        sub_ids["librarian"] = lib.sub_run_id
        self.trace.delegate(
            stage="librarian", sub_run_id=lib.sub_run_id,
            input_summary=self.goal[:200], outcome=lib.outcome,
            output_summary=(str(lib.output)[:200] if lib.output else None),
        )
        if lib.outcome == "ok" and lib.output and "analysis" in lib.output:
            self.trace.run_end("answered", turns_used=0)
            return OrchestratorResult(
                outcome="answered", experiment_id=None,
                analysis=lib.output["analysis"],
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if lib.outcome == "ok" and lib.output and "impossible" in lib.output:
            self.trace.run_end("refused", turns_used=0)
            return OrchestratorResult(
                outcome="refused", experiment_id=None,
                analysis=f"REFUSED: {lib.output['impossible']}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        # 'build' handoff or librarian failure -> proceed to build either
        # way (a broken reference desk must not block measurement).

        # Stage 1: config_builder
        cb: SpecialistResult = run_specialist(CONFIG_BUILDER, brief=self.goal, model=self.model)
        sub_ids["config_builder"] = cb.sub_run_id
        self.trace.delegate(
            stage="config_builder", sub_run_id=cb.sub_run_id,
            input_summary=self.goal[:200], outcome=cb.outcome,
            output_summary=(json.dumps(cb.output) if cb.output else None),
        )
        if cb.outcome == "ok" and cb.output and "impossible" in cb.output:
            # Structured refusal — terminal, honest, cheap. Not a failure.
            reason = cb.output["impossible"]
            self.trace.run_end("refused", turns_used=0, error=None)
            return OrchestratorResult(
                outcome="refused", experiment_id=None,
                analysis=f"REFUSED: {reason}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if cb.outcome != "ok" or not cb.output or "experiment_id" not in cb.output:
            self.trace.run_end("config_builder_failed", turns_used=0, error=cb.error)
            return OrchestratorResult(
                outcome="config_builder_failed", experiment_id=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=cb.error or "config_builder produced no experiment_id",
            )
        exp_id = cb.output["experiment_id"]

        # Stage 2: pure-Python poller (budget contract-declarable)
        interval = 3.0
        poll_result = poll_until_terminal(
            exp_id,
            max_polls=max(1, int(self.poll_budget_seconds / interval)),
            interval_seconds=interval,
        )
        self.trace.delegate(
            stage="poll", sub_run_id=None,
            input_summary=f"experiment_id={exp_id}",
            outcome=poll_result["status"],
            output_summary=json.dumps(poll_result),
        )
        if poll_result["status"] == "timeout":
            # SUSPENDED, not failed: the experiment is still executing
            # server-side and will finish regardless of who's watching.
            # No poll budget is "right" for open-ended workloads (edge-4:
            # a legitimate 16GB out-of-memory sort outlived a 30-minute
            # budget). The run is resumable: `Orchestrator.resume(exp_id)`
            # picks up at the analyzer for a few thousand tokens once the
            # capsule completes.
            self.trace.run_end("suspended", turns_used=0, error=None)
            return OrchestratorResult(
                outcome="suspended", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=None,
            )
        if poll_result["status"] != "complete":
            self.trace.run_end("poll_failed", turns_used=0, error=str(poll_result))
            return OrchestratorResult(
                outcome="poll_failed", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=f"poll returned {poll_result['status']}: {poll_result.get('detail') or poll_result.get('error')}",
            )

        return self._analyzer_stage(exp_id, sub_ids)

    def resume(self, exp_id: str) -> OrchestratorResult:
        """Pick up a SUSPENDED run: skip config_builder (the experiment
        already exists), check/poll the capsule, then run the analyzer.
        Cheap — the analyzer is a few thousand tokens; polling is free.

        Callable any time after suspension: minutes later, next session,
        or after a crash — the capsule is the durable hand-off point."""
        sub_ids: dict = {"config_builder": None}  # skipped on resume
        interval = 3.0
        poll_result = poll_until_terminal(
            exp_id,
            max_polls=max(1, int(self.poll_budget_seconds / interval)),
            interval_seconds=interval,
        )
        self.trace.delegate(
            stage="poll", sub_run_id=None,
            input_summary=f"experiment_id={exp_id} (resume)",
            outcome=poll_result["status"],
            output_summary=json.dumps(poll_result),
        )
        if poll_result["status"] == "timeout":
            self.trace.run_end("suspended", turns_used=0, error=None)
            return OrchestratorResult(
                outcome="suspended", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if poll_result["status"] != "complete":
            self.trace.run_end("poll_failed", turns_used=0, error=str(poll_result))
            return OrchestratorResult(
                outcome="poll_failed", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=f"poll returned {poll_result['status']}: {poll_result.get('detail') or poll_result.get('error')}",
            )
        return self._analyzer_stage(exp_id, sub_ids)

    def _analyzer_stage(self, exp_id: str, sub_ids: dict) -> OrchestratorResult:
        # Fetch the config's `definitions` block server-side (no LLM tokens)
        # so the analyzer knows what the partition labels MEAN (row counts).
        # Run-4 lesson: without this the analyzer had to assume "large is
        # probably 2x medium" and hedged its scaling claims accordingly.
        definitions_note = ""
        try:
            client = _get_client()
            r = client.get(f"/v1/results/{exp_id}", timeout=30)
            config = (r.json() or {}).get("config") or {}
            definitions = config.get("definitions")
            if definitions:
                definitions_note = (
                    f"\n\nDataset scale definitions from the sealed config "
                    f"(partition label -> parameter value): {json.dumps(definitions)}"
                )
        except Exception:
            pass  # analyzer still works without it, just hedges more

        analyzer_brief = (
            f"The experiment {exp_id} has completed. Original user goal: {self.goal}"
            f"{definitions_note}\n\n"
            "Produce the analysis."
        )
        an: SpecialistResult = run_specialist(ANALYZER, brief=analyzer_brief, model=self.model)
        sub_ids["analyzer"] = an.sub_run_id
        self.trace.delegate(
            stage="analyzer", sub_run_id=an.sub_run_id,
            input_summary=analyzer_brief[:200], outcome=an.outcome,
            output_summary=(str(an.output)[:200] if an.output else None),
        )
        if an.outcome != "ok" or not an.output:
            self.trace.run_end("analyzer_failed", turns_used=0, error=an.error)
            return OrchestratorResult(
                outcome="analyzer_failed", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=an.error or "analyzer produced no final answer",
            )

        self.trace.run_end("final_answer", turns_used=0)
        return OrchestratorResult(
            outcome="complete", experiment_id=exp_id, analysis=an.output.get("analysis"),
            orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
        )
