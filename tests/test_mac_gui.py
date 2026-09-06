"""Guard tests for the macOS real-SAP adapter (no GUI / no OCR needed)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

from sapcfg.gui import mac_gui


class MacGuiGuards(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ.pop("SAPCFG_ALLOW_REAL_SAP", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_importable_on_darwin(self):
        self.assertTrue(hasattr(mac_gui, "MacSapGui"))
        self.assertEqual(mac_gui.MacSapGui.name, "sap_gui_mac")

    def test_consent_env_required(self):
        with mock.patch.object(mac_gui, "FLAG_FILE",
                               mac_gui.ROOT / "nonexistent_consent_file"):
            with self.assertRaises(PermissionError):
                mac_gui.MacSapGui()

    def test_env_consent_grants_construction(self):
        os.environ["SAPCFG_ALLOW_REAL_SAP"] = "1"
        gui = mac_gui.MacSapGui(system="ADT", client="110")
        self.assertEqual(gui.system, "ADT")
        self.assertEqual(gui.client, "110")

    def test_flag_file_consent_grants_construction(self):
        fake = mac_gui.ROOT / "tests" / "tmp_flag_test"
        fake.write_text("consent")
        self.addCleanup(lambda: fake.unlink(missing_ok=True))
        try:
            with mock.patch.object(mac_gui, "FLAG_FILE", fake):
                gui = mac_gui.MacSapGui()
                self.assertIsNotNone(gui)
        finally:
            fake.unlink(missing_ok=True)

    def test_refuses_non_darwin(self):
        os.environ["SAPCFG_ALLOW_REAL_SAP"] = "1"
        with mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(SystemError):
                mac_gui.MacSapGui()

    def test_real_sap_allowed_detects_flag(self):
        fake = mac_gui.ROOT / "tests" / "tmp_flag_detect"
        fake.write_text("x")
        self.addCleanup(lambda: fake.unlink(missing_ok=True))
        with mock.patch.object(mac_gui, "FLAG_FILE", fake):
            self.assertTrue(mac_gui.real_sap_allowed())
        os.environ.pop("SAPCFG_ALLOW_REAL_SAP", None)
        with mock.patch.object(mac_gui, "FLAG_FILE",
                               mac_gui.ROOT / "definitely_missing"):
            self.assertFalse(mac_gui.real_sap_allowed())


if __name__ == "__main__":
    unittest.main()
