"""
tests/parsing_arch/v5/test_config_v5.py

Verify that the three v5 config settings load with correct defaults
and that environment variable overrides are respected.
"""
import os
import importlib
import pytest


def _reload_settings(overrides: dict[str, str] | None = None):
    """Reload config.Settings with a clean env, applying any overrides."""
    env_backup = os.environ.copy()
    # Clear the three v5 keys so we get clean defaults
    for key in ("ENABLE_PDF_PAGE_ROUTER", "PDF_TEXT_RATIO_THRESHOLD", "PDF_SMOLVLM_MAX_NEW_TOKENS"):
        os.environ.pop(key, None)
    if overrides:
        os.environ.update(overrides)
    try:
        import config
        importlib.reload(config)
        return config.settings
    finally:
        os.environ.clear()
        os.environ.update(env_backup)
        importlib.reload(config)


class TestV5ConfigDefaults:
    def test_enable_pdf_page_router_default_true(self):
        s = _reload_settings()
        assert s.enable_pdf_page_router is True

    def test_pdf_text_ratio_threshold_default(self):
        s = _reload_settings()
        assert s.pdf_text_ratio_threshold == pytest.approx(0.05)

    def test_pdf_smolvlm_max_new_tokens_default(self):
        s = _reload_settings()
        assert s.pdf_smolvlm_max_new_tokens == 200


class TestV5ConfigOverrides:
    def test_enable_pdf_page_router_env_false(self):
        # Explicit env var can still disable the router (rollback path)
        s = _reload_settings({"ENABLE_PDF_PAGE_ROUTER": "false"})
        assert s.enable_pdf_page_router is False

    def test_enable_pdf_page_router_env_case_insensitive(self):
        s = _reload_settings({"ENABLE_PDF_PAGE_ROUTER": "True"})
        assert s.enable_pdf_page_router is True

    def test_pdf_text_ratio_threshold_override(self):
        s = _reload_settings({"PDF_TEXT_RATIO_THRESHOLD": "0.1"})
        assert s.pdf_text_ratio_threshold == pytest.approx(0.1)

    def test_pdf_smolvlm_max_new_tokens_override(self):
        s = _reload_settings({"PDF_SMOLVLM_MAX_NEW_TOKENS": "512"})
        assert s.pdf_smolvlm_max_new_tokens == 512
