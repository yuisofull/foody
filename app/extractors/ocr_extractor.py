from __future__ import annotations

from app.extractors.base import MenuExtractor
from app.models.menu import MenuItem
from app.providers.base import MenuProvider


class OCRExtractor(MenuExtractor):
    """
    Menu extractor that uses Optical Character Recognition (OCR).

    This is a stub implementation. A full implementation would download
    menu images, apply an OCR engine (e.g. Tesseract or a cloud OCR API),
    and parse the resulting text into structured menu items.
    """

    @property
    def name(self) -> str:
        return "OCR"

    async def extract(self, menu_url: str, provider: MenuProvider) -> list[MenuItem]:
        # TODO: Implement OCR-based extraction using an OCR library or API.
        return []
