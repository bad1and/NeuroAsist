import re


class TextNormalizer:
    _CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
    _URL = re.compile(r"https?://\S+", re.IGNORECASE)
    _SERVICE_TAG = re.compile(r"<[^>]+>")
    _MARKDOWN = re.compile(r"[*_~>#]+")

    def normalize(self, text: str) -> str:
        text = self._CODE_BLOCK.sub(" ", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = self._URL.sub("ссылка", text)
        text = self._SERVICE_TAG.sub(" ", text)
        text = self._MARKDOWN.sub("", text)
        return re.sub(r"\s+", " ", text).strip()


class TextChunker:
    _BOUNDARY = re.compile(r"[.!?;](?:[\"'»)]*)\s+")
    _ABBREVIATIONS = ("т. д.", "т. п.", "т. е.")

    def __init__(
        self,
        first_target: int = 50,
        next_target: int = 80,
        max_chars: int = 90,
        max_words: int = 18,
    ) -> None:
        self._buffer = ""
        self._first_target = first_target
        self._next_target = next_target
        self._max_chars = max_chars
        self._max_words = max_words
        self._emitted = False

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        return self._drain_complete()

    def flush_idle(self) -> list[str]:
        minimum = self._first_target if not self._emitted else self._next_target
        if not re.search(r"\w", self._buffer):
            return []
        boundary = self._find_boundary()
        if boundary is not None:
            return [self._take(boundary)]
        if len(self._buffer.strip()) < minimum or not re.search(r"\w\s*$", self._buffer):
            return []
        return [self._take(len(self._buffer))]

    def flush(self) -> list[str]:
        chunks = self._drain_complete()
        while self._buffer.strip():
            chunks.append(self._take(self._split_at_limit(self._buffer)))
        return [chunk for chunk in chunks if re.search(r"\w", chunk)]

    def _drain_complete(self) -> list[str]:
        chunks: list[str] = []
        while self._buffer.strip():
            if len(self._buffer) > self._max_chars or len(self._buffer.split()) > self._max_words:
                chunks.append(self._take(self._split_at_limit(self._buffer)))
                continue
            boundary = self._find_boundary()
            if boundary is None:
                break
            chunks.append(self._take(boundary))
        return [chunk for chunk in chunks if re.search(r"\w", chunk)]

    def _find_boundary(self, start: int = 0) -> int | None:
        protected = self._buffer
        for abbreviation in self._ABBREVIATIONS:
            protected = protected.replace(abbreviation, abbreviation.replace(".", "∯"))
        protected = re.sub(r"(?<=\d)\.(?=\d)", "∯", protected)
        match = self._BOUNDARY.search(protected, pos=start)
        return match.end() if match else None

    def _split_at_limit(self, text: str) -> int:
        if self._fits(text):
            return len(text)
        char_limit = min(self._max_chars, self._word_limit_index(text))
        prefix = text[: char_limit + 1]
        for separator in (",", " "):
            index = prefix.rfind(separator)
            if index >= max(1, char_limit // 2):
                return index + (1 if separator == "," else 0)
        return char_limit

    def _fits(self, text: str) -> bool:
        return len(text.strip()) <= self._max_chars and len(text.split()) <= self._max_words

    def _word_limit_index(self, text: str) -> int:
        matches = list(re.finditer(r"\S+", text))
        if len(matches) <= self._max_words:
            return len(text)
        return matches[self._max_words].start()

    def _take(self, end: int) -> str:
        value = self._buffer[:end].strip()
        self._buffer = self._buffer[end:].lstrip()
        self._emitted = True
        return value
