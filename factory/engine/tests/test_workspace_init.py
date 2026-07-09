"""Workspace bootstrap — blank + slug validation."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.workspace_init import (
    init_blank_workspace,
    normalize_workspace_id,
    validate_workspace_id,
)


class TestWorkspaceId(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(normalize_workspace_id("Midnight Harbor"), "midnight-harbor")
        self.assertEqual(normalize_workspace_id("  CEO Contract 2 "), "ceo-contract-2")

    def test_validate(self):
        self.assertIsNone(validate_workspace_id("glass-meridian"))
        self.assertIsNotNone(validate_workspace_id("ab"))
        self.assertIsNotNone(validate_workspace_id("1bad"))


class TestBlankWorkspace(unittest.TestCase):
    def test_creates_empty_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspaces"
            root.mkdir()
            with patch("factory.engine.lib.workspace_init.workspace_dir", lambda name: root / name):
                path = init_blank_workspace("my-new-book", title="My Book", target_language="vi")
            self.assertTrue((path / "concept.yaml").exists())
            self.assertTrue((path / "direction.yaml").exists())
            self.assertFalse(any((path / "bible" / "narrative").glob("*.json")))
            shutil.rmtree(path)


if __name__ == "__main__":
    unittest.main()
