#!/usr/bin/env python3
"""Audit the active Python environment for native macOS arm64 binaries.

This checks architecture, not dependency versions or transitive dylib linkage.
Run check_dependencies.py and the test suite as separate compatibility checks.
"""

import json
import os
import pathlib
import platform
import subprocess
import sys
import sysconfig


def GetBinaryPaths():
    """Yields the interpreter and installed extension/shared-library paths."""
    yield pathlib.Path(sys.executable).resolve()
    roots = {
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
        sysconfig.get_config_var("DESTSHARED"),
    }
    seen = set()

    def RaiseWalkError(error):
        """Do not report a successful audit for unreadable directories."""
        raise error

    for root in sorted(path for path in roots if path):
        for directory, _, filenames in os.walk(root, onerror=RaiseWalkError):
            for filename in sorted(filenames):
                if not filename.endswith((".so", ".dylib")):
                    continue
                path = pathlib.Path(directory, filename).resolve()
                if path not in seen:
                    seen.add(path)
                    yield path


def AuditEnvironment():
    """Returns a JSON-compatible architecture report for the active environment."""
    report = {
        "platform": sys.platform,
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "binaries": [],
        "errors": [],
    }
    if sys.platform != "darwin" or report["machine"] != "arm64":
        report["errors"].append(
            "Run this check with native arm64 Python on macOS. "
            "An Intel/Rosetta Python or an ARM Linux environment is not supported."
        )
        return report

    try:
        for path in GetBinaryPaths():
            entry = {"path": str(path), "architectures": []}
            report["binaries"].append(entry)
            try:
                result = subprocess.run(
                    ["/usr/bin/lipo", "-archs", str(path)],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exception:
                report["errors"].append(f"Cannot inspect {path}: {exception}")
                continue

            entry["architectures"] = result.stdout.split()
            if "arm64" not in entry["architectures"]:
                report["errors"].append(f"Missing arm64 slice: {path}")
    except OSError as exception:
        report["errors"].append(f"Cannot enumerate native libraries: {exception}")

    return report


def Main():
    """Prints the report and returns a nonzero exit status on an audit failure."""
    report = AuditEnvironment()
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(Main())
