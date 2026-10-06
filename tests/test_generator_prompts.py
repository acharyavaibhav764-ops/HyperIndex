import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from core.generator import (
    DEFAULT_PROMPT_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT,
    GenerationError,
    Generator,
)


class TestGeneratorPrompts(unittest.TestCase):
    def test_default_prompts_defined(self):
        self.assertIsInstance(DEFAULT_SYSTEM_PROMPT, str)
        self.assertIn("Honeywell", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("Systevo", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("FACTUAL GROUNDING", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("SAFETY FIRST", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("[Doc: <filename>, Page: <page>]", DEFAULT_SYSTEM_PROMPT)

        self.assertIsInstance(DEFAULT_PROMPT_TEMPLATE, str)
        self.assertIn("{context}", DEFAULT_PROMPT_TEMPLATE)
        self.assertIn("{question}", DEFAULT_PROMPT_TEMPLATE)
        self.assertIn("CONTEXT EXCERPTS:", DEFAULT_PROMPT_TEMPLATE)

    def test_generator_initialization_defaults(self):
        generator = Generator()
        self.assertEqual(generator.system_prompt, DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(generator.prompt_template, DEFAULT_PROMPT_TEMPLATE)

    def test_generator_custom_prompts(self):
        custom_system = "Custom System Prompt"
        custom_template = "Context: {context} | Q: {question}"

        generator = Generator(
            system_prompt=custom_system,
            prompt_template=custom_template,
        )
        self.assertEqual(generator.system_prompt, custom_system)
        self.assertEqual(generator.prompt_template, custom_template)

    def test_build_prompt_structure(self):
        generator = Generator()
        documents = [
            "The SEM-IP connects via DBUS and ABUS.",
            "Systevo Room Display requires software V.12.10R200.",
        ]
        metadatas = [
            {"filename": "89500A6.GB0.pdf", "page": 26},
            {"filename": "89475A3.GB0.pdf", "page": 1},
        ]
        question = "What are the SEM-IP bus connections?"

        prompt = generator.build_prompt(question, documents, metadatas)

        # Context chunks formatting verification
        self.assertIn("[Document 1: 89500A6.GB0.pdf | Page 26]", prompt)
        self.assertIn("The SEM-IP connects via DBUS and ABUS.", prompt)
        self.assertIn("[Document 2: 89475A3.GB0.pdf | Page 1]", prompt)
        self.assertIn("Systevo Room Display requires software V.12.10R200.", prompt)
        self.assertIn("### QUESTION:\nWhat are the SEM-IP bus connections?", prompt)
        self.assertIn("### ANSWER:", prompt)

    def test_build_prompt_metadata_fallback(self):
        generator = Generator()
        documents = ["Sample content without explicit metadata"]
        metadatas = [{}]
        question = "What is this?"

        prompt = generator.build_prompt(question, documents, metadatas)
        self.assertIn("[Document 1: Unknown Document | Page Unknown]", prompt)
        self.assertIn("Sample content without explicit metadata", prompt)

    @patch("core.generator.urlopen")
    def test_generate_sends_system_prompt_to_ollama(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"response": "Grounded answer based on manuals."}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        generator = Generator()
        prompt = "Sample assembled prompt"
        answer = generator.generate(prompt)

        self.assertEqual(answer, "Grounded answer based on manuals.")
        mock_urlopen.assert_called_once()

        # Verify the HTTP request payload sent to Ollama
        call_args = mock_urlopen.call_args[0]
        request = call_args[0]
        payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(payload["model"], generator.model)
        self.assertEqual(payload["system"], generator.system_prompt)
        self.assertEqual(payload["prompt"], prompt)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["keep_alive"], -1)
        self.assertEqual(payload["options"]["temperature"], 0.0)

    @patch("core.generator.urlopen")
    def test_generate_handles_empty_response(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"response": ""}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        generator = Generator()
        with self.assertRaises(GenerationError) as ctx:
            generator.generate("Some prompt")
        self.assertIn("empty response", str(ctx.exception))

    @patch("core.generator.urlopen")
    def test_generate_handles_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("Connection refused")

        generator = Generator()
        with self.assertRaises(GenerationError) as ctx:
            generator.generate("Some prompt")
        self.assertIn("Unable to reach Ollama", str(ctx.exception))
