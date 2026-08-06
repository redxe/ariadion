from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "research" / "adaptive-physical-realization.md"


class AdaptivePhysicalRealizationResearchTests(unittest.TestCase):
    def test_record_cites_required_evidence_and_states_the_design_boundary(self) -> None:
        contents = DOCUMENT.read_text(encoding="utf-8")

        self.assertIn("Documentation consulted:** 2026-08-06", contents)
        for reference in (
            "10.1103/PhysRevApplied.22.034066",
            "10.1038/s41567-025-02990-x",
            "arxiv.org/abs/2303.02775",
            "10.1103/nzxg-5lbg",
            "arxiv.org/abs/2602.05154",
            "arxiv.org/abs/2509.18583",
        ):
            with self.subTest(reference=reference):
                self.assertIn(reference, contents)

        self.assertIn("The current gate operation is one semantic instruction form.", contents)
        self.assertIn("Hamiltonian-, unitary-, analog-, or control-level", contents)
        self.assertIn("QASMTrans preprint", contents)
        self.assertIn("EvolutionBlock", contents)
        self.assertIn("optimized control waveform", contents)


if __name__ == "__main__":
    unittest.main()
