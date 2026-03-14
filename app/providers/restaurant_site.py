from __future__ import annotations

from app.models.restaurant import Restaurant
from app.providers.base import MenuProvider


class RestaurantSiteProvider(MenuProvider):
    """Returns the restaurant's own website as the menu URL source."""

    @property
    def name(self) -> str:
        return "RestaurantSite"

    async def get_menu_url(self, restaurant: Restaurant) -> str | None:
        return restaurant.website or None
