import shutil
import unittest
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from package_delivery import PackageError, package_directory


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_package_test_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


class PackageDeliveryTests(unittest.TestCase):
    def test_packages_delivery_with_root_folder_and_sha256(self):
        with workspace_temp() as temp:
            delivery = temp / "BrandBAI_交付"
            (delivery / "data").mkdir(parents=True)
            (delivery / "01_作品清单.xlsx").write_bytes(b"xlsx")
            (delivery / "data" / "works.json").write_text("[]", encoding="utf-8")
            result = package_directory(delivery)
            target = Path(result["zip"])
            self.assertTrue(target.is_file())
            self.assertEqual(len(result["sha256"]), 64)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(sorted(archive.namelist()), [
                    "BrandBAI_交付/01_作品清单.xlsx",
                    "BrandBAI_交付/data/works.json",
                ])

    def test_rejects_zip_inside_delivery(self):
        with workspace_temp() as temp:
            delivery = temp / "delivery"
            delivery.mkdir()
            (delivery / "file.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(PackageError):
                package_directory(delivery, delivery / "inside.zip")


if __name__ == "__main__":
    unittest.main()
