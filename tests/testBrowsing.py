import unittest

from pentestgpt.test_connection import get_project_version


class TestUtilityFunctions(unittest.TestCase):
    def test_get_project_version_returns_non_empty_string(self):
        version = get_project_version()
        self.assertIsInstance(version, str)
        self.assertNotEqual(version.strip(), "")


if __name__ == "__main__":
    unittest.main()
