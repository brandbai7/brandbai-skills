from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from package_delivery import PackageError, package_directory


class PackageDeliveryTests(unittest.TestCase):
    def test_packages_delivery_with_root_folder_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            delivery = root / "BrandBAI_微博普通版"
            (delivery / "data").mkdir(parents=True)
            (delivery / "01_账号资料.xlsx").write_bytes(b"synthetic-xlsx")
            (delivery / "data" / "delivery_manifest.json").write_text("{}", encoding="utf-8")
            result = package_directory(delivery)
            target = Path(result["zip"])
            self.assertTrue(target.is_file())
            self.assertEqual(len(result["sha256"]), 64)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(sorted(archive.namelist()), [
                    "BrandBAI_微博普通版/01_账号资料.xlsx",
                    "BrandBAI_微博普通版/data/delivery_manifest.json",
                ])

    def test_rejects_zip_inside_delivery(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            delivery = Path(temp) / "delivery"
            delivery.mkdir()
            (delivery / "file.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(PackageError):
                package_directory(delivery, delivery / "inside.zip")


if __name__ == "__main__":
    unittest.main()
