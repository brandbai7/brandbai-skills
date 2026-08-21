import json
import tempfile
import unittest
from pathlib import Path

from merge_product_value_ledger_parts import merge_parts


class MergeProductValueLedgerPartsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temporary.name)
        root = self.root
        self.delivery = root / "delivery"
        (self.delivery / "data").mkdir(parents=True)
        self.parts = root / "parts"
        self.parts.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_merge_preserves_part_order_and_writes_jsonl(self):
        (self.parts / "001.jsonl").write_text(
            json.dumps({"fact_id": "F-001", "statement": "事实一"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (self.parts / "002.json").write_text(
            json.dumps([{"fact_id": "DYN-001", "statement": "动态一"}], ensure_ascii=False),
            encoding="utf-8",
        )
        result = merge_parts(self.delivery, "facts", self.parts, expected_count=2)
        self.assertEqual(result["rows"], 2)
        rows = [json.loads(line) for line in (self.delivery / "data" / "fact_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["fact_id"] for row in rows], ["F-001", "DYN-001"])

    def test_duplicate_id_is_rejected(self):
        for index in (1, 2):
            (self.parts / f"{index:03d}.json").write_text(
                json.dumps({"gap_id": "GAP-001"}), encoding="utf-8"
            )
        with self.assertRaisesRegex(ValueError, "重复"):
            merge_parts(self.delivery, "gaps", self.parts)

    def test_parts_must_be_outside_delivery(self):
        inside = self.delivery / "parts"
        inside.mkdir()
        (inside / "001.json").write_text(json.dumps({"value_id": "V-001"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "之外"):
            merge_parts(self.delivery, "values", inside)


if __name__ == "__main__":
    unittest.main()
