from __future__ import annotations

import logging
import signal
import time

from app.services.research_documents import (
    claim_next_uploaded_document,
    index_research_document_safely,
)
from app.services.research_filing_changes import (
    claim_next_filing_change_run,
    run_filing_change_detection_safely,
)


LOGGER = logging.getLogger("aistockcn.research.worker")
RUNNING = True


def _stop(_signum: int, _frame: object) -> None:
    global RUNNING
    RUNNING = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    LOGGER.info("research document worker started")
    while RUNNING:
        document_id = claim_next_uploaded_document()
        if document_id:
            LOGGER.info("indexing document id=%s", document_id)
            index_research_document_safely(document_id)
            continue
        change_run_id = claim_next_filing_change_run()
        if change_run_id:
            LOGGER.info("running filing change detection id=%s", change_run_id)
            run_filing_change_detection_safely(change_run_id)
            continue
        time.sleep(2.0)
    LOGGER.info("research document worker stopped")


if __name__ == "__main__":
    main()
