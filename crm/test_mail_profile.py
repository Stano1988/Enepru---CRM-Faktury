import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from .mail_profile import FILENAME, SERVICE, load_profile, save_profile


class MailProfileTests(SimpleTestCase):
    def test_password_stays_in_system_vault_not_profile(self):
        vault = type("Vault", (), {"__module__": "keyring.backends.Windows"})()
        storage = {}
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch("crm.mail_profile.platform.system", return_value="Windows"),
                patch("keyring.get_keyring", return_value=vault),
                patch(
                    "keyring.set_password",
                    side_effect=lambda service, key, password: storage.update(
                        {(service, key): password}
                    ),
                ),
                patch(
                    "keyring.get_password",
                    side_effect=lambda service, key: storage.get((service, key)),
                ),
            ):
                save_profile(
                    Path(folder),
                    "mail@example.invalid",
                    "test-only-password",
                    "Poptavky",
                    True,
                )
                text = (Path(folder) / FILENAME).read_text()
                self.assertNotIn("test-only-password", text)
                metadata = json.loads(text)
                self.assertEqual(
                    storage[(SERVICE, metadata["credential_id"])], "test-only-password"
                )
                self.assertEqual(load_profile(folder)["password"], "test-only-password")
                self.assertTrue(metadata["auto_create"])

    def test_no_plaintext_fallback_when_system_vault_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("crm.mail_profile.platform.system", return_value="Linux"):
                with self.assertRaises(RuntimeError):
                    save_profile(folder, "mail@example.invalid", "test-only-password")
            self.assertFalse((Path(folder) / FILENAME).exists())

    def test_profile_missing_is_harmless(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_profile(folder), {})
