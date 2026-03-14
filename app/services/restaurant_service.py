from __future__ import annotations

import logging
import httpx

from app.cache.restaurant_cache import RestaurantCache
from app.config import get_settings
from app.models.restaurant import Location, Restaurant


class RestaurantService:
    """
    Service for discovering nearby restaurants.

    Uses the Google Places API (Nearby Search) when an API key is configured.
    Falls back to an empty list if no API key is set.
    """

    PLACES_NEARBY_URL = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    )
    PLACES_NEARBY_NEW_URL = "https://places.googleapis.com/v1/places:searchNearby"
    PLACES_FIELD_MASK = (
        "places.id,places.displayName,places.formattedAddress,places.location,"
        "places.types,places.rating,places.internationalPhoneNumber,places.websiteUri"
    )

    _logger = logging.getLogger(__name__)

    def __init__(self, cache: RestaurantCache | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.google_places_api_key
        self._cache = cache or RestaurantCache(
            maxsize=settings.restaurant_cache_maxsize,
            ttl=settings.restaurant_cache_ttl,
        )

    async def get_nearby_restaurants(
        self,
        location: Location,
        radius: float,
    ) -> list[Restaurant]:
        """
        GetRestaurantNearby(location, radius) -> []restaurants

        Args:
            location: The centre point for the search.
            radius: Search radius in metres (max 50 000 for Google Places).

        Returns:
            A list of nearby Restaurant objects.
        """
        cached = self._cache.get(location, radius)
        if cached is not None:
            return cached

        restaurants = await self._fetch_from_google(location, radius)
        self._cache.set(location, radius, restaurants)
        return restaurants

    async def _fetch_from_google(
        self,
        location: Location,
        radius: float,
    ) -> list[Restaurant]:
        if not self._api_key:
            return []

        # Prefer Places API (New). Fall back to legacy API if unavailable.
        new_api_results = await self._fetch_from_google_new(location, radius)
        if new_api_results is not None:
            return new_api_results

        return await self._fetch_from_google_legacy(location, radius)

    async def _fetch_from_google_new(
        self,
        location: Location,
        radius: float,
    ) -> list[Restaurant] | None:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": self.PLACES_FIELD_MASK,
        }
        payload = {
            "includedTypes": ["restaurant"],
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": location.lat,
                        "longitude": location.lng,
                    },
                    "radius": float(radius),
                }
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.PLACES_NEARBY_NEW_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            self._logger.warning("Places API (New) request failed", exc_info=True)
            return None

        places = data.get("places")
        if places is None:
            error_message = data.get("error", {}).get("message") if isinstance(data, dict) else None
            self._logger.warning(
                "Places API (New) unavailable or denied; falling back to legacy API. error=%s",
                error_message,
            )
            return None

        restaurants: list[Restaurant] = []
        for place in places:
            restaurant = self._parse_place_new(place)
            if restaurant:
                restaurants.append(restaurant)
        return restaurants

    async def _fetch_from_google_legacy(
        self,
        location: Location,
        radius: float,
    ) -> list[Restaurant]:

        params = {
            "location": f"{location.lat},{location.lng}",
            "radius": str(int(radius)),
            "type": "restaurant",
            "key": self._api_key,
        }
        restaurants: list[Restaurant] = []
        next_page_token: str | None = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                if next_page_token:
                    params["pagetoken"] = next_page_token
                try:
                    response = await client.get(self.PLACES_NEARBY_URL, params=params)
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    break

                status = data.get("status")
                if status not in {"OK", "ZERO_RESULTS"}:
                    self._logger.warning(
                        "Legacy Places API denied or failed. status=%s, message=%s",
                        status,
                        data.get("error_message"),
                    )
                    break

                for place in data.get("results", []):
                    restaurant = self._parse_place(place)
                    if restaurant:
                        restaurants.append(restaurant)

                next_page_token = data.get("next_page_token")
                if not next_page_token:
                    break

        return restaurants

    def _parse_place_new(self, place: dict) -> Restaurant | None:
        place_id = place.get("id")
        name = place.get("displayName", {}).get("text")
        if not place_id or not name:
            return None

        location = place.get("location", {})
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is None or lng is None:
            return None

        return Restaurant(
            id=place_id,
            name=name,
            address=place.get("formattedAddress", ""),
            location=Location(lat=lat, lng=lng),
            cuisine_types=place.get("types", []),
            rating=place.get("rating"),
            phone=place.get("internationalPhoneNumber"),
            website=place.get("websiteUri"),
        )

    def _parse_place(self, place: dict) -> Restaurant | None:
        place_id = place.get("place_id")
        name = place.get("name")
        if not place_id or not name:
            return None

        geometry = place.get("geometry", {}).get("location", {})
        lat = geometry.get("lat")
        lng = geometry.get("lng")
        if lat is None or lng is None:
            return None

        return Restaurant(
            id=place_id,
            name=name,
            address=place.get("vicinity", ""),
            location=Location(lat=lat, lng=lng),
            cuisine_types=place.get("types", []),
            rating=place.get("rating"),
            phone=None,
            website=None,
        )
