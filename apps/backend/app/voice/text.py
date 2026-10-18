import re


_ABBREVIATION_RE = re.compile(
    r"(?<!\w)(?:т\.\s*[дпек]\.|(?:г|ул|рис|стр|им|руб|коп)\.)(?!\w)",
    re.IGNORECASE,
)


def protect_sentence_boundaries(text: str) -> str:
    """Mask non-terminal dots without changing offsets into the original text."""
    text = _ABBREVIATION_RE.sub(lambda m: m.group().replace(".", "∯"), text)
    text = re.sub(r"(?<!\w)т\.(?:\s*[дпек]\.?)?(?=\s*$)", lambda m: m.group().replace(".", "∯"), text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", lambda m: m.group().replace(".", "∯"), text, flags=re.IGNORECASE)
    return re.sub(r"(?<=\d)\.(?=\d)", "∯", text)


class TextNormalizer:
    _CODE_BLOCK = re.compile(r"```.*?(?:```|$)|~~~.*?(?:~~~|$)", re.DOTALL)
    _URL = re.compile(r"https?://\S+", re.IGNORECASE)
    _SERVICE_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
    _MARKDOWN = re.compile(r"[*_~#]+")

    def remove_code_blocks(self, text: str) -> str:
        return self._CODE_BLOCK.sub(" ", text)

    def normalize(self, text: str, *, preserve_newlines: bool = False) -> str:
        text = self.remove_code_blocks(text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = self._URL.sub(lambda m: "ссылка" + m.group()[len(m.group().rstrip(".,!?;:»\"")):], text)
        text = self._SERVICE_TAG.sub(" ", text)
        text = re.sub(r"(?m)^[ \t]*>[ \t]?", "", text)
        text = re.sub(r"(?<=[\d)])\s*\*\*\s*(?=[+-]?\d|\()", " ^ ", text)
        text = re.sub(r"(?<=[\d)])\s*\*\s*(?=[+-]?\d|\()", " × ", text)
        text = self._MARKDOWN.sub("", text)
        return re.sub(r"[^\S\n]+" if preserve_newlines else r"\s+", " ", text).strip()


class FencedCodeFilter:
    """Discard fenced code before streaming text is split into speech jobs."""

    def __init__(self) -> None:
        self._buffer = ""
        self._fence: str | None = None

    def feed(self, text: str) -> str:
        self._buffer += text
        parts = []
        while self._buffer:
            if self._fence is not None:
                end = self._buffer.find(self._fence)
                if end < 0:
                    # Only a possible fragmented closing fence needs retention.
                    self._buffer = self._buffer[-2:]
                    break
                self._buffer = self._buffer[end + 3:]
                self._fence = None
                parts.append(" ")
                continue
            match = re.search(r"```|~~~", self._buffer)
            if match:
                parts.append(self._buffer[:match.start()])
                self._fence = match.group()
                self._buffer = self._buffer[match.end():]
                parts.append(" ")
                continue
            partial = re.search(r"[`~]{1,2}$", self._buffer)
            if partial:
                parts.append(self._buffer[:partial.start()])
                self._buffer = self._buffer[partial.start():]
            else:
                parts.append(self._buffer)
                self._buffer = ""
            break
        return "".join(parts)

    def finish(self) -> str:
        tail = self._buffer if self._fence is None else ""
        self._buffer = ""
        self._fence = None
        return tail


class TextChunker:
    _HARD_BOUNDARY = re.compile(r"[.!?…](?:[\"'»”)]*)(?:\s+|$)|\n+")
    _SOFT_BOUNDARY = re.compile(r"(?:[;:]|[—–])(?:[\"'»)]*)(?:\s+|$)")
    _FIRST_CLAUSE_BOUNDARY = re.compile(r"(?:[,;:]|[—–])(?:[\"'»)]*)(?:\s+|$)")
    _DASH_BOUNDARY = re.compile(r"[—–](?:[\"'»)]*)(?:\s+|$)")

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

    @property
    def emitted(self) -> bool:
        return self._emitted

    @property
    def has_pending_text(self) -> bool:
        return bool(re.search(r"\w", self._buffer))

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        return self._drain_complete()

    def flush_idle(self) -> list[str]:
        minimum = self._first_target if not self._emitted else self._next_target
        if not re.search(r"\w", self._buffer):
            return []
        if re.search(r"\d[.,]$", self._buffer):
            return []  # A decimal/date/version can continue in the next delta.
        boundary = self._find_boundary()
        if boundary is not None:
            return [self._take(boundary)]
        # A delta ending in a letter may be the middle of a token.  Idle flushes
        # are only safe after whitespace/punctuation and never for a tiny tail.
        if len(self._buffer.strip()) < minimum or not re.search(r"(?:\s|[.!?…;:,])$", self._buffer):
            return []
        if len(self._buffer.split()) < 4:
            return []
        return [self._take(len(self._buffer))]

    def flush(self) -> list[str]:
        chunks = self._drain_complete()
        while self._buffer.strip():
            chunks.append(self._take(self._split_at_limit(self._buffer)))
        chunks = [chunk for chunk in chunks if re.search(r"\w", chunk)]
        if len(chunks) >= 2 and len(chunks[-1].split()) <= 3:
            combined = f"{chunks[-2]} {chunks[-1]}".strip()
            if len(combined) <= self._max_chars and len(combined.split()) <= self._max_words:
                chunks[-2:] = [combined]
        return chunks

    def _drain_complete(self) -> list[str]:
        chunks: list[str] = []
        while self._buffer.strip():
            boundary = self._find_boundary(allow_terminal=False)
            if boundary is not None and self._fits(self._buffer[:boundary]):
                chunks.append(self._take(boundary))
                continue
            if len(self._buffer) > self._max_chars or len(self._buffer.split()) > self._max_words:
                end = self._split_at_limit(self._buffer)
                if end == len(self._buffer) and not self._buffer[-1].isspace():
                    break  # A long token may still be arriving; do not bisect it.
                chunks.append(self._take(end))
                continue
            if boundary is None:
                break
            chunks.append(self._take(boundary))
        return [chunk for chunk in chunks if re.search(r"\w", chunk)]

    def _find_boundary(self, start: int = 0, *, allow_terminal: bool = True) -> int | None:
        protected = protect_sentence_boundaries(self._buffer)
        if not allow_terminal:
            protected = re.sub(r"[.!?…;:,—–]+[\"'»)]*$", lambda m: "∯" * len(m.group()), protected)
        target = self._first_target if not self._emitted else self._next_target
        hard = self._HARD_BOUNDARY.search(protected, pos=start)
        dash = self._DASH_BOUNDARY.search(protected, pos=start)
        if (
            dash
            and (hard is None or dash.end() < hard.end())
            and dash.end() >= min(target, 28)
            and len(re.findall(r"\w+", protected[: dash.end()], flags=re.UNICODE)) >= 5
        ):
            return dash.end()
        if hard:
            return hard.end()
        if not self._emitted:
            first_clause = self._FIRST_CLAUSE_BOUNDARY.search(protected, pos=start)
            if (
                first_clause
                and first_clause.end() >= min(target, 28)
                and len(protected[: first_clause.end()].split()) >= 6
            ):
                return first_clause.end()
        matches = []
        for priority, pattern in enumerate((self._SOFT_BOUNDARY,)):
            for match in pattern.finditer(protected, pos=start):
                matches.append((priority, abs(match.end() - target), match.end()))
        eligible = [item for item in matches if item[2] >= min(target, 30)]
        if eligible:
            return min(eligible, key=lambda item: (item[0], item[1]))[2]
        return min(matches, key=lambda item: (item[0], item[1]))[2] if matches else None

    def _split_at_limit(self, text: str) -> int:
        if self._fits(text):
            return len(text)
        char_limit = min(self._max_chars, self._word_limit_index(text))
        prefix = text[: char_limit + 1]
        for match in reversed(list(re.finditer(r"[—–;:,](?=\s)", prefix))):
            if match.start() >= max(1, char_limit // 2):
                return match.end()
        spaces = list(re.finditer(r"\s+", prefix))
        if spaces:
            return spaces[-1].start() or spaces[-1].end()
        # The limit is a target for natural speech, never a reason to cut a word.
        space = re.search(r"\s", text)
        return space.start() if space else len(text)

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
        if re.search(r"\w", value):
            self._emitted = True
        return value
