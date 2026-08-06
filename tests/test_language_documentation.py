from __future__ import annotations

import ast
import re
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_LANGUAGE_DOCUMENTS = (
    ROOT / "specs" / "language.md",
    ROOT / "specs" / "syntax.md",
)
_PUBLIC_LANGUAGE_MATERIAL = (
    (ROOT / "README.md",)
    + tuple(sorted((ROOT / "specs").rglob("*.md")))
    + tuple(sorted((ROOT / "docs").rglob("*.md")))
    + tuple(sorted((ROOT / "examples").glob("*.py")))
)
_PYTHON_FENCE = re.compile(r"```python\n(?P<source>.*?)\n```", re.DOTALL)
_LOWERCASE_QUBIT_CONSTRUCTOR = re.compile(r"\bqubit\s*\(")
_LOWERCASE_QUBIT_IMPORT = re.compile(r"from\s+ariadion\s+import[^\n]*\bqubit\b")


class LanguageDocumentationTests(unittest.TestCase):
    def test_target_python_fences_parse(self) -> None:
        for document in _LANGUAGE_DOCUMENTS:
            contents = document.read_text(encoding="utf-8")
            samples = tuple(_PYTHON_FENCE.finditer(contents))
            self.assertTrue(samples, f"{document} must contain target Python examples")
            for sample_index, sample in enumerate(samples, start=1):
                source = textwrap.dedent(sample.group("source"))
                with self.subTest(document=document, sample=sample_index):
                    ast.parse(source, filename=str(document))

    def test_bell_and_quantum_preserving_examples_parse(self) -> None:
        contents = (ROOT / "specs" / "language.md").read_text(encoding="utf-8")
        samples = tuple(
            textwrap.dedent(match.group("source"))
            for match in _PYTHON_FENCE.finditer(contents)
        )
        bell = next((sample for sample in samples if "def bell()" in sample), None)
        prepare_plus = next((sample for sample in samples if "def prepare_plus()" in sample), None)

        self.assertIsNotNone(bell)
        self.assertIsNotNone(prepare_plus)
        ast.parse(bell or "", filename="specs/language.md:bell")
        ast.parse(prepare_plus or "", filename="specs/language.md:prepare_plus")
        self.assertIn("from ariadion import Bit, Qubit, cx, h, quantum, z", bell or "")

    def test_contract_documents_do_not_show_lowercase_qubit_public_api(self) -> None:
        for document in _PUBLIC_LANGUAGE_MATERIAL:
            contents = document.read_text(encoding="utf-8")
            with self.subTest(document=document, check="constructor"):
                self.assertIsNone(
                    _LOWERCASE_QUBIT_CONSTRUCTOR.search(contents),
                    f"{document} contains a lowercase qubit constructor",
                )
            with self.subTest(document=document, check="import"):
                self.assertIsNone(
                    _LOWERCASE_QUBIT_IMPORT.search(contents),
                    f"{document} imports a lowercase qubit factory",
                )


if __name__ == "__main__":
    unittest.main()
