from __future__ import annotations

import pytest

from app.models.menu import MenuItem
from app.models.nutrition import NutritionConfidence, NutritionEstimate
from app.models.user import GoalType, MacroSplits, UserProfile
from app.services.ranking_service import RankingService


@pytest.fixture
def ranking_service() -> RankingService:
    return RankingService()


@pytest.fixture
def base_profile() -> UserProfile:
    return UserProfile(
        user_id="u1",
        goal_type=GoalType.general_health,
        cal_target=2000.0,
        budget_max=20.0,
    )


@pytest.fixture
def items() -> list[MenuItem]:
    return [
        MenuItem(id="i1", name="Grilled Chicken", price=15.0, description="Lean protein", category="Mains", tags=["gluten-free"]),
        MenuItem(id="i2", name="Beef Burger", price=18.0, description="Juicy beef patty", category="Burgers", tags=[]),
        MenuItem(id="i3", name="Veggie Wrap", price=12.0, description="Fresh vegetables", category="Wraps", tags=["vegan", "vegetarian"]),
        MenuItem(id="i4", name="Chocolate Cake", price=8.0, description="Rich chocolate", category="Desserts", tags=[]),
        MenuItem(id="i5", name="Nut Brownie", price=5.0, description="Brownie with nuts", category="Desserts", tags=["nuts"]),
    ]


@pytest.fixture
def nutrition_map() -> dict[str, NutritionEstimate]:
    return {
        "i1": NutritionEstimate(calories=400, protein=45, carbs=20, fat=10, confidence=NutritionConfidence.estimated),
        "i2": NutritionEstimate(calories=700, protein=30, carbs=55, fat=35, confidence=NutritionConfidence.estimated),
        "i3": NutritionEstimate(calories=350, protein=12, carbs=55, fat=8, confidence=NutritionConfidence.estimated),
        "i4": NutritionEstimate(calories=500, protein=5, carbs=75, fat=22, confidence=NutritionConfidence.estimated),
        "i5": NutritionEstimate(calories=300, protein=4, carbs=40, fat=15, confidence=NutritionConfidence.estimated),
    }


class TestRankingService:
    def test_returns_top_n(self, ranking_service, base_profile, items, nutrition_map):
        result = ranking_service.rank_top_menu(base_profile, items, n=3, nutrition_map=nutrition_map)
        assert len(result) == 3

    def test_returns_all_when_n_greater_than_items(self, ranking_service, base_profile, items):
        result = ranking_service.rank_top_menu(base_profile, items, n=100)
        assert len(result) == len(items)

    def test_sorted_by_score_descending(self, ranking_service, base_profile, items, nutrition_map):
        result = ranking_service.rank_top_menu(base_profile, items, n=5, nutrition_map=nutrition_map)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_disliked_item_excluded(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            budget_max=20.0,
            disliked_items=["i2"],
        )
        result = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)
        item_ids = [r.item.id for r in result]
        # i2 should be excluded (score=0) or at the bottom
        if "i2" in item_ids:
            # If present, it must be at the end with score 0
            beef_entry = next(r for r in result if r.item.id == "i2")
            assert beef_entry.score == 0.0

    def test_nut_allergy_excludes_nut_item(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            restrictions=["nut_allergy"],
        )
        result = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)
        # i5 (Nut Brownie with "nuts" tag) should score 0
        nut_brownie = next((r for r in result if r.item.id == "i5"), None)
        if nut_brownie:
            assert nut_brownie.score == 0.0

    def test_vegan_restriction(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            restrictions=["vegan"],
        )
        result = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)
        # Only i3 (Veggie Wrap tagged vegan) should have positive score
        for r in result:
            if r.item.id != "i3":
                assert r.score == 0.0

    def test_over_budget_penalised(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            budget_max=10.0,
        )
        result = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)
        # Items priced over $10 should be penalised vs items under $10
        cheap_items = [r for r in result if r.item.price is not None and r.item.price <= 10.0]
        expensive_items = [r for r in result if r.item.price is not None and r.item.price > 10.0]
        if cheap_items and expensive_items:
            max_expensive = max(r.score for r in expensive_items)
            max_cheap = max(r.score for r in cheap_items)
            # Cheap items should generally outscore expensive ones (all else equal)
            assert max_cheap >= max_expensive

    def test_liked_item_gets_bonus(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            budget_max=20.0,
            liked_items=["i4"],
        )
        result_liked = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)

        profile_no_like = UserProfile(
            user_id="u1",
            goal_type=GoalType.general_health,
            cal_target=2000.0,
            budget_max=20.0,
        )
        result_no_like = ranking_service.rank_top_menu(profile_no_like, items, n=5, nutrition_map=nutrition_map)

        cake_liked = next(r for r in result_liked if r.item.id == "i4")
        cake_no_like = next(r for r in result_no_like if r.item.id == "i4")
        assert cake_liked.score > cake_no_like.score

    def test_muscle_gain_rewards_protein(self, ranking_service, items, nutrition_map):
        profile = UserProfile(
            user_id="u1",
            goal_type=GoalType.muscle_gain,
            cal_target=2800.0,
            budget_max=25.0,
        )
        result = ranking_service.rank_top_menu(profile, items, n=5, nutrition_map=nutrition_map)
        # Grilled Chicken (i1, 45g protein) should outscore Chocolate Cake (i4, 5g protein)
        chicken = next(r for r in result if r.item.id == "i1")
        cake = next(r for r in result if r.item.id == "i4")
        assert chicken.score > cake.score

    def test_empty_items_returns_empty(self, ranking_service, base_profile):
        result = ranking_service.rank_top_menu(base_profile, [], n=5)
        assert result == []

    def test_passes_restrictions_no_restrictions(self, ranking_service):
        item = MenuItem(id="x", name="Anything", tags=["nuts"])
        assert ranking_service._passes_restrictions(item, []) is True

    def test_passes_restrictions_nut_allergy_excluded(self, ranking_service):
        item = MenuItem(id="x", name="Nut Bar", tags=["nuts"])
        assert ranking_service._passes_restrictions(item, ["nut_allergy"]) is False

    def test_passes_restrictions_vegan_required(self, ranking_service):
        vegan_item = MenuItem(id="x", name="Salad", tags=["vegan"])
        non_vegan_item = MenuItem(id="y", name="Steak", tags=[])
        assert ranking_service._passes_restrictions(vegan_item, ["vegan"]) is True
        assert ranking_service._passes_restrictions(non_vegan_item, ["vegan"]) is False
