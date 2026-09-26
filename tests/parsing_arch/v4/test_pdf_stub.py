import pytest
from unittest.mock import MagicMock, patch
from docling_core.types.doc import DoclingDocument
from docling.datamodel.base_models import DocumentStream

from parsers.pdf_stub import PdfStubParser

def test_can_handle():
    parser = PdfStubParser()
    assert parser.can_handle(".pdf") is True
    assert parser.can_handle(".PDF") is True
    assert parser.can_handle(".txt") is False
    assert parser.can_handle(".docx") is False

@patch("parsers.pdf_stub.DocumentConverter")
def test_parse(mock_converter_class):
    # Set up the mock DocumentConverter and its return value
    mock_converter_instance = MagicMock()
    mock_converter_class.return_value = mock_converter_instance
    
    # Mock the conversion result
    mock_result = MagicMock()
    mock_doc = MagicMock(spec=DoclingDocument)
    mock_result.document = mock_doc
    mock_converter_instance.convert.return_value = mock_result
    
    # Initialize the parser
    parser = PdfStubParser()
    
    # Execute the parse method
    file_bytes = b"dummy pdf content"
    filename = "sample.pdf"
    result = parser.parse(file_bytes, filename)
    
    # Assertions
    assert result == mock_doc, "The returned document should match the converter's output"
    mock_converter_instance.convert.assert_called_once()
    
    # Verify it was called with a DocumentStream wrapping our bytes
    call_args = mock_converter_instance.convert.call_args[0]
    doc_stream = call_args[0]
    assert isinstance(doc_stream, DocumentStream), "Expected a DocumentStream to be passed to Docling"
    assert doc_stream.name == filename, "Filename should match"
