from types import SimpleNamespace
import unittest

from cogs.management import ManagementCommand
from main import bot


class MeowBotConfigurationTests(unittest.TestCase):
    def test_discovers_expected_extensions(self) -> None:
        names = bot.discover_extension_names()

        self.assertIn("avatar", names)
        self.assertIn("management", names)
        self.assertIn("music_cog", names)
        self.assertNotIn("__init__", names)

    def test_extension_path_uses_discovered_allowlist(self) -> None:
        self.assertEqual(bot.extension_path("avatar"), "cogs.avatar")
        self.assertIsNone(bot.extension_path("../main"))
        self.assertIsNone(bot.extension_path("missing"))

    def test_required_intents_are_enabled(self) -> None:
        self.assertTrue(bot.intents.members)
        self.assertTrue(bot.intents.message_content)

    def test_direct_messages_do_not_receive_admin_access(self) -> None:
        interaction = SimpleNamespace(guild=None, user=object())

        self.assertFalse(ManagementCommand._is_admin(interaction))


if __name__ == "__main__":
    unittest.main()
