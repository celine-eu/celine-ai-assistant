"""Doubles for the three platform clients the skills reach through `celine-sdk`.

The cut is at the **client object**, not at HTTP. That is the cheaper of the two, and
what it buys is that these tests describe how the skills read a response — which fields
they reach for, what they do when one is missing. What it does not buy is any warning
when the SDK changes shape underneath us: an SDK bump can leave every test here green
and every call in production broken.

`.agents/knowledge/faking-the-sdk-boundary.md` records what to do about that.
"""

from __future__ import annotations

from typing import Any


class Item:
    """A row, as the SDK hands one over."""

    def __init__(self, **fields: Any) -> None:
        self._fields = fields

    def to_dict(self) -> dict[str, Any]:
        return dict(self._fields)


class Page:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = items or []
        self.count = len(self.items)


class Attr:
    """An object whose attributes the skills read with `getattr(..., None)`."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class FakeParticipants:
    def __init__(self, *, profile=None, assets=None, values=None, raises=None):
        self._profile = profile if profile is not None else Attr()
        self._assets = assets if assets is not None else Page()
        self._values: dict[str, Page] = values or {}
        self._raises = raises or {}
        self.calls: list[tuple[str, dict]] = []

    async def profile(self, participant_id: str):
        self.calls.append(("profile", {"participant_id": participant_id}))
        if "profile" in self._raises:
            raise self._raises["profile"]
        return self._profile

    async def assets(self, participant_id: str):
        self.calls.append(("assets", {"participant_id": participant_id}))
        if "assets" in self._raises:
            raise self._raises["assets"]
        return self._assets

    async def fetch_values(self, *, participant_id: str, fetcher_id: str, payload: dict):
        self.calls.append(
            ("fetch_values", {"fetcher_id": fetcher_id, "payload": payload})
        )
        if fetcher_id in self._raises:
            raise self._raises[fetcher_id]
        return self._values.get(fetcher_id, Page())


class FakeCommunities:
    def __init__(self, *, values=None, raises=None):
        self._values: dict[str, Page] = values or {}
        self._raises = raises or {}
        self.calls: list[tuple[str, dict]] = []

    async def fetch_values(self, *, community_id: str, fetcher_id: str, payload: dict):
        self.calls.append(
            (
                "fetch_values",
                {"community_id": community_id, "fetcher_id": fetcher_id, "payload": payload},
            )
        )
        if fetcher_id in self._raises:
            raise self._raises[fetcher_id]
        return self._values.get(fetcher_id, Page())


class FakeDTClient:
    """Stands in for `celine.sdk.dt.DTClient`."""

    def __init__(self, *, participants=None, communities=None, **_ignored):
        self.participants = participants or FakeParticipants()
        self.communities = communities or FakeCommunities()


def member_of(community_key: str | None, name: str = "Folgaria REC") -> Attr:
    """A participant profile with (or without) a community membership."""
    if community_key is None:
        return Attr(membership=None)
    return Attr(membership=Attr(community=Attr(key=community_key, name=name)))


def with_sensors(*sensor_ids: str) -> Page:
    return Page([Attr(sensor_id=s, asset_type="meter", name=f"Meter {s}") for s in sensor_ids])


def install_dt(monkeypatch, module, client: FakeDTClient) -> None:
    """Replace the `DTClient` name a skill module imported with one that returns `client`."""
    monkeypatch.setattr(module, "DTClient", lambda **kwargs: client)
