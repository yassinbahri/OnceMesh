"""Deterministic pypdf layout-v1 text extraction adapter."""

from __future__ import annotations

from io import BytesIO
import re

import pypdf

from ..canonical import canonical_json, digest_bytes
from ..authorization import validate_authorization_partition


def build_pdf_to_text_action(
    pdf: bytes,
    *,
    media_type: str = "application/pdf",
    max_pages: int = 1000,
    max_output_bytes: int = 50_000_000,
    parser_version: str | None = None,
    authorization_partition: str | None = None,
) -> dict:
    if media_type.lower().split(";", 1)[0].strip() != "application/pdf":
        raise ValueError("pdf-to-text/v1 requires application/pdf input")
    for value, label in ((max_pages, "max_pages"), (max_output_bytes, "max_output_bytes")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
    if authorization_partition is not None:
        validate_authorization_partition(authorization_partition)
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "document.pdf-to-text", "version": "1"},
        "inputs": {
            "content": {
                "digest": digest_bytes(pdf),
                "size": len(pdf),
                "media_type": media_type,
            }
        },
        "executor": {
            "name": "oncemesh.pypdf",
            "version": parser_version or pypdf.__version__,
            "config": {
                "profile": "layout-v1",
                "max_pages": max_pages,
                "max_output_bytes": max_output_bytes,
            },
        },
        "output_schema": "oncemesh.document/plain-text-v1",
        "vary": (
            {"authorization_partition": authorization_partition}
            if authorization_partition is not None
            else {}
        ),
    }


def _normalize_page(text: str) -> str:
    lines = [line.rstrip(" \t") for line in re.sub(r"\r\n?", "\n", text).split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def pdf_to_text_artifacts(action: dict, pdf: bytes) -> dict[str, tuple[bytes, str]]:
    if action.get("operation") != {"name": "document.pdf-to-text", "version": "1"}:
        raise ValueError("action is not a document.pdf-to-text/v1 action")
    if action["executor"] != {
        "name": "oncemesh.pypdf",
        "version": pypdf.__version__,
        "config": action["executor"]["config"],
    }:
        raise ValueError("action parser version does not match the installed pypdf executor")
    descriptor = action["inputs"]["content"]
    if descriptor.get("media_type", "").lower().split(";", 1)[0].strip() != "application/pdf":
        raise ValueError("PDF input descriptor must use application/pdf")
    if descriptor["digest"] != digest_bytes(pdf) or descriptor["size"] != len(pdf):
        raise ValueError("PDF bytes do not match the action input descriptor")
    config = action["executor"]["config"]
    if set(config) != {"profile", "max_pages", "max_output_bytes"}:
        raise ValueError("PDF executor config contains unsupported fields")
    if config.get("profile") != "layout-v1":
        raise ValueError("unsupported PDF extraction profile")

    reader = pypdf.PdfReader(BytesIO(pdf), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted PDFs are not supported by pdf-to-text/v1")
    page_count = len(reader.pages)
    if page_count > config["max_pages"]:
        raise ValueError("PDF exceeds max_pages")
    pages = [
        _normalize_page(page.extract_text(extraction_mode="layout") or "")
        for page in reader.pages
    ]
    encoded = ("\n\f\n".join(pages).rstrip("\n") + "\n").encode("utf-8")
    if len(encoded) > config["max_output_bytes"]:
        raise ValueError("extracted text exceeds max_output_bytes")
    metadata = canonical_json(
        {
            "page_count": page_count,
            "parser": "pypdf",
            "parser_version": pypdf.__version__,
            "profile": "layout-v1",
        }
    )
    return {
        "text": (encoded, "text/plain; charset=utf-8"),
        "metadata": (metadata, "application/json"),
    }
