"""Tests for native macOS architecture validation without a Mac dependency."""

import contextlib
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from utils import check_macos_native


class MacOSNativeTest(unittest.TestCase):
    """Tests the architecture gate, including universal and incompatible binaries."""

    def testArchitectures(self):
        """Accepts arm64/universal2 and rejects Intel-only/empty architecture lists."""
        for architectures, has_errors in (
            ("arm64\n", False),
            ("x86_64 arm64\n", False),
            ("x86_64\n", True),
            ("", True),
        ):
            with self.subTest(architectures=architectures):
                with (
                    mock.patch.object(check_macos_native.sys, "platform", "darwin"),
                    mock.patch.object(
                        check_macos_native.platform, "machine", return_value="arm64"
                    ),
                    mock.patch.object(
                        check_macos_native,
                        "GetBinaryPaths",
                        return_value=[pathlib.Path("/example/extension.so")],
                    ),
                    mock.patch.object(
                        check_macos_native.subprocess,
                        "run",
                        return_value=subprocess.CompletedProcess(
                            [], 0, stdout=architectures
                        ),
                    ),
                ):
                    report = check_macos_native.AuditEnvironment()
                self.assertEqual(bool(report["errors"]), has_errors)
                self.assertEqual(
                    report["binaries"][0]["architectures"], architectures.split()
                )

    def testUnsupportedRuntime(self):
        """Rejects Rosetta/Intel Python and ARM Linux before invoking lipo."""
        for system, machine in (("darwin", "x86_64"), ("linux", "arm64")):
            with self.subTest(system=system, machine=machine):
                with (
                    mock.patch.object(check_macos_native.sys, "platform", system),
                    mock.patch.object(
                        check_macos_native.platform, "machine", return_value=machine
                    ),
                    mock.patch.object(check_macos_native.subprocess, "run") as run,
                ):
                    self.assertTrue(check_macos_native.AuditEnvironment()["errors"])
                    run.assert_not_called()

    def testInspectionFailure(self):
        """Missing tools, invalid binaries and timeouts must fail the audit."""
        for error in (
            FileNotFoundError("lipo"),
            subprocess.CalledProcessError(1, "lipo"),
            subprocess.TimeoutExpired("lipo", 30),
        ):
            with self.subTest(error=error):
                with (
                    mock.patch.object(check_macos_native.sys, "platform", "darwin"),
                    mock.patch.object(
                        check_macos_native.platform, "machine", return_value="arm64"
                    ),
                    mock.patch.object(
                        check_macos_native,
                        "GetBinaryPaths",
                        return_value=[pathlib.Path("/example/extension.so")],
                    ),
                    mock.patch.object(
                        check_macos_native.subprocess, "run", side_effect=error
                    ),
                ):
                    self.assertTrue(check_macos_native.AuditEnvironment()["errors"])

    def testBinaryDiscovery(self):
        """Finds nested vendored libraries and deduplicates identical roots."""
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            nested = root / "package" / ".dylibs"
            nested.mkdir(parents=True)
            extension = root / "extension.so"
            library = nested / "libexample.dylib"
            extension.touch()
            library.touch()
            (root / "pure_python.py").touch()
            with (
                mock.patch.object(
                    check_macos_native.sysconfig, "get_path", return_value=directory
                ),
                mock.patch.object(
                    check_macos_native.sysconfig,
                    "get_config_var",
                    return_value=directory,
                ),
            ):
                paths = list(check_macos_native.GetBinaryPaths())
            self.assertEqual(len(paths), 3)
            self.assertIn(extension.resolve(), paths)
            self.assertIn(library.resolve(), paths)

    def testExitStatus(self):
        """Keeps JSON output parseable and returns a failing status for errors."""
        for errors, exit_status in (([], 0), (["failure"], 1)):
            output = io.StringIO()
            with (
                mock.patch.object(
                    check_macos_native,
                    "AuditEnvironment",
                    return_value={"errors": errors},
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(check_macos_native.Main(), exit_status)
            self.assertEqual(json.loads(output.getvalue())["errors"], errors)


if __name__ == "__main__":
    unittest.main()
