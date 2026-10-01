"""
Text extraction for MOT corpus ingestion (a local, one-time job).

Shells out to CLI tools present on macOS — pdftotext (poppler), textutil, and
unzip — so no heavy Python parsing dependencies are added to the deployed app.
Each file is best-effort: extraction failures return "" and are skipped by the
runner rather than aborting the ingest.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_PLAIN_EXT = {".txt", ".md", ".csv", ".rmd"}

# File types we attempt to ingest.
SUPPORTED = {
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".html", ".htm",
    ".pptx", ".odp", ".ppt", ".txt", ".md", ".csv", ".rmd",
}


def _run(cmd: list[str], timeout: int = 180) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout or ""
    except Exception as e:  # missing tool, timeout, decode error, …
        logger.warning("extract command failed (%s): %s", cmd[0], e)
        return ""


def extract_text(path: Path) -> str:
    """Return the plain text of a document, or '' if it can't be extracted."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _run(["pdftotext", "-q", str(path), "-"])
    if ext in (".docx", ".doc", ".odt", ".rtf", ".html", ".htm", ".ppt"):
        return _run(["textutil", "-convert", "txt", "-stdout", str(path)])
    if ext == ".pptx":
        xml = _run(["unzip", "-p", str(path), "ppt/slides/slide*.xml"])
        return _TAG_RE.sub(" ", xml)
    if ext == ".odp":
        # OpenDocument presentations keep their text in content.xml, not ppt/slides.
        xml = _run(["unzip", "-p", str(path), "content.xml"])
        return _TAG_RE.sub(" ", xml)
    if ext in _PLAIN_EXT:
        try:
            return path.read_text(errors="ignore")
        except OSError as e:
            logger.warning("read failed for %s: %s", path, e)
            return ""
    return ""
