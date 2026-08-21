from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_product_observation_ledger_from_notes.py")
SPEC = importlib.util.spec_from_file_location("observation_compiler", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ObservationCompilerTests(unittest.TestCase):
    def test_parse_note_accepts_single_hash_headings(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            path = Path(temporary) / "SF-002.md"
            path.write_text("# source_file_id\nSF-002\n\n# sequence\n1\n", encoding="utf-8")
            self.assertEqual(MODULE.parse_note(path), {"source_file_id": "SF-002", "sequence": "1"})

    def test_normalise_flags_maps_freeform_model_labels(self) -> None:
        flags = MODULE.normalise_flags(
            "promotional_banner\nbrand_endorser\n营养成分表",
            "会员赠品与代言人，页面含蛋白质营养成分表",
            "high",
        )
        self.assertIn("transaction", flags)
        self.assertIn("audience", flags)
        self.assertIn("nutrition_table", flags)
        self.assertTrue(set(flags).issubset(MODULE.ALLOWED_FLAGS))

    def test_none_density_has_no_flags(self) -> None:
        self.assertEqual(MODULE.normalise_flags("warning", "警示", "none"), [])


if __name__ == "__main__":
    unittest.main()
