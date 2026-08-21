import json
import shutil
import unittest
import uuid
from pathlib import Path

from merge_value_expression_ledger_parts import merge_parts
from prepare_value_expression_work_packets import prepare


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class ValueExpressionWorkPacketsTest(unittest.TestCase):
    def setUp(self):
        test_parent = Path(__file__).resolve().parent / "_skill_test_artifacts"
        test_parent.mkdir(exist_ok=True)
        self.root = test_parent / f"work-packets-{uuid.uuid4().hex}"
        self.root.mkdir()
        root = self.root
        self.product = root / "product"
        self.delivery = root / "expression"
        self.work = root / "work"
        (self.product / "data").mkdir(parents=True)
        (self.delivery / "data").mkdir(parents=True)
        write_json(self.product / "data" / "product_manifest.json", {"product_value_id": "PV-0123456789ab"})
        write_json(self.delivery / "data" / "expression_manifest.json", {"product_value_id": "PV-0123456789ab"})
        write_jsonl(self.product / "data" / "value_ledger.jsonl", [{
            "value_id": "V-001", "layer": "P0", "supporting_fact_ids": ["F-001"],
            "downstream_readiness": "conditional",
        }])
        write_jsonl(self.product / "data" / "fact_ledger.jsonl", [{"fact_id": "F-001", "statement": "事实"}])
        write_json(self.product / "data" / "p0_decision.json", {"recommended_value_id": "V-001"})
        write_jsonl(self.delivery / "data" / "existing_expression_ledger.jsonl", [{
            "expression_id": "PEX-001", "value_ids": ["V-001"], "fact_ids": ["F-001"],
        }])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_prepare_and_merge_six_path_packets(self):
        result = prepare(self.delivery, self.product, self.work)
        self.assertEqual(result["expected_six_path_rows"], 6)
        packet = json.loads((self.work / "inputs" / "V-001.json").read_text(encoding="utf-8"))
        self.assertEqual(packet["supporting_facts"][0]["fact_id"], "F-001")
        rows = [json.loads(line) for line in (self.work / "six_path" / "V-001.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["route"] for row in rows], ["数字化", "感官化", "差异化", "情境化", "证据化", "人格化"])
        for index, row in enumerate(rows):
            row["role"] = "primary" if index == 0 else "supporting" if index == 1 else "not_prioritized"
            row["translation"] = "翻译"
            row["reason"] = "理由"
            row["fact_ids"] = ["F-001"]
            row["expression_ids"] = ["PEX-001"]
            row["boundary"] = "边界"
        write_jsonl(self.work / "six_path" / "V-001.jsonl", rows)
        merged = merge_parts(self.delivery, "six_path", self.work / "six_path", expected_count=6)
        self.assertEqual(merged["rows"], 6)

    def test_mismatched_product_value_is_rejected(self):
        write_json(self.delivery / "data" / "expression_manifest.json", {"product_value_id": "PV-ffffffffffff"})
        with self.assertRaisesRegex(ValueError, "不一致"):
            prepare(self.delivery, self.product, self.work, dry_run=True)


if __name__ == "__main__":
    unittest.main()
