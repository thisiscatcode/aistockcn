from __future__ import annotations

import argparse
import logging
import signal
import time

from app.services.research_coverage import (
    claim_next_coverage_job,
    process_coverage_job,
    reconcile_coverage_jobs,
    seed_core_company_coverage,
)


LOGGER = logging.getLogger("aistockcn.research.coverage")
RUNNING = True


def _stop(_signum: int, _frame: object) -> None:
    global RUNNING
    RUNNING = False


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AiStockCN filing coverage worker")
    parser.add_argument("--seed", type=int, default=0, help="Seed this many prioritized companies before working")
    parser.add_argument("--once", action="store_true", help="Seed/reconcile once and exit without consuming jobs")
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if args.seed:
        result = seed_core_company_coverage(limit=args.seed)
        LOGGER.info(
            "coverage seeded target=%s selected=%s queued=%s favorites=%s unsupported_favorites=%s",
            result["target"], result["selected"], result["queued"], result["fei_favorites_selected"],
            result["fei_favorites_without_sec_cik"],
        )
    reconcile_coverage_jobs()
    if args.once:
        return
    LOGGER.info("research coverage worker started")
    last_reconcile = 0.0
    while RUNNING:
        now = time.monotonic()
        if now - last_reconcile >= 10:
            summary = reconcile_coverage_jobs()
            if any(summary.values()):
                LOGGER.info("coverage reconciled %s", summary)
            last_reconcile = now
        job_id = claim_next_coverage_job()
        if job_id:
            result = process_coverage_job(job_id)
            LOGGER.info("coverage sync result=%s", result)
            continue
        time.sleep(2.0)
    LOGGER.info("research coverage worker stopped")


if __name__ == "__main__":
    main()
