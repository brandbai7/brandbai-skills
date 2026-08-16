from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from package_delivery import package_directory


class PackageDeliveryTests(unittest.TestCase):
    def test_default_zip_name_preserves_dots_in_delivery_folder(self) -> None:
        root = Path(__file__).resolve().parent / ".xhs_package_test_runtime"
        source = root / "小红书_v0.4.2_验收"
        if root.exists():
            shutil.rmtree(root)
        source.mkdir(parents=True)
        (source / "说明.md").write_text("synthetic", encoding="utf-8")
        try:
            result = package_directory(source)
            self.assertEqual(Path(result["zip"]).name, "小红书_v0.4.2_验收.zip")
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
