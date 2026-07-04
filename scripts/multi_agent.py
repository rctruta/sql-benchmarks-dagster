#!/usr/bin/env python3
"""Multi-agent driver — orchestrator + specialist sub-agents.

Companion to `scripts/autonomous_agent.py` (the monolithic single-agent
loop). Same lab, same tools, same goal shape. Different architecture:
the orchestrator threads specialists (config_builder → poller → analyzer)
each with a scoped tool subset and focused prompt.

Every specialist gets its own JSONL trace. The orchestrator's trace ties
them together via `delegate` events naming each specialist's run_id.

Preserved for A/B: run the same goal through this script AND
autonomous_agent.py to compare (turn count × token cost × outcome
quality × per-stage failure classification).
"""
import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
    load_dotenv()
except ImportError:
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, _REPO_ROOT)

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from sql_benchmarks.agent_orchestrator import Orchestrator

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Multi-agent lab driver")
    parser.add_argument("--model", type=str, default="anthropic/claude-sonnet-5",
                        help="litellm model identifier")
    parser.add_argument("--goal", type=str, required=True,
                        help="Natural-language goal for the orchestrator")
    args = parser.parse_args()

    console.print(Panel(f"[bold cyan]GOAL:[/bold cyan] {args.goal}",
                        title="🤖 Multi-Agent Orchestrator"))
    console.print(f"[dim]Model: {args.model}[/dim]")

    orch = Orchestrator(goal=args.goal, model=args.model)
    console.print(f"[dim]Orchestrator trace: {orch.trace.path}[/dim]\n")

    result = orch.run()

    console.print(f"\n[bold]Outcome:[/bold] {result.outcome}")
    console.print(f"[dim]experiment_id: {result.experiment_id}[/dim]")
    for stage, sub_id in result.sub_run_ids.items():
        console.print(f"[dim]  {stage}: {sub_id}[/dim]")

    if result.outcome == "complete" and result.analysis:
        console.print(Panel(Markdown(result.analysis), title="📊 Analysis",
                            border_style="green"))
    elif result.error:
        console.print(f"\n[bold red]Error:[/bold red] {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
