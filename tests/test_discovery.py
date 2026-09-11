"""Regression tests for discovery with same-named source and test packages."""

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


class TestDiscoveryTest(unittest.TestCase):
    """Exercises the real runner against a dependency-free miniature checkout."""

    def testRunnerWithUtilsPackage(self):
        """Discovers tests.utils separately from utils and preserves failure status."""
        runner_path = pathlib.Path(__file__).resolve().parents[1] / "run_tests.py"
        for success in (True, False):
            with self.subTest(success=success):
                with tempfile.TemporaryDirectory() as directory:
                    root = pathlib.Path(directory)
                    shutil.copyfile(runner_path, root / "run_tests.py")
                    for package in ("utils", "tests", "tests/utils"):
                        package_path = root / package
                        package_path.mkdir(parents=True, exist_ok=True)
                        (package_path / "__init__.py").write_text("", encoding="utf-8")
                    (root / "utils/dependencies.py").write_text(
                        "class DependencyHelper:\n"
                        "    def CheckTestDependencies(self):\n"
                        "        return True\n",
                        encoding="utf-8",
                    )
                    (root / "tests/utils/probe.py").write_text(
                        "import unittest\n"
                        "from utils import dependencies\n"
                        "class DiscoveryProbe(unittest.TestCase):\n"
                        "    def testProbe(self):\n"
                        "        self.assertTrue(\n"
                        "            dependencies.DependencyHelper()"
                        ".CheckTestDependencies())\n"
                        f"        self.assertTrue({success!r})\n",
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [sys.executable, "run_tests.py"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
                self.assertIn("tests.utils.probe.DiscoveryProbe", result.stderr)
                self.assertIn("Ran 1 test", result.stderr)
                self.assertNotIn("incorrectly imported", result.stderr)


if __name__ == "__main__":
    unittest.main()
