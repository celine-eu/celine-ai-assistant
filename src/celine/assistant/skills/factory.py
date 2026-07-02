from __future__ import annotations

import logging
from typing import Any

from celine.assistant.settings import Settings

# from .datasets import DatasetSkill  # disabled: dataset-api requires service tokens, not user tokens
from .digital_twin import DigitalTwinSkill
from .documents import DocumentSkill
from .flexibility import FlexibilitySkill
from .rec_registry import RecRegistrySkill
from .registry import SkillRegistry
from .weather import WeatherSkill

log = logging.getLogger(__name__)


def build_skill_registry(
    *,
    user_token: str | None,
    user_id: str,
    settings: Settings,
    history_store: Any,
) -> SkillRegistry:
    registry = SkillRegistry()

    registry.register(DocumentSkill(history_store=history_store, user_id=user_id))

    if user_token and settings.digital_twin_api_url:
        registry.register(
            DigitalTwinSkill(
                dt_base_url=settings.digital_twin_api_url,
                user_token=user_token,
                user_id=user_id,
            )
        )
        registry.register(
            WeatherSkill(
                dt_base_url=settings.digital_twin_api_url,
                user_token=user_token,
                user_id=user_id,
            )
        )
    else:
        if not settings.digital_twin_api_url:
            log.warning(
                "digital_twin_skill_disabled: set DIGITAL_TWIN_API_URL to enable live energy data queries"
            )
        elif not user_token:
            log.warning(
                "digital_twin_skill_disabled: no user token available (unauthenticated request)"
            )

    if user_token and settings.rec_registry_api_url:
        registry.register(
            RecRegistrySkill(
                registry_base_url=settings.rec_registry_api_url,
                user_token=user_token,
            )
        )
    else:
        if not settings.rec_registry_api_url:
            log.warning(
                "rec_registry_skill_disabled: set REC_REGISTRY_API_URL to enable REC membership queries"
            )
        elif not user_token:
            log.warning(
                "rec_registry_skill_disabled: no user token available (unauthenticated request)"
            )

    if user_token and settings.flexibility_api_url and settings.digital_twin_api_url:
        registry.register(
            FlexibilitySkill(
                flexibility_base_url=settings.flexibility_api_url,
                dt_base_url=settings.digital_twin_api_url,
                user_token=user_token,
                user_id=user_id,
            )
        )
    else:
        if not settings.flexibility_api_url:
            log.warning(
                "flexibility_skill_disabled: set FLEXIBILITY_API_URL to enable flexibility suggestions"
            )

    # DatasetSkill disabled — dataset-api requires service-level tokens,
    # not user tokens. Re-enable when a token exchange or service account
    # flow is available.
    #
    # if user_token and settings.datasets_api_url:
    #     registry.register(
    #         DatasetSkill(
    #             datasets_base_url=settings.datasets_api_url,
    #             user_token=user_token,
    #         )
    #     )

    return registry
