from __future__ import annotations

from io import BytesIO
import json
import sys
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import action_digest, canonical_json  # noqa: E402
from oncemesh.adapters import build_pdf_to_text_action, pdf_to_text_artifacts  # noqa: E402


def fixture_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in ("OnceMesh PDF fixture - page one", "Page two has deterministic text"):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


class PdfAdapterTests(unittest.TestCase):
    def test_extracts_pages_with_form_feed_separator(self) -> None:
        pdf = fixture_pdf()
        action = build_pdf_to_text_action(pdf)
        first = pdf_to_text_artifacts(action, pdf)
        second = pdf_to_text_artifacts(action, pdf)
        self.assertEqual(first, second)
        text = first["text"][0].decode("utf-8")
        self.assertIn("OnceMesh PDF fixture - page one", text)
        self.assertIn("\n\f\n", text)
        self.assertIn("Page two has deterministic text", text)
        metadata = json.loads(first["metadata"][0])
        self.assertEqual(metadata["page_count"], 2)

    def test_descriptor_mismatch_is_rejected(self) -> None:
        pdf = fixture_pdf()
        action = build_pdf_to_text_action(pdf)
        with self.assertRaisesRegex(ValueError, "do not match"):
            pdf_to_text_artifacts(action, pdf + b"changed")

    def test_page_limit_is_enforced(self) -> None:
        pdf = fixture_pdf()
        action = build_pdf_to_text_action(pdf, max_pages=1)
        with self.assertRaisesRegex(ValueError, "max_pages"):
            pdf_to_text_artifacts(action, pdf)

    def test_parser_version_mismatch_is_rejected(self) -> None:
        pdf = fixture_pdf()
        action = build_pdf_to_text_action(pdf, parser_version="0.0.0")
        with self.assertRaisesRegex(ValueError, "does not match"):
            pdf_to_text_artifacts(action, pdf)

    def test_pdf_action_conformance_vector(self) -> None:
        vectors = json.loads(
            (ROOT / "conformance" / "pdf-actions-v0.json").read_text(encoding="utf-8")
        )
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(canonical_json(vector["action"]).decode(), vector["canonical_json"])
                self.assertEqual(action_digest(vector["action"]), vector["action_digest"])


if __name__ == "__main__":
    unittest.main()
