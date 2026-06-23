import asyncio
from job_automation.db import get_repo
from job_automation.scoring import score_job
from job_automation.config import load_config
from pathlib import Path

async def main():
    config = load_config(Path("config.yaml"))
    db = get_repo(Path("outputs/second_innings.db"))
    jobs = db.get_jobs(limit=1000)
    
    print(f"Loaded {len(jobs)} jobs. Recalculating scores...")
    updated = 0
    for job in jobs:
        if job.status in ["applied", "failed", "company_site_pending"]:
            continue
        # We temporarily set status to empty so score_job can re-evaluate Priority/Shortlist/Review
        job.status = "" 
        job.next_action = ""
        await score_job(job, config)
        db.upsert_job(job)
        updated += 1
        print(f"[{updated}/{len(jobs)}] Scored {job.company}: {job.score}% -> {job.status}")
        
if __name__ == "__main__":
    asyncio.run(main())
