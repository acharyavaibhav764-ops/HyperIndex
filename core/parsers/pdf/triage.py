from enum import Enum
import fitz  # PyMuPDF


class PageRoute(str, Enum):
    """Routing schema for individual PDF pages."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class PageTriager:
    """Classify a single PDF page into one or more routing categories based on content heuristics (tables, images, text density)."""

    def __init__(self, min_text_chars_for_text_route: int = 200) -> None:
        self.min_text_chars = min_text_chars_for_text_route

    def triage_page(self, page: fitz.Page) -> list[PageRoute]:
        """Classify a single PDF page into one or more routing categories and return list of routes"""
        
        routes: list[PageRoute] = []

        # Table detection
        has_tables = False
        try:
            tabs = page.find_tables()
            has_tables = bool(tabs.tables)
        except Exception:
            has_tables = False

        if has_tables:
            routes.append(PageRoute.TABLE)

        # Image / diagram detection
        has_images = False
        try:
            images = page.get_images()
            text_len = len(page.get_text().strip())
            
            has_images = bool(images) and (text_len < self.min_text_chars) # An image-heavy page is one with at least one image where text is sparse
        except Exception:
            has_images = False

        if has_images:
            routes.append(PageRoute.IMAGE)

        # Default: Pure text via PyMuPDF4LLM
        if not routes:
            routes.append(PageRoute.TEXT)

        return routes

