from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.models.user import GoalType, MacroSplits, UserProfile
from app.services.user_service import UserService


@pytest.fixture
def tmp_storage(tmp_path) -> str:
    return str(tmp_path / "profiles.json")


@pytest.fixture
def user_service(tmp_storage) -> UserService:
    return UserService(storage_path=tmp_storage)


@pytest.fixture
def weight_loss_profile() -> UserProfile:
    return UserProfile(
        user_id="user_001",
        goal_type=GoalType.weight_loss,
        budget_max=15.0,
        restrictions=["gluten_free"],
        cuisine_preferences=["Japanese", "Mediterranean"],
    )


@pytest.fixture
def muscle_gain_profile() -> UserProfile:
    return UserProfile(
        user_id="user_002",
        goal_type=GoalType.muscle_gain,
    )


class TestUserService:
    def test_analyze_weight_loss_sets_calorie_target(self, user_service, weight_loss_profile):
        result = user_service.analyze_user_preference_profile(weight_loss_profile)
        assert result.cal_target == 1600.0

    def test_analyze_muscle_gain_sets_calorie_target(self, user_service, muscle_gain_profile):
        result = user_service.analyze_user_preference_profile(muscle_gain_profile)
        assert result.cal_target == 2800.0

    def test_analyze_muscle_gain_sets_macro_splits(self, user_service, muscle_gain_profile):
        result = user_service.analyze_user_preference_profile(muscle_gain_profile)
        assert result.macro_splits.protein == 0.35
        assert result.macro_splits.carbs == 0.45

    def test_analyze_preserves_custom_calorie_target(self, user_service):
        profile = UserProfile(
            user_id="user_custom",
            goal_type=GoalType.weight_loss,
            cal_target=1400.0,
        )
        result = user_service.analyze_user_preference_profile(profile)
        # Custom target should not be overwritten
        assert result.cal_target == 1400.0

    def test_analyze_preserves_custom_macro_splits(self, user_service):
        custom_macros = MacroSplits(protein=0.4, carbs=0.3, fat=0.3)
        profile = UserProfile(
            user_id="user_macros",
            goal_type=GoalType.muscle_gain,
            macro_splits=custom_macros,
        )
        result = user_service.analyze_user_preference_profile(profile)
        assert result.macro_splits == custom_macros

    def test_store_and_retrieve_profile(self, user_service, weight_loss_profile):
        user_service.store_user_profile(weight_loss_profile)
        retrieved = user_service.get_user_profile("user_001")
        assert retrieved is not None
        assert retrieved.user_id == "user_001"
        assert retrieved.goal_type == GoalType.weight_loss
        assert retrieved.budget_max == 15.0

    def test_get_profile_not_found_returns_none(self, user_service):
        result = user_service.get_user_profile("nonexistent_user")
        assert result is None

    def test_store_overwrites_existing(self, user_service):
        profile_v1 = UserProfile(user_id="user_001", goal_type=GoalType.weight_loss)
        profile_v2 = UserProfile(user_id="user_001", goal_type=GoalType.muscle_gain)

        user_service.store_user_profile(profile_v1)
        user_service.store_user_profile(profile_v2)

        retrieved = user_service.get_user_profile("user_001")
        assert retrieved is not None
        assert retrieved.goal_type == GoalType.muscle_gain

    def test_store_multiple_profiles(self, user_service, weight_loss_profile, muscle_gain_profile):
        user_service.store_user_profile(weight_loss_profile)
        user_service.store_user_profile(muscle_gain_profile)

        r1 = user_service.get_user_profile("user_001")
        r2 = user_service.get_user_profile("user_002")

        assert r1 is not None and r1.goal_type == GoalType.weight_loss
        assert r2 is not None and r2.goal_type == GoalType.muscle_gain

    def test_delete_profile_returns_true(self, user_service, weight_loss_profile):
        user_service.store_user_profile(weight_loss_profile)
        result = user_service.delete_user_profile("user_001")
        assert result is True
        assert user_service.get_user_profile("user_001") is None

    def test_delete_nonexistent_returns_false(self, user_service):
        result = user_service.delete_user_profile("ghost_user")
        assert result is False
