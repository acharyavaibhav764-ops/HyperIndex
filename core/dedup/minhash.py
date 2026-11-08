"""
MinHash-based near-duplicate detection for versioning.

Shingle-based MinHash sketch (84 permutations).  Alphanumeric tokenisation
is used deliberately so that numerical values such as part numbers, voltages,
and tolerances (e.g. "14V", "30V", "TC500") are preserved and contribute to
the fingerprint — changes in these values will correctly lower the Jaccard
similarity and avoid false "same version" conclusions.

Sliding word shingles (k=4) are combined with line/sentence keyphrases so that
cross-format conversions (e.g. PDF visual layout vs. Word XML paragraphs and
tables) produce highly reliable Jaccard similarity estimates.
"""
from __future__ import annotations

import re
import zlib

# Common English stop-words to strip before fingerprinting
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "do", "for", "from", "has", "have", "he", "her", "his", "how",
    "i", "if", "in", "is", "it", "its", "me", "my", "no", "not",
    "of", "on", "or", "our", "out", "so", "than", "that", "the",
    "their", "them", "then", "there", "they", "this", "to", "up",
    "us", "was", "we", "were", "what", "when", "which", "who",
    "will", "with", "you", "your",
})

# Mersenne prime for the universal hash family (a*x + b) mod p
_PRIME: int = 2_147_483_647  # 2^31 - 1


class MinHashDeduplicator:
    """
    Compute and compare 84-slot MinHash sketches for document text.

    Attributes:
        num_perm:    Number of independent hash functions (sketch width).
        threshold:   Minimum Jaccard similarity to call a near-duplicate.
        shingle_k:   Number of words per sliding shingle.

    Methods:
        compute_sketch()
        jaccard_similarity()
        is_near_duplicate()
        best_match()
    """

    def __init__(self, num_perm: int = 84, threshold: float = 0.65, shingle_k: int = 4) -> None:
        self.num_perm = num_perm
        self.threshold = threshold
        self.shingle_k = shingle_k

        # Deterministic coefficients — fixed across all processes/restarts
        self._a: list[int] = [
            ((i * 10_007 + 3) % (_PRIME - 1)) + 1 for i in range(num_perm)
        ]
        self._b: list[int] = [
            (i * 20_011 + 7) % _PRIME for i in range(num_perm)
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _tokenise(self, text: str) -> list[str]:
        """Return meaningful alphanumeric tokens, retaining numbers/codes."""
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        return [t for t in tokens if t not in _STOP_WORDS]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_sketch(self, text: str) -> list[int]:
        """
        Build an 84-integer MinHash sketch from *text*.

        Combines sliding word n-gram shingles with structural phrase fingerprints,
        then computes the column-wise minimum over all 84 hash functions:
            h(x) = (a * x + b) mod p

        Returns a list of num_perm integers, or all-zeros if text is empty.
        """
        clean_tokens = self._tokenise(text)
        if not clean_tokens:
            return [0] * self.num_perm

        h_set: set[int] = set()

        # 1. Sliding word n-gram shingles (captures continuous phrase context)
        k = self.shingle_k
        if len(clean_tokens) >= k:
            for i in range(len(clean_tokens) - k + 1):
                shingle = "_".join(clean_tokens[i : i + k])
                h_set.add(zlib.crc32(shingle.encode("utf-8")) & 0xFFFF_FFFF)
        else:
            h_set.add(zlib.crc32("_".join(clean_tokens).encode("utf-8")) & 0xFFFF_FFFF)

        # 2. Line / sentence level keyphrases (captures headings and short table cells)
        lines = re.split(r"[\r\n.!?]+", text)
        for line in lines:
            lt = self._tokenise(line)
            if len(lt) >= 2:
                key = "_".join(sorted(lt[:4]))
                h_set.add(zlib.crc32(key.encode("utf-8")) & 0xFFFF_FFFF)

        if not h_set:
            return [0] * self.num_perm

        # MinHash permutation step: keep the minimum hash value for each of the 84 functions
        sketch: list[int] = []
        for a, b in zip(self._a, self._b):
            min_val = min((a * h + b) % _PRIME for h in h_set)
            sketch.append(min_val)
        return sketch

    @staticmethod
    def jaccard_similarity(sketch_a: list[int] | str | None, sketch_b: list[int] | str | None) -> float:
        """
        Estimate Jaccard similarity from two MinHash sketches.

        Returns the fraction of the 84 positions that match.
        """
        import json

        if not sketch_a or not sketch_b:
            return 0.0

        if isinstance(sketch_a, str):
            try:
                sketch_a = json.loads(sketch_a)
            except Exception:
                return 0.0

        if isinstance(sketch_b, str):
            try:
                sketch_b = json.loads(sketch_b)
            except Exception:
                return 0.0

        if not isinstance(sketch_a, list) or not isinstance(sketch_b, list):
            return 0.0

        if len(sketch_a) != len(sketch_b) or len(sketch_a) == 0:
            return 0.0

        matches = sum(1 for x, y in zip(sketch_a, sketch_b) if x == y)
        return matches / len(sketch_a)

    def is_near_duplicate(
        self, sketch_a: list[int], sketch_b: list[int]
    ) -> bool:
        """Return True if the two sketches exceed the similarity threshold."""
        return self.jaccard_similarity(sketch_a, sketch_b) >= self.threshold

    def best_match(
        self, new_sketch: list[int], candidates: list[tuple[str, list[int]]]
    ) -> tuple[str | None, float]:
        """
        Find the most similar candidate sketch.

        Args:
            new_sketch:  Sketch for the incoming document.
            candidates:  List of (document_id, sketch) for existing documents.

        Returns:
            (best_document_id, best_score) or (None, 0.0) if no candidates.
        """
        best_id: str | None = None
        best_score: float = 0.0
        for doc_id, sketch in candidates:
            score = self.jaccard_similarity(new_sketch, sketch)
            if score > best_score:
                best_score = score
                best_id = doc_id
        return best_id, best_score
