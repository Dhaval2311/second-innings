from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .browser import list_open_tabs
from .config import load_config, resolve_db_path, resolve_output_paths, validate_config
from .scraper.orchestrator import run_scraper
from .applier.orchestrator import run_applier
from .scoring import score_job
from .tracker import load_tracker, merge_jobs, save_tracker, write_shortlist

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Second Innings — scrape, score, and auto-apply to jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  setup       First-time configuration wizard
  scrape      Scrape jobs from configured sources (browser)
  apply       Auto-apply to easy-apply jobs; log company-site jobs
  run         scrape then apply in one go
  ui          Start the web dashboard at http://localhost:8080
  status      Show tracker summary from DB
  tabs        List open tabs in the attached browser
  learn       Learn screening answers from the open browser tab
  pending     Show questions needing your answers
        """,
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "config.yaml"),
        help="Path to config.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # setup
    sub.add_parser("setup", help="First-time configuration wizard")

    # scrape
    scrape = sub.add_parser("scrape", help="Scrape jobs from configured sources")
    scrape.add_argument(
        "--sources", nargs="*",
        choices=["naukri", "linkedin", "indeed", "hirist",
                 "wellfound", "cutshort"],
        help="Limit to specific sources",
    )

    # apply
    sub.add_parser("apply", help="Run the two-lane apply pipeline")

    # run
    run_all = sub.add_parser("run", help="Scrape then apply")
    run_all.add_argument(
        "--sources", nargs="*",
        choices=["naukri", "linkedin", "indeed", "hirist",
                 "wellfound", "cutshort"],
    )

    # ui
    ui_cmd = sub.add_parser("ui", help="Start the web dashboard")
    ui_cmd.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")

    # status
    sub.add_parser("status", help="Show pipeline summary")

    # tabs
    sub.add_parser("tabs", help="List open browser tabs")

    # learn
    sub.add_parser("learn", help="Learn screening answers from open browser tab")

    # pending
    sub.add_parser("pending", help="Show pending screening questions")

    # content
    cover = sub.add_parser("cover-letter", help="Generate a cover letter")
    cover.add_argument("--company", required=True)
    cover.add_argument("--role", required=True)

    email = sub.add_parser("cold-email", help="Generate a cold outreach email")
    email.add_argument("--company", required=True)
    email.add_argument("--role", required=True)
    email.add_argument("--to", dest="hiring_manager", default="", help="Hiring manager name")

    dm = sub.add_parser("cold-dm", help="Generate a LinkedIn DM")
    dm.add_argument("--company", required=True)
    dm.add_argument("--role", required=True)
    dm.add_argument("--name", dest="target_name", default="", help="Target person's name")

    return parser


# ── Command handlers ──────────────────────────────────────────────────

async def cmd_scrape(config: dict, base_dir: Path, sources: list[str] | None) -> None:
    console.print("[bold cyan]Starting scrape…[/bold cyan]")
    console.print("Make sure your browser is open with remote debugging on port 9222.")
    new_jobs = await run_scraper(config, base_dir, sources)
    console.print(f"[green]Scrape complete.[/green] {len(new_jobs)} new job(s) added to DB.")


async def cmd_apply(config: dict, base_dir: Path) -> None:
    console.print("[bold cyan]Starting apply pipeline…[/bold cyan]")
    stats = await run_applier(config, base_dir)
    table = Table(title="Apply Results")
    table.add_column("Metric"); table.add_column("Count")
    for k, v in stats.items():
        table.add_row(k, str(v))
    console.print(table)


async def cmd_run(config: dict, base_dir: Path, sources: list[str] | None) -> None:
    await cmd_scrape(config, base_dir, sources)
    await cmd_apply(config, base_dir)


async def cmd_tabs(config: dict) -> None:
    cdp = config.get("browser", {}).get("cdp_url", "http://localhost:9222")
    try:
        tabs = await list_open_tabs(cdp)
    except ConnectionError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    if not tabs:
        console.print("No open tabs found.")
        return
    table = Table(title=f"Open Tabs ({len(tabs)})")
    table.add_column("#"); table.add_column("URL")
    for i, url in enumerate(tabs, 1):
        table.add_row(str(i), url)
    console.print(table)


async def cmd_learn(config: dict, base_dir: Path) -> None:
    from .browser import BrowserSession
    from .screening_learn import learn_from_open_tab
    from .db import get_repo

    db = get_repo(resolve_db_path(config, base_dir))
    session = BrowserSession(config)
    async with session:
        page = await session.get_work_page(
            prefer_hosts=["hirist.tech", "linkedin.com", "naukri.com", "indeed."]
        )
        from .screening_learn import extract_screening_qa
        qa = await extract_screening_qa(page)
        if not qa:
            console.print("[yellow]No filled answers found. Fill the form in browser first.[/yellow]")
            return
        count = 0
        for q, a in qa.items():
            existing = db.get_answer(q)
            if not existing:
                db.save_answer(q, str(a), source="learned")
                count += 1
    console.print(f"[green]Learned {count} answer(s) → saved to DB[/green]")


def cmd_pending(base_dir: Path, config: dict) -> None:
    from .db import get_repo
    db = get_repo(resolve_db_path(config, base_dir))
    pending = db.get_pending_inputs()
    if not pending:
        console.print("No pending questions — run the dashboard to answer them.")
        return
    table = Table(title=f"Pending Questions ({len(pending)})")
    table.add_column("Company"); table.add_column("Question")
    for e in pending[:30]:
        table.add_row(e.get("company", ""), e.get("question", "")[:70])
    console.print(table)
    console.print("\n[dim]Answer these in the dashboard (python -m second_innings ui)[/dim]")


def cmd_status(config: dict, base_dir: Path) -> None:
    from .db import get_repo
    db = get_repo(resolve_db_path(config, base_dir))
    stats = db.get_pipeline_stats()
    breakdown = db.get_source_breakdown()

    table = Table(title="Pipeline Summary")
    table.add_column("Metric"); table.add_column("Count")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)

    if breakdown:
        src_table = Table(title="By Source")
        src_table.add_column("Source"); src_table.add_column("Total")
        src_table.add_column("Easy"); src_table.add_column("Company")
        src_table.add_column("Applied")
        for r in breakdown:
            src_table.add_row(r["source"], str(r["total"]),
                              str(r["easy_apply"]), str(r["company_site"]),
                              str(r["applied"]))
        console.print(src_table)


async def cmd_content(
    content_type: str,
    config: dict,
    company: str,
    role: str,
    extra: str = "",
) -> None:
    from .content.ai_client import AIClient
    from .models import Job

    ai = AIClient(config)
    profile = config.get("profile", {})

    if content_type == "cover-letter":
        from .content.cover_letter import generate_cover_letter
        job = Job(source="", company=company, role=role, source_url="")
        text = await generate_cover_letter(job, profile, ai)
        console.print(text)

    elif content_type == "cold-email":
        from .content.cold_email import generate_cold_email
        result = await generate_cold_email(company, role, profile, ai, hiring_manager=extra)
        console.print(f"[bold]Subject:[/bold] {result['subject']}\n")
        console.print(result["body"])

    elif content_type == "cold-dm":
        from .content.linkedin_dm import generate_linkedin_dm
        text = await generate_linkedin_dm(company, role, profile, ai, target_name=extra)
        console.print(text)
        console.print(f"\n[dim]({len(text)} chars)[/dim]")


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # setup doesn't need an existing config
    if args.command == "setup":
        from .setup_wizard import run_setup
        config_path = Path(args.config).resolve()
        run_setup(config_path)
        return

    # All other commands need a config
    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    base_dir = Path(args.config).resolve().parent

    # Validate config and show warnings
    warnings = validate_config(config)
    for w in warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")

    if args.command == "scrape":
        asyncio.run(cmd_scrape(config, base_dir, args.sources))
    elif args.command == "apply":
        asyncio.run(cmd_apply(config, base_dir))
    elif args.command == "run":
        asyncio.run(cmd_run(config, base_dir, args.sources))
    elif args.command == "ui":
        from .ui import run_ui_server
        run_ui_server(config, base_dir, port=args.port)
    elif args.command == "status":
        cmd_status(config, base_dir)
    elif args.command == "tabs":
        asyncio.run(cmd_tabs(config))
    elif args.command == "learn":
        asyncio.run(cmd_learn(config, base_dir))
    elif args.command == "pending":
        cmd_pending(base_dir, config)
    elif args.command == "cover-letter":
        asyncio.run(cmd_content("cover-letter", config, args.company, args.role))
    elif args.command == "cold-email":
        asyncio.run(cmd_content("cold-email", config, args.company, args.role,
                                extra=args.hiring_manager))
    elif args.command == "cold-dm":
        asyncio.run(cmd_content("cold-dm", config, args.company, args.role,
                                extra=args.target_name))


if __name__ == "__main__":
    main()