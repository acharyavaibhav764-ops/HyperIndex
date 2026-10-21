import unittest
from collections import Counter

from core.parsers.pdf.transforms.cleanup import (
    build_vocab,
    clean_markdown_page,
    clean_markdown_tables,
    collapse_letter_spacing,
    fix_heading_number,
    fix_lost_spaces,
    is_noise_paragraph,
    rejoin_urls,
    renumber_sequence,
    repair_heading_sequence,
    segment_words,
    strip_running_lines,
    strip_vlm_tokens,
)


class TestPdfCleanup(unittest.TestCase):
    """Unit tests for token scrubbing, boilerplate line cleanup, and table/sequence repairs."""

    def test_strip_vlm_tokens(self):
        """strip_vlm_tokens removes leaked generation tokens such as <end_of_utteranc>."""
        raw = "Temperature sensor overview.<end_of_utteranc>"
        cleaned = strip_vlm_tokens(raw)
        self.assertEqual(cleaned, "Temperature sensor overview.")

        raw_incomplete = "Sensor circuit diagram.<end_of_"
        cleaned_incomplete = strip_vlm_tokens(raw_incomplete)
        self.assertEqual(cleaned_incomplete, "Sensor circuit diagram.")

    def test_strip_running_lines_headers_and_footers(self):
        """strip_running_lines detects and removes recurring page headers/footers."""
        pages = [
            "Honeywell Confidential Header\n\nPage 1 Content\n\nPage 1 of 3",
            "Honeywell Confidential Header\n\nPage 2 Content\n\nPage 2 of 3",
            "Honeywell Confidential Header\n\nPage 3 Content\n\nPage 3 of 3",
        ]
        cleaned = strip_running_lines(pages)
        for page in cleaned:
            self.assertNotIn("Honeywell Confidential Header", page)
        self.assertIn("Page 1 Content", cleaned[0])
        self.assertIn("Page 2 Content", cleaned[1])
        self.assertIn("Page 3 Content", cleaned[2])

    def test_clean_markdown_page(self):
        """clean_markdown_page collapses excessive consecutive newlines and strips tokens."""
        raw = "Paragraph 1\n\n\n\n\nParagraph 2<unused0>"
        cleaned = clean_markdown_page(raw)
        self.assertEqual(cleaned, "Paragraph 1\n\nParagraph 2")

    # ------------------------------------------------------------------------
    # Phase 1: Vocabulary & Dynamic Programming Word Segmentation Tests
    # ------------------------------------------------------------------------

    def test_build_vocab_and_segment_words(self):
        """build_vocab builds frequency dictionary and segment_words splits glued tokens."""
        sample_texts = [
            "The system parameters and calibration settings are normal.",
            "Please check the system parameters before operation.",
        ]
        vocab = build_vocab(sample_texts)
        self.assertGreater(vocab["system"], 0)
        self.assertGreater(vocab["parameters"], 0)

        pieces = segment_words("systemparameters", vocab)
        self.assertEqual(pieces, ["system", "parameters"])

    def test_fix_lost_spaces_and_camelcase(self):
        """fix_lost_spaces rejoins words and respects CamelCase tokens."""
        vocab = Counter({"system": 5, "parameters": 5, "ring": 3, "dips": 3})
        text = "Check the systemparameters and RingDips routine."
        fixed = fix_lost_spaces(text, vocab)
        self.assertIn("system parameters", fixed)
        self.assertIn("Ring Dips", fixed)

    def test_collapse_letter_spacing(self):
        """collapse_letter_spacing rejoins spaced-out letters into coherent words."""
        text = "This is R o u n d 1 of the testing phase."
        self.assertEqual(collapse_letter_spacing(text), "This is Round 1 of the testing phase.")

    def test_rejoin_urls(self):
        """rejoin_urls fixes URLs split by spaces or line breaks."""
        broken_url = "Visit https:/ /honeywell.com/ safety / instructions for details."
        fixed = rejoin_urls(broken_url)
        self.assertIn("https://honeywell.com/safety/instructions", fixed)

    def test_is_noise_paragraph(self):
        """is_noise_paragraph flags layout debris while keeping actual content."""
        self.assertTrue(is_noise_paragraph(". . ."))
        self.assertTrue(is_noise_paragraph("..."))
        self.assertFalse(is_noise_paragraph("Normal instruction paragraph explaining sensor operations."))

    # ------------------------------------------------------------------------
    # Phase 2: Markdown Table Normalization & Sequence Repairs Tests
    # ------------------------------------------------------------------------

    def test_clean_markdown_tables_side_by_side(self):
        """clean_markdown_tables splits side-by-side tables into consecutive blocks."""
        table_md = (
            "| Meat / Eggs | Protein (per 100g) | Fish | Protein (per 100g) |\n"
            "|---|---|---|---|\n"
            "| Beef | 24 | Tuna | 25 |\n"
            "| Eggs | 13 | Mackerel | 18 |"
        )
        cleaned = clean_markdown_tables(table_md)
        self.assertIn("| Fish | Protein (per 100g) |", cleaned)
        self.assertIn("| Beef | 24 |", cleaned)

    def test_clean_markdown_tables_subheaders(self):
        """clean_markdown_tables splits category subheaders inside a single table."""
        table_md = (
            "| Round | 1 (Dynamic) | Reps | Target Muscles |\n"
            "|---|---|---|---|\n"
            "| Exc. 1 | Dragon Fly | 8 | Core |\n"
            "| Round | 2 (Static) | Reps | Target Muscles |\n"
            "| Exc. 1 | Dragon Flag | Max | Core |"
        )
        cleaned = clean_markdown_tables(table_md)
        self.assertEqual(cleaned.count("| Round 1 (Dynamic) |"), 1)
        self.assertEqual(cleaned.count("| Round 2 (Static) |"), 1)

    def test_heading_number_and_sequence_repairs(self):
        """fix_heading_number, repair_heading_sequence and renumber_sequence correct numbering."""
        # fix_heading_number
        self.assertEqual(fix_heading_number("6.5. 1Chest Circuit"), "6.5.1 Chest Circuit")

        # repair_heading_sequence (fixes backtracking 6.2.2 after 6.5.1)
        seq = ["6.5.1 Upper Body", "6.2.2 Lower Body"]
        repaired = repair_heading_sequence(seq)
        self.assertEqual(repaired, ["6.5.1 Upper Body", "6.5.2 Lower Body"])

        # renumber_sequence
        labels = ["Day 7", "Day 2", "Day 3"]
        renumbered = renumber_sequence(labels)
        self.assertEqual(renumbered, ["Day 1", "Day 2", "Day 3"])


if __name__ == "__main__":
    unittest.main()
