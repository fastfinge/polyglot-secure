# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the text helpers, chiefly the filter that keeps wordless strings unsent."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.common.textUtils import isWorthTranslating  # noqa: E402


class IsWorthTranslatingTestCase(unittest.TestCase):
	"""A string is worth sending to an engine only when it holds a letter."""

	def test_wordlessStringsAreSkipped(self) -> None:
		"""Digits, punctuation, emoji and their mixtures never reach an engine."""
		for text in (
			"",
			"   ",
			"123",
			"3.14",
			"1,234,567",
			"2026-09-05 12:30",
			"...",
			"(!?)",
			"-- >>",
			"100% (+5)",
			"😀",
			"👨‍👩‍👧",
			"❤️👍🏽",
			"👍 100%",
		):
			with self.subTest(text=text):
				self.assertFalse(isWorthTranslating(text))

	def test_stringsWithLettersAreTranslated(self) -> None:
		"""One letter in any script is enough, even beside digits or emoji."""
		for text in (
			"a",
			"Hello world",
			"Page 3 of 10",
			"100 dollars",
			"👍 ok",
			"你好",
			"안녕하세요",
			"مرحبا",
			"Привет",
		):
			with self.subTest(text=text):
				self.assertTrue(isWorthTranslating(text))


if __name__ == "__main__":
	unittest.main()
