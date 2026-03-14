from __future__ import annotations

from app.models.menu import MenuItem
from app.models.nutrition import NutritionEstimate
from app.models.user import UserProfile


class RankedItem:
    """A menu item paired with its computed relevance score."""

    def __init__(self, item: MenuItem, score: float, nutrition: NutritionEstimate | None = None) -> None:
        self.item = item
        self.score = score
        self.nutrition = nutrition


class RankingService:
    """
    Service for ranking menu items against a user's preference profile.
    """

    def rank_top_menu(
        self,
        profile: UserProfile,
        items: list[MenuItem],
        n: int,
        nutrition_map: dict[str, NutritionEstimate] | None = None,
    ) -> list[RankedItem]:
        """
        RankingTopMenu(user_profile, []items, N) -> top N items

        Scores each item according to:
        1. Dietary restriction compliance (hard filter – excluded items score 0).
        2. Budget compliance (penalty for items exceeding budget).
        3. Calorie proximity (how close the item's calories are to 1/3 of daily target).
        4. Protein density (bonus for high-protein items when goal is muscle_gain).
        5. User preference history (liked/disliked items).

        Args:
            profile: The user's preference profile.
            items: Candidate menu items.
            n: Number of top items to return.
            nutrition_map: Optional mapping of item.id -> NutritionEstimate.

        Returns:
            Up to N RankedItem objects sorted by score descending.
        """
        nutrition_map = nutrition_map or {}
        ranked: list[RankedItem] = []

        for item in items:
            nutrition = nutrition_map.get(item.id)
            score = self._score_item(profile, item, nutrition)
            ranked.append(RankedItem(item=item, score=score, nutrition=nutrition))

        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked[:n]

    def _score_item(
        self,
        profile: UserProfile,
        item: MenuItem,
        nutrition: NutritionEstimate | None,
    ) -> float:
        score = 100.0

        # Hard exclusion: disliked items
        if item.id in profile.disliked_items:
            return 0.0

        # Dietary restriction check
        if not self._passes_restrictions(item, profile.restrictions):
            return 0.0

        # Bonus for previously liked items
        if item.id in profile.liked_items:
            score += 20.0

        # Budget compliance
        if profile.budget_max is not None and item.price is not None:
            if item.price > profile.budget_max:
                score -= 30.0
            else:
                # Small bonus for good value (price well under budget)
                remaining_fraction = (profile.budget_max - item.price) / profile.budget_max
                score += remaining_fraction * 5.0

        # Nutrition scoring
        if nutrition and nutrition.calories is not None:
            meal_cal_target = profile.cal_target / 3.0
            cal_diff_pct = abs(nutrition.calories - meal_cal_target) / meal_cal_target
            # Penalise items that are far from the per-meal calorie target
            score -= min(cal_diff_pct * 20.0, 30.0)

        if nutrition and nutrition.protein is not None:
            from app.models.user import GoalType

            if profile.goal_type == GoalType.muscle_gain:
                # Reward protein-dense items
                score += min(nutrition.protein / 5.0, 20.0)
            elif profile.goal_type == GoalType.weight_loss:
                # Penalise high-calorie, low-protein items
                if nutrition.calories and nutrition.calories > 0:
                    protein_ratio = nutrition.protein * 4 / nutrition.calories
                    score += protein_ratio * 10.0

        # Tag-based restriction bonuses
        tag_set = {t.lower() for t in item.tags}
        if "vegan" in profile.restrictions and "vegan" in tag_set:
            score += 5.0
        if "vegetarian" in profile.restrictions and "vegetarian" in tag_set:
            score += 5.0

        return max(score, 0.0)

    @staticmethod
    def _passes_restrictions(item: MenuItem, restrictions: list[str]) -> bool:
        if not restrictions:
            return True

        tag_set = {t.lower() for t in item.tags}

        restriction_tag_map: dict[str, list[str]] = {
            "vegan": ["vegan"],
            "vegetarian": ["vegetarian", "vegan"],
            "halal": ["halal"],
            "kosher": ["kosher"],
            "gluten_free": ["gluten-free", "gluten free"],
            "nut_allergy": [],  # Handled via exclusion tags below
            "dairy_free": ["dairy-free", "dairy free"],
        }

        exclusion_map: dict[str, list[str]] = {
            "nut_allergy": ["nuts", "peanuts", "tree nuts", "contains nuts"],
        }

        for restriction in restrictions:
            restriction_lower = restriction.lower()

            # Check required tags (item must have at least one)
            required = restriction_tag_map.get(restriction_lower)
            if required is not None and required:
                if not tag_set.intersection(required):
                    return False

            # Check exclusion tags (item must NOT have any)
            excluded = exclusion_map.get(restriction_lower, [])
            if tag_set.intersection(excluded):
                return False

        return True
