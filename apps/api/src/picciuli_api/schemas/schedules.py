"""Bodies of the recurring transaction endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from pydantic import Field, field_validator

from picciuli import ScheduleFrequency, ScheduleMode, TransactionKind
from picciuli.limits import MAX_ID, MAX_SCHEDULE_EVERY

from .base import Date, InputModel, OutputModel, PatchModel, Text
from .periods import PeriodOut
from .transactions import SplitList, SplitOut, TransactionOut, _tag_split

__all__ = [
    "CatchUpIn",
    "CatchUpOut",
    "OccurrenceOut",
    "ScheduleCreate",
    "ScheduleOut",
    "SchedulePost",
    "ScheduleUpdate",
]

Every = Annotated[int, Field(ge=1, le=MAX_SCHEDULE_EVERY)]
DayOfMonth = Annotated[
    int,
    Field(
        ge=1,
        le=31,
        description="Day of the month of monthly and yearly occurrences; 31 "
        "means the last day of every month.",
    ),
]
Occurrences = Annotated[
    int, Field(ge=1, le=MAX_ID, description="Occurrences left, including the next.")
]


class ScheduleOut(OutputModel):
    """A recurring transaction: a template of splits and when it repeats."""

    id: int
    description: str | None
    notes: str | None
    splits: list[SplitOut]
    frequency: ScheduleFrequency
    every: int
    day_of_month: int | None
    next_date: dt.date | None = Field(description="`null` once finished.")
    end: dt.date | None
    remaining: int | None = Field(
        description="Occurrences left including the next; `null` for no limit."
    )
    mode: ScheduleMode
    paused: bool
    last_error: str | None = Field(
        description="Why the last automatic posting failed, if it did."
    )
    kind: TransactionKind
    net_amount: int
    is_finished: bool

    @field_validator("splits", mode="before")
    @classmethod
    def _tag_splits(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [_tag_split(split) for split in value]
        return value


class ScheduleCreate(InputModel):
    """A new recurring transaction. Its splits cannot move shares."""

    start: Date = Field(description="Day of the first occurrence.")
    splits: SplitList
    frequency: ScheduleFrequency = ScheduleFrequency.MONTHLY
    every: Every = 1
    day_of_month: DayOfMonth | None = Field(
        default=None, description="Defaults to the day of `start`."
    )
    end: Date | None = None
    occurrences: Occurrences | None = None
    mode: ScheduleMode = ScheduleMode.AUTO
    description: Text | None = None
    notes: Text | None = None


class ScheduleUpdate(PatchModel):
    """Changes to a recurring transaction; recorded transactions are kept."""

    _not_null = frozenset(
        {"splits", "next_date", "frequency", "every", "mode", "paused"}
    )

    splits: SplitList | None = None
    next_date: Date | None = None
    frequency: ScheduleFrequency | None = None
    every: Every | None = None
    day_of_month: DayOfMonth | None = None
    end: Date | None = None
    occurrences: Occurrences | None = None
    mode: ScheduleMode | None = None
    paused: bool | None = None
    description: Text | None = None
    notes: Text | None = None

    def changes(self) -> dict[str, Any]:
        """Return the explicitly set fields, with splits converted."""
        changes = super().changes()
        if self.splits is not None:
            changes["splits"] = [split.to_model() for split in self.splits]
        return changes


class SchedulePost(PatchModel):
    """Record the next occurrence; the fields change only this transaction."""

    date: Date | None = Field(
        default=None, description="Defaults to the day of the next occurrence."
    )
    splits: SplitList | None = Field(
        default=None,
        description="Default to the template, for example to "
        "record a bill whose amount varies.",
    )
    description: Text | None = None
    notes: Text | None = None

    def changes(self) -> dict[str, Any]:
        """Return the explicitly set fields, with splits converted."""
        changes = super().changes()
        if self.splits is not None:
            changes["splits"] = [split.to_model() for split in self.splits]
        return changes


class OccurrenceOut(OutputModel):
    """A day on which a recurring transaction is (or was) due."""

    schedule_id: int
    date: dt.date


class CatchUpIn(InputModel):
    """The current day of the user, in their own time zone."""

    today: Date


class CatchUpOut(OutputModel):
    """What catching up created, and what waits for confirmation."""

    periods: list[PeriodOut] = Field(description="Monthly periods created.")
    posted: list[TransactionOut] = Field(
        description="Transactions recorded by automatic schedules."
    )
    due: list[OccurrenceOut] = Field(
        description="Occurrences waiting for confirmation, up to today."
    )
    failed: list[ScheduleOut] = Field(
        description="Automatic schedules that could not record an occurrence."
    )
