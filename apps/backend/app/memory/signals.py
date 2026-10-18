"""Cheap scheduling signals; semantic memory decisions belong to the model."""
import re


MEMORY_CORRECTION_CUE = re.compile(
    r"(?iu)(?:"
    r"\bне\s+[^.!?\n]{1,120}?\s*,?\s+а\s+[^.!?\n]+"
    r"|\b(?:на\s+самом\s+деле|теперь\s+я|я\s+больше\s+не|зови\s+меня|исправ\w*)\b"
    r"|\bнет[, :]+(?:я|меня|мой|моя|мо[её]|теперь|это|у)\b"
    r")"
)
