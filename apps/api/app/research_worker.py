from __future__ import annotations

import logging
import signal
import time

from app.services.research_documents import (
    claim_next_uploaded_document,
    index_pdf_document_safely,
    init_research_document_schema,
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
    init_research_document_schema()
    LOGGER.info("research document worker started")
    while RUNNING:
        document_id = claim_next_uploaded_document()
        if document_id:
            LOGGER.info("indexing document id=%s", document_id)
            index_pdf_document_safely(document_id)
            continue
        time.sleep(2.0)
    LOGGER.info("research document worker stopped")


if __name__ == "__main__":
    main()
