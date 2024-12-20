from abc import ABC, abstractmethod
from datetime import timedelta, datetime
from typing import Generic, Any

from hgraph._types._scalar_types import SCALAR, BUFF_SIZE, BUFF_SIZE_MIN
from hgraph._types._scalar_value import Array
from hgraph._types._time_series_types import TimeSeriesDeltaValue, TimeSeriesInput, TimeSeriesOutput

__all__ = ("TimeSeriesBuffer", "BUFF", "BUFF_OUT", "TimeSeriesBufferInput",
           "TimeSeriesBufferOutput")

class TimeSeriesBuffer(
    TimeSeriesDeltaValue[Array[SCALAR], SCALAR],
    Generic[SCALAR, BUFF_SIZE, BUFF_SIZE_MIN],
):
    """
    Provides a time-series buffer over stream of scalar values.
    """

    def __init__(self, __type__: SCALAR, __size__: BUFF_SIZE, __min_size__: BUFF_SIZE_MIN):
        self.__type__: SCALAR = __type__
        self.__size__: BUFF_SIZE = __size__
        self.__min_size__: BUFF_SIZE_MIN = __min_size__

    def __class_getitem__(cls, item) -> Any:
        # For now, limit to validation of item
        is_tuple = type(item) is tuple
        if is_tuple:
            if len(item) != 3:
                item = (item[0] if len(item) >= 1 else SCALAR), \
                (item[1] if len(item) == 2 else BUFF_SIZE), \
                (item[1] if len(item) == 2 else BUFF_SIZE_MIN)
        else:
            item = item, BUFF_SIZE, BUFF_SIZE_MIN
        out = super(TimeSeriesBuffer, cls).__class_getitem__(item)
        if item != (SCALAR, BUFF_SIZE, BUFF_SIZE_MIN):
            from hgraph._types._scalar_type_meta_data import HgScalarTypeMetaData

            if HgScalarTypeMetaData.parse_type(item[0]) is None:
                from hgraph import ParseError

                raise ParseError(
                    f"Type '{item[0]}' must be a scalar or a valid TypeVar (bound to a scalar value)"
                )
        return out

    def __len__(self) -> int:
        """
        Returns the length of the buffer if it is of a tick length. Since this only gets called during the wiring
        phase it can only provide the value if the size is set and it has a tick size.
        When called inside of a node this is the actual length of the buffer at the point in time.
        """
        return getattr(self, "__size__", -1)

    @property
    def min_size(self) -> int | timedelta:
        """The minimum size (either as integer when defined as int, or timedelta when defined as timedelta)"""
        return self.__min_size__.SIZE if self.__min_size__.FIXED_SIZE else self.__min_size__.TIME_RANGE

    @property
    @abstractmethod
    def size(self) -> int | timedelta:
        """The size (either as integer when defined as int, or timedelta when defined as timedelta)"""
        return self.__size__.SIZE if self.__size__.FIXED_SIZE else self.__size__.TIME_RANGE

    @property
    @abstractmethod
    def value_times(self) -> tuple[datetime, ...]:
        """
        The times associated to the value array. These are the times when the values were updated.
        """

    @property
    @abstractmethod
    def first_modified_time(self) -> datetime:
        """
        The time the first tick in the buffer was modified.
        """


class TimeSeriesBufferInput(
    TimeSeriesBuffer[SCALAR, BUFF_SIZE, BUFF_SIZE_MIN], TimeSeriesInput, ABC, Generic[SCALAR, BUFF_SIZE, BUFF_SIZE_MIN]
):
    """
    The input of a time series buffer.
    """


class TimeSeriesBufferOutput(
    TimeSeriesBuffer[SCALAR, BUFF_SIZE, BUFF_SIZE_MIN], TimeSeriesOutput, ABC, Generic[SCALAR, BUFF_SIZE, BUFF_SIZE_MIN]
):
    """
    The output of the time series list
    """

    value: TimeSeriesOutput


BUFF = TimeSeriesBufferInput
BUFF_OUT = TimeSeriesBufferOutput
