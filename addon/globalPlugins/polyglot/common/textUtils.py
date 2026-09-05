# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

from collections.abc import Callable


def splitText(
	text: str,
	maxLength: int,
	lengthFunction: Callable[[str], int] = len,
) -> list[str]:
	"""
	Split text recursively into chunks of at most maxLength measured units.
	Attempts to split at natural boundaries like paragraphs, sentences, and words.
	"""
	if maxLength <= 0 or lengthFunction(text) <= maxLength:
		return [text]

	def _splitByLength(currentText: str) -> list[str]:
		"""Split at code-point boundaries while respecting the supplied unit metric."""
		chunks: list[str] = []
		currentChunk: list[str] = []
		currentLength = 0
		for character in currentText:
			characterLength = lengthFunction(character)
			if currentChunk and currentLength + characterLength > maxLength:
				chunks.append("".join(currentChunk))
				currentChunk = []
				currentLength = 0
			currentChunk.append(character)
			currentLength += characterLength
		if currentChunk:
			chunks.append("".join(currentChunk))
		return chunks

	def _split(currentText: str, separators: list[str]) -> list[str]:
		if lengthFunction(currentText) <= maxLength:
			return [currentText]
		if not separators:
			return _splitByLength(currentText)

		sep = separators[0]
		if sep == "":
			return _splitByLength(currentText)

		chunks = currentText.split(sep)
		newChunks = []
		for i, chunk in enumerate(chunks):
			if i < len(chunks) - 1:
				newChunks.append(chunk + sep)
			else:
				if chunk:
					newChunks.append(chunk)

		result = []
		currentChunk = ""

		for c in newChunks:
			if lengthFunction(c) > maxLength:
				if currentChunk:
					result.append(currentChunk)
					currentChunk = ""
				# Recursively split the oversized chunk with remaining separators
				subChunks = _split(c, separators[1:])
				result.extend(subChunks)
			else:
				if lengthFunction(currentChunk) + lengthFunction(c) <= maxLength:
					currentChunk += c
				else:
					if currentChunk:
						result.append(currentChunk)
					currentChunk = c

		if currentChunk:
			result.append(currentChunk)

		return result

	return _split(text, ["\n\n", "\n", ". ", "。", " ", ""])


def isWorthTranslating(text: str) -> bool:
	"""Return whether text holds anything a translation engine could act on.

	A string made only of digits, punctuation, symbols, emoji, whitespace or any
	mixture of those carries no words, so translating it can only return it
	unchanged.  Some engines refuse it outright: Naver reports an error for a
	string of digits.  Any letter in any script, Han and Hangul included, makes
	the string worth sending.
	"""
	return any(character.isalpha() for character in text)
