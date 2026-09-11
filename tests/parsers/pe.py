#!/usr/bin/env python3
"""Tests for the PE file parser."""

import os
import unittest
from unittest import mock

import pefile

from dfvfs.lib import definitions as dfvfs_definitions
from dfvfs.path import factory as path_spec_factory
from dfvfs.resolver import resolver as path_spec_resolver

from plaso.containers import artifacts
from plaso.parsers import pe

from tests.parsers import test_lib


class PECOFFTest(test_lib.ParserTestCase):
    """Tests for the PE file parser."""

    # pylint: disable=protected-access

    def testParseResourceSectionWithoutDirectory(self):
        """A leaf entry produces a warning and later resources are still parsed."""
        parser = pe.PEParser()
        parser_mediator = mock.Mock(extract_winevt_resources=False)
        leaf = pefile.ResourceDirEntryData(id=10, name=None, data=object())
        valid = pefile.ResourceDirEntryData(
            id=11,
            name=None,
            directory=pefile.ResourceDirData(entries=[], TimeDateStamp=1),
        )
        pefile_object = mock.Mock(
            DIRECTORY_ENTRY_RESOURCE=pefile.ResourceDirData(entries=[leaf, valid])
        )

        parser._ParseResourceSection(parser_mediator, pefile_object)

        parser_mediator.ProduceWarning.assert_called_once()
        parser_mediator.ProduceEventData.assert_called_once()
        event_data = parser_mediator.ProduceEventData.call_args.args[0]
        self.assertEqual(event_data.identifier, 11)

    def testParseEventLogResourceWithoutDirectory(self):
        """Missing type/name directories are reported without AttributeError."""
        parser = pe.PEParser()
        leaf = pefile.ResourceDirEntryData(id=1, name=None, data=object())
        resources = (
            leaf,
            pefile.ResourceDirEntryData(
                id=11, name=None, directory=pefile.ResourceDirData(entries=[leaf])
            ),
        )
        for method in (
            parser._ParseMessageTableResource,
            parser._ParseWevtTemplateResource,
        ):
            for resource in resources:
                with self.subTest(method=method.__name__, resource=resource):
                    parser_mediator = mock.Mock()
                    pefile_object = mock.Mock()

                    method(parser_mediator, pefile_object, mock.Mock(), resource)

                    parser_mediator.ProduceWarning.assert_called_once()
                    pefile_object.get_memory_mapped_image.assert_not_called()

    def testParseEmptyEventLogResources(self):
        """Absent and empty resources retain their existing no-op behavior."""
        parser = pe.PEParser()
        resources = (
            None,
            pefile.ResourceDirEntryData(
                id=11, name=None, directory=pefile.ResourceDirData(entries=[])
            ),
        )
        for method in (
            parser._ParseMessageTableResource,
            parser._ParseWevtTemplateResource,
        ):
            for resource in resources:
                with self.subTest(method=method.__name__, resource=resource):
                    parser_mediator = mock.Mock()
                    method(parser_mediator, mock.Mock(), mock.Mock(), resource)
                    parser_mediator.ProduceWarning.assert_not_called()

    def testParseFileObjectOnExecutable(self):
        """Tests the ParseFileObject on a PE executable (EXE) file."""
        parser = pe.PEParser()
        storage_writer = self._ParseFile(["test_pe.exe"], parser)

        number_of_event_data = storage_writer.GetNumberOfAttributeContainers(
            "event_data"
        )
        self.assertEqual(number_of_event_data, 3)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "extraction_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "recovery_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        expected_event_values = {
            "creation_time": "2015-04-21T14:53:56+00:00",
            "data_type": "pe_coff:file",
            "export_table_modification_time": None,
            "imphash": "8d0739063fc8f9955cc6696b462544ab",
            "load_configuration_table_modification_time": None,
            "pe_type": "Executable (EXE)",
        }
        event_data = storage_writer.GetAttributeContainerByIndex("event_data", 0)
        self.CheckEventData(event_data, expected_event_values)

        expected_event_values = {
            "data_type": "pe_coff:dll_import",
            "delayed_import": False,
            "modification_time": "2015-04-21T14:53:55+00:00",
            "name": "KERNEL32.dll",
        }
        event_data = storage_writer.GetAttributeContainerByIndex("event_data", 1)
        self.CheckEventData(event_data, expected_event_values)

        expected_event_values = {
            "data_type": "pe_coff:dll_import",
            "delayed_import": True,
            "modification_time": "2015-04-21T14:53:54+00:00",
            "name": "USER32.dll",
        }
        event_data = storage_writer.GetAttributeContainerByIndex("event_data", 2)
        self.CheckEventData(event_data, expected_event_values)

    def testParseFileObjectOnDriver(self):
        """Tests the ParseFileObject on a PE driver (SYS) file."""
        parser = pe.PEParser()
        storage_writer = self._ParseFile(["test_driver.sys"], parser)

        number_of_event_data = storage_writer.GetNumberOfAttributeContainers(
            "event_data"
        )
        self.assertEqual(number_of_event_data, 1)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "extraction_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "recovery_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        expected_event_values = {
            "data_type": "pe_coff:file",
            "creation_time": "2015-04-21T14:53:54+00:00",
            "export_table_modification_time": None,
            "imphash": "d9c9c4541168665f44917e3ddc4a00d5",
            "load_configuration_table_modification_time": None,
            "pe_type": "Driver (SYS)",
        }
        event_data = storage_writer.GetAttributeContainerByIndex("event_data", 0)
        self.CheckEventData(event_data, expected_event_values)

    def testParseFileObjectOnResourceFile(self):
        """Tests the ParseFileObject on a resource Dynamic Link Library file."""
        test_file_path = self._GetTestFilePath(["wrc-test-wevt_template.dll"])
        self._SkipIfPathNotExists(test_file_path)

        storage_writer = self._CreateStorageWriter()
        parser_mediator = self._CreateParserMediator(storage_writer)
        parser_mediator._extract_winevt_resources = True
        parser_mediator._windows_event_log_providers_per_path = {
            os.path.dirname(test_file_path).lower(): {
                "wrc-test-wevt_template.dll": (
                    artifacts.WindowsEventLogMessageFileArtifact()
                ),
            }
        }
        path_spec = path_spec_factory.Factory.NewPathSpec(
            dfvfs_definitions.TYPE_INDICATOR_OS, location=test_file_path
        )
        file_entry = path_spec_resolver.Resolver.OpenFileEntry(path_spec)
        parser_mediator.SetFileEntry(file_entry)

        parser = pe.PEParser()

        file_object = file_entry.GetFileObject()
        parser.Parse(parser_mediator, file_object)

        number_of_event_data = storage_writer.GetNumberOfAttributeContainers(
            "event_data"
        )
        self.assertEqual(number_of_event_data, 1)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "extraction_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        number_of_warnings = storage_writer.GetNumberOfAttributeContainers(
            "recovery_warning"
        )
        self.assertEqual(number_of_warnings, 0)

        expected_event_values = {
            "creation_time": "2022-01-03T08:55:07+00:00",
            "data_type": "pe_coff:file",
            "export_table_modification_time": None,
            "imphash": "1913ea9cbfeed7fd2a2ef823b6656f85",
            "load_configuration_table_modification_time": None,
            "pe_type": "Dynamic Link Library (DLL)",
        }
        event_data = storage_writer.GetAttributeContainerByIndex("event_data", 0)
        self.CheckEventData(event_data, expected_event_values)

        number_of_artifacts = storage_writer.GetNumberOfAttributeContainers(
            "windows_eventlog_message_table"
        )
        self.assertEqual(number_of_artifacts, 1)

        attribute_containers = list(
            storage_writer.GetAttributeContainers("windows_eventlog_message_table")
        )
        self.assertEqual(attribute_containers[0].language_identifier, 1033)

        number_of_artifacts = storage_writer.GetNumberOfAttributeContainers(
            "windows_eventlog_message_string"
        )
        self.assertEqual(number_of_artifacts, 1)

        attribute_containers = list(
            storage_writer.GetAttributeContainers("windows_eventlog_message_string")
        )
        self.assertEqual(attribute_containers[0].message_identifier, 0xB0010001)
        self.assertEqual(attribute_containers[0].string, "A test value")

        number_of_artifacts = storage_writer.GetNumberOfAttributeContainers(
            "windows_wevt_template_event"
        )
        self.assertEqual(number_of_artifacts, 1)

        attribute_containers = list(
            storage_writer.GetAttributeContainers("windows_wevt_template_event")
        )
        self.assertEqual(attribute_containers[0].identifier, 1)
        self.assertEqual(attribute_containers[0].message_identifier, 0xB0010001)
        self.assertEqual(
            attribute_containers[0].provider_identifier,
            "{67883bbc-d592-4d02-8e29-66907fcb07d6}",
        )
        self.assertEqual(attribute_containers[0].version, 1)


if __name__ == "__main__":
    unittest.main()
