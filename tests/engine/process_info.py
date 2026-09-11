#!/usr/bin/env python3
"""Tests the process information."""

import os
import types
import unittest
from unittest import mock

import psutil

from plaso.engine import process_info


class ProcessInfoTest(unittest.TestCase):
    """Tests the process information."""

    def testInitialization(self):
        """Tests the __init__ function."""
        pid = os.getpid()
        process_information = process_info.ProcessInfo(pid)
        self.assertIsNotNone(process_information)

        with self.assertRaises(OSError):
            process_info.ProcessInfo(-1)

    def testGetUsedMemory(self):
        """Tests the GetUsedMemory function."""
        pid = os.getpid()
        process_information = process_info.ProcessInfo(pid)

        used_memory = process_information.GetUsedMemory()
        self.assertIsNotNone(used_memory)
        self.assertGreater(used_memory, 0)

    def testGetUsedMemoryPlatformFields(self):
        """Uses RSS when data/shared fields are absent, including on macOS."""
        cases = (
            ({"rss": 4096, "vms": 65536, "pfaults": 3, "pageins": 0}, 4096),
            ({"rss": 4096, "vms": 65536}, 4096),
            ({"rss": 4096, "data": 2048, "shared": 512}, 2560),
            ({"rss": 4096, "data": 0, "shared": 0}, 0),
            ({"rss": 4096, "data": 2048}, 4096),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                process = mock.Mock()
                process.memory_info.return_value = types.SimpleNamespace(**fields)
                with (
                    mock.patch.object(psutil, "pid_exists", return_value=True),
                    mock.patch.object(psutil, "Process", return_value=process),
                ):
                    process_information = process_info.ProcessInfo(os.getpid())
                self.assertEqual(process_information.GetUsedMemory(), expected)

    def testGetUsedMemoryExitedProcess(self):
        """An exited process continues to return an unavailable measurement."""
        process = mock.Mock()
        process.memory_info.side_effect = psutil.NoSuchProcess(os.getpid())
        with (
            mock.patch.object(psutil, "pid_exists", return_value=True),
            mock.patch.object(psutil, "Process", return_value=process),
        ):
            process_information = process_info.ProcessInfo(os.getpid())
        self.assertIsNone(process_information.GetUsedMemory())


if __name__ == "__main__":
    unittest.main()
