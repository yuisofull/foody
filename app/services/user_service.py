from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import get_settings
from app.models.user import GoalType, MacroSplits, UserProfile


_GOAL_DEFAULTS: dict[GoalType, dict] = {
    GoalType.weight_loss: {
        "cal_target": 1600.0,
        "macro_splits": MacroSplits(protein=0.35, carbs=0.35, fat=0.30),
    },
    GoalType.muscle_gain: {
        "cal_target": 2800.0,
        "macro_splits": MacroSplits(protein=0.35, carbs=0.45, fat=0.20),
    },
    GoalType.maintenance: {
        "cal_target": 2000.0,
        "macro_splits": MacroSplits(protein=0.30, carbs=0.40, fat=0.30),
    },
    GoalType.general_health: {
        "cal_target": 2000.0,
        "macro_splits": MacroSplits(protein=0.25, carbs=0.50, fat=0.25),
    },
}


class UserService:
    """
    Service for managing user preference profiles.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        settings = get_settings()
        self._storage_path = Path(storage_path or settings.user_profile_storage_path)

    def analyze_user_preference_profile(self, profile: UserProfile) -> UserProfile:
        """
        AnalyzeUserPreferenceProfile(profile) -> enriched profile

        Fills in sensible defaults for calorie target and macro splits based on
        the user's goal_type when those values have not been explicitly set by
        the user.

        Args:
            profile: The raw user profile.

        Returns:
            A UserProfile with goal-appropriate defaults applied.
        """
        defaults = _GOAL_DEFAULTS.get(profile.goal_type, _GOAL_DEFAULTS[GoalType.general_health])

        # Only apply defaults when the user has not customised the values
        cal_target = profile.cal_target
        macro_splits = profile.macro_splits

        if cal_target == 2000.0 and profile.goal_type != GoalType.maintenance:
            cal_target = defaults["cal_target"]

        default_macros = defaults["macro_splits"]
        if macro_splits == MacroSplits(protein=0.3, carbs=0.4, fat=0.3):
            macro_splits = default_macros

        return profile.model_copy(
            update={"cal_target": cal_target, "macro_splits": macro_splits}
        )

    def store_user_profile(self, profile: UserProfile) -> None:
        """
        StoreUserProfile: persist the user profile to disk.

        Args:
            profile: The UserProfile to save.
        """
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        profiles: dict[str, dict] = {}
        if self._storage_path.exists():
            try:
                profiles = json.loads(self._storage_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                profiles = {}

        profiles[profile.user_id] = profile.model_dump(mode="json")
        self._storage_path.write_text(
            json.dumps(profiles, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_user_profile(self, user_id: str) -> UserProfile | None:
        """
        Load a stored user profile by user_id.

        Returns None if not found.
        """
        if not self._storage_path.exists():
            return None
        try:
            profiles = json.loads(self._storage_path.read_text(encoding="utf-8"))
            data = profiles.get(user_id)
            if data:
                return UserProfile.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError):
            pass
        return None

    def delete_user_profile(self, user_id: str) -> bool:
        """
        Delete a stored user profile.

        Returns True if the profile existed and was deleted, False otherwise.
        """
        if not self._storage_path.exists():
            return False
        try:
            profiles = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if user_id not in profiles:
                return False
            del profiles[user_id]
            self._storage_path.write_text(
                json.dumps(profiles, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except (json.JSONDecodeError, OSError):
            return False
