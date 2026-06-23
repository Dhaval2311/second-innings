"""Interactive first-run setup wizard for Second Innings."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


SITES = ["naukri", "linkedin", "hirist", "indeed", "wellfound", "cutshort"]

AI_PROVIDERS = {
    "1": ("gemini_free", "Gemini 1.5 Flash (Free) — https://aistudio.google.com/app/apikey"),
    "2": ("groq",        "Groq Llama 3 (Free)     — https://console.groq.com"),
    "3": ("none",        "No AI — rule-based answers only"),
}


def _ask(prompt: str, default: str = "") -> str:
    if default:
        val = input(f"  {prompt} [{default}]: ").strip()
        return val if val else default
    return input(f"  {prompt}: ").strip()


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"  {prompt} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


def _pick_sites() -> list[str]:
    print("\n  Available sites:")
    for i, s in enumerate(SITES, 1):
        print(f"    {i}. {s}")
    raw = input("  Enter site numbers to enable (e.g. 1,2,3) [all]: ").strip()
    if not raw:
        return SITES[:]
    selected = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(SITES):
                selected.append(SITES[idx])
        except ValueError:
            pass
    return selected if selected else SITES[:]


def run_setup(config_path: Path) -> None:
    """Interactive wizard that writes config.yaml."""
    print("\n" + "=" * 60)
    print("  Second Innings — First-time Setup")
    print("=" * 60)
    print("  This wizard creates your config.yaml.")
    print("  Your data stays local — never uploaded anywhere.\n")

    # --- Profile ---
    print("── Profile ──────────────────────────────────────")
    full_name   = _ask("Your full name")
    email       = _ask("Email address")
    phone       = _ask("Phone number (with country code, e.g. +91-9876543210)")
    location    = _ask("Current city", "Mumbai")
    years_exp   = _ask_int("Years of total experience", 5)
    current_ctc = _ask("Current CTC (LPA)", "0")
    expected_ctc = _ask("Expected CTC (LPA)", "0")
    notice_days = _ask("Notice period (days)", "0")
    resume_path = _ask("Path to your resume PDF (e.g. ~/Downloads/Resume.pdf)")

    # Skills
    print("\n  Common skills: python, sql, spark, pyspark, etl, aws, azure, airflow, kafka, tableau")
    skills_raw  = _ask("Your key skills (comma-separated)", "python,sql,spark")
    skill_list  = [s.strip().lower() for s in skills_raw.split(",") if s.strip()]

    # --- Sites ---
    print("\n── Job Sites ─────────────────────────────────────")
    enabled_sites = _pick_sites()
    fresh_days = _ask_int("Only scrape listings from last N days", 7)

    # --- AI ---
    print("\n── AI Provider (for screening answers & content) ─")
    print("  AI is optional. Without it, rule-based answers are used.")
    for k, (_, label) in AI_PROVIDERS.items():
        print(f"    {k}. {label}")
    ai_choice = input("  Choose [3]: ").strip() or "3"
    ai_provider, _ = AI_PROVIDERS.get(ai_choice, AI_PROVIDERS["3"])
    api_key = ""
    if ai_provider != "none":
        api_key = _ask(f"Paste your {ai_provider} API key")

    # --- Target roles ---
    print("\n── Search Configuration ──────────────────────────")
    roles_raw = _ask(
        "Target job titles (comma-separated)",
        "data engineer, senior data analyst, analytics engineer",
    )

    # Build skill_years dict from skill list
    skill_years = {}
    for sk in skill_list:
        skill_years[sk] = years_exp

    # --- Build config dict ---
    searches: dict = {}
    if "naukri" in enabled_sites:
        searches["naukri"] = [
            {"url": "https://www.naukri.com/data-engineer-sql-python-spark-jobs", "label": "data-engineer"},
            {"url": "https://www.naukri.com/senior-data-analyst-sql-python-jobs",  "label": "senior-data-analyst"},
        ]
    if "linkedin" in enabled_sites:
        searches["linkedin"] = [
            {"url": "https://www.linkedin.com/jobs/search/?keywords=data%20engineer%20python%20spark&location=India&f_TPR=r604800&f_AL=true", "label": "easy-de-spark-india"},
            {"url": "https://www.linkedin.com/jobs/search/?keywords=senior%20data%20analyst%20sql&location=India&f_TPR=r604800&f_AL=true",    "label": "easy-sda-india"},
            {"url": "https://www.linkedin.com/jobs/search/?keywords=analytics%20engineer&location=India&f_TPR=r604800&f_AL=true",               "label": "easy-analytics-india"},
        ]
    if "hirist" in enabled_sites:
        searches["hirist"] = [
            {"url": "https://www.hirist.tech/data-engineering-jobs?minexp=5&maxexp=12", "label": "data-engineering"},
            {"url": "https://www.hirist.tech/data-analyst-jobs?minexp=5&maxexp=12",     "label": "data-analyst"},
        ]
    if "indeed" in enabled_sites:
        searches["indeed"] = [
            {"url": "https://in.indeed.com/jobs?q=data+engineer+python+spark&l=India&fromage=7", "label": "data-engineer"},
        ]

    config: dict = {
        "browser": {
            "cdp_url": "http://localhost:9222",
            "mode": "cdp",
            "reuse_existing_tabs": True,
            "never_open_new_tabs": True,
            "executable_path": "",
            "user_data_dir": "~/.job-automation-browser",
        },
        "profile": {
            "resume_path": resume_path,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "current_ctc_lpa": current_ctc,
            "expected_ctc_lpa": expected_ctc,
            "notice_period_days": notice_days,
            "years_experience": years_exp,
            "current_location": location,
            "willing_to_relocate": "Yes",
            "work_authorization": "Yes",
            "visa_sponsorship_required": "No",
            "comfortable_onsite": "Yes",
            "comfortable_remote": "Yes",
            "earliest_start": "Immediately",
            "english_proficiency": "Yes",
            "default_screening_answer": str(years_exp),
            "skill_years": skill_years,
            "linkedin_url": "",
            "portfolio_url": "",
            "custom_answers": {},
        },
        "ai": {
            "provider": ai_provider,
            "api_key": api_key,
        },
        "scraper": {
            "max_jobs_per_search": 20,
            "enrich_details": True,
            "enrich_limit_per_search": 10,
            "fresh_only_days": fresh_days,
            "searches": searches,
        },
        "scoring": {
            "primary_keywords": [
                "sql", "python", "pyspark", "spark", "etl", "elt",
                "data engineer", "data analyst", "analytics engineer",
                "data warehouse", "data warehousing", "snowflake", "databricks",
                "redshift", "aws", "azure", "gcp", "airflow", "tableau",
                "power bi", "hive", "bigquery", "postgresql",
            ],
            "bonus_keywords": ["flink", "kafka", "java", "kubernetes", "streaming"],
            "priority_threshold": 75,
            "shortlist_threshold": 45,
        },
        "applier": {
            "dry_run": True,
            "delay_seconds": 4,
            "statuses": ["priority", "shortlist", "review"],
            "sources": list(enabled_sites),
            "skip_already_applied": True,
            "max_per_run": 20,
            "pause_on_captcha": True,
            "pause_on_unknown_form": False,
            "prompt_on_unknown": False,
        },
        "output": {
            "dir": "../outputs",
            "tracker_file": "job_tracker.csv",
            "shortlist_file": "job_shortlist.md",
        },
    }

    # Write config.yaml
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    # Ensure .gitignore exists and covers config.yaml
    gitignore_path = config_path.parent / ".gitignore"
    gitignore_entries = ["config.yaml", "second_innings.db", "outputs/", ".venv/", "__pycache__/", "*.pyc", "*.pyo"]
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        for entry in gitignore_entries:
            if entry not in existing:
                gitignore_path.open("a").write(f"\n{entry}")
    else:
        gitignore_path.write_text("\n".join(gitignore_entries) + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"  ✅ Config saved: {config_path}")
    print(f"  ✅ .gitignore updated — config.yaml will NOT be committed")
    print()
    print("  Next steps:")
    print("  1. Launch Brave with remote debugging:")
    print("       ./scripts/launch_brave.sh")
    print("  2. Log into job sites in that Brave window")
    print("  3. Run a scrape:")
    print("       python -m job_automation scrape")
    print("  4. Start the dashboard:")
    print("       python -m job_automation ui")
    print("=" * 60 + "\n")
