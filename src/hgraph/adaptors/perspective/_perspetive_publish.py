from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Type, Callable

from perspective import Table, View

from hgraph import (
    TIME_SERIES_TYPE,
    sink_node,
    graph,
    TSD,
    K,
    AUTO_RESOLVE,
    EvaluationClock,
    STATE,
    HgScalarTypeMetaData,
    HgTupleFixedScalarType,
    HgTimeSeriesTypeMetaData,
    HgTSBTypeMetaData,
    HgTSTypeMetaData,
    HgCompoundScalarType,
    HgDataFrameScalarTypeMetaData,
    push_queue,
    OUT,
    nothing,
    SCHEDULER, operator,
)
from ._perspective import PerspectiveTablesManager


@operator
def _publish_table(
    name: str, ts: TIME_SERIES_TYPE, editable: bool = False, empty_row: bool = False, history: int = None
): ...


@operator
def _receive_table_edits(name: str, type: Type[TIME_SERIES_TYPE]) -> TIME_SERIES_TYPE:
    """
    Receive the edits to a perspective table
    """
    ...


@sink_node(overloads=_publish_table)
def _publish_table_from_tsd(
    name: str,
    ts: TSD[K, TIME_SERIES_TYPE],
    editable: bool = False,
    empty_row: bool = False,
    index_col_name: str = None,
    history: int = None,
    _key: Type[K] = AUTO_RESOLVE,
    _schema: Type[TIME_SERIES_TYPE] = AUTO_RESOLVE,
    ec: EvaluationClock = None,
    state: STATE = None,
    sched: SCHEDULER = None,
):
    """
    Publish a TSD to a perspective table as a collection of rows. The value types supported are a bundle,
    a compound scalar, Frame. Schema defines the columns along with the keys of the TSD which are allowed
    to be tuples in which case the index_col_name is expected to be a comma separated list (no spaces) of the key names
    in order. index_col_name can also include names of columns from the value in case of Frame value type.
    """
    data = None
    if state.multi_row:
        for k in ts.removed_keys():
            state.removed.update(state.key_tracker.pop(k, set()))

        for k, v in ts.modified_items():
            data = [{**state.process_key(k), **row} for row in state.process_row(v)]
            if state.create_index:
                data = [{**i, **state.create_index(i)} for i in data]

            index = state.index
            updated_indices = set(i[index] for i in data)
            state.removed.update(state.key_tracker[k] - updated_indices)
            state.removed -= updated_indices
            state.key_tracker[k] = updated_indices
            state.data += data
    else:
        for k in ts.removed_keys():
            if v := state.key_tracker.pop(k, None):
                state.removed.add(v)

        for k, v in ts.modified_items():
            data = {**state.process_key(k), **state.process_row(v)}
            if state.create_index:
                data = {**data, **state.create_index(data)}

            index = state.index
            if (old_i := state.key_tracker.get(k)) is not None and old_i != data[index]:
                state.removed.add(old_i)
            state.removed.discard(data[index])
            state.key_tracker[k] = data[index]
            state.data.append(data)

    if not sched.is_scheduled and data:
        sched.schedule(timedelta(milliseconds=250), on_wall_clock=True)

    if sched.is_scheduled_now:
        state.manager.update_table(name, state.data, state.removed)
        if history:
            state.manager.update_table(name + "_history", [{"time": ec.evaluation_time, **d} for d in state.data])

        state.data = []
        state.removed = set()


@_publish_table_from_tsd.start
def _publish_table_from_tsd_start(
    name: str,
    index_col_name: str,
    history: int,
    editable: bool,
    empty_row: bool,
    _key: Type[K],
    _schema: Type[TIME_SERIES_TYPE],
    state: STATE,
):
    manager = PerspectiveTablesManager.current()
    state.manager = manager

    if name in manager.get_table_names():
        raise ValueError(f"Table '{name}' already exists")

    index_col_names = [s.strip() for s in index_col_name.split(",")]

    # process the key types
    _key = HgScalarTypeMetaData.parse_type(_key)
    if isinstance(_key, HgTupleFixedScalarType):
        ks_tps = _key.py_type.__args__
        ks = len(ks_tps)
        if index_col_name:
            index = index_col_names[:ks]
        else:
            index = [f"index_{i}" for i in range(ks)]

        index_col_name = "index"

        state.process_key = lambda k: {index[i]: ki for i, ki in enumerate(k)}
        state.create_index = lambda v: {"index": ",".join(str(v[i]) for i in index_col_names)}
        state.key_schema = {"index": str, **{index[i]: ks_tps[i] for i in range(ks)}}

        residual_index_col_names = index_col_names[ks:]
    else:
        if index_col_name is None:
            index = "index"
        else:
            index = index_col_names[0]

        residual_index_col_names = index_col_names[1:]

        if residual_index_col_names:
            state.process_key = lambda k: {"index": str, index: k}
            state.create_index = lambda v: {"index": ",".join(str(v[i]) for i in index_col_names)}
            state.key_schema = state.process_key(_key.py_type)
            index_col_name = "index"
        else:
            state.process_key = lambda k: {index: k}
            state.create_index = None
            state.key_schema = state.process_key(_key.py_type)

    # process the value type
    _schema = HgTimeSeriesTypeMetaData.parse_type(_schema)
    if isinstance(_schema, HgTSBTypeMetaData):
        state.schema = {k: t.scalar_type().py_type for k, t in _schema.bundle_schema_tp.meta_data_schema.items()}
        state.process_row = lambda v: v.delta_value
        state.multi_row = False
    elif isinstance(_schema, HgTSTypeMetaData):
        if isinstance(_schema.value_scalar_tp, HgCompoundScalarType):
            state.schema = {k: v.py_type for k, v in _schema.value_scalar_tp.meta_data_schema.items()}
            state.process_row = lambda v: asdict(v.value)
            state.multi_row = False
        elif isinstance(_schema.value_scalar_tp, HgDataFrameScalarTypeMetaData):
            state.schema = {k: v.py_type for k, v in _schema.value_scalar_tp.schema.meta_data_schema.items()}
            state.process_row = lambda v: v.value.to_dicts()
            state.multi_row = True
        else:
            state.schema = {"value": _schema.value_scalar_tp.py_type}
            state.process_row = lambda v: {"value": v.value}
            state.multi_row = False
    else:
        raise ValueError(f"Unsupported schema type '{_schema}'")

    state.index = (index_col_name or "index")
    table = Table({**state.key_schema, **{k: v for k, v in state.schema.items()}}, index=state.index)

    if empty_row:
        empty_values = [
            "-" if i is str else i.py_type()
            for i in (_key.py_type.__args__ if isinstance(_key, HgTupleFixedScalarType) else [_key])
        ]
        table.update([state.process_key(empty_values)])

    manager.add_table(name, table, editable)
    state.data = []
    state.removed = set()
    state.key_tracker = defaultdict(set) if state.multi_row else {}

    if history:
        history_table = Table(
            {"time": datetime, **state.key_schema, **{k: v for k, v in state.schema.items()}},
            limit=min(history, 4294967295),
        )

        manager.add_table(name + "_history", history_table)


@push_queue(TSD[K, TIME_SERIES_TYPE], overloads=_receive_table_edits)
def _receive_table_edits_tsd(
    sender: Callable,
    name: str,
    type: Type[TSD[K, TIME_SERIES_TYPE]],
    index_col_name: str = None,
    _key: Type[K] = AUTO_RESOLVE,
    _schema: Type[TIME_SERIES_TYPE] = AUTO_RESOLVE,
) -> TSD[K, TIME_SERIES_TYPE]:
    _schema = HgTimeSeriesTypeMetaData.parse_type(_schema)
    if isinstance(_schema, HgTSBTypeMetaData):
        tp_schema = {k: v.scalar_type().py_type for k, v in _schema.bundle_schema_tp.meta_data_schema.items()}
        process_row = lambda row, i: {k: row[k] for k in row if k not in i and k != "index"}
    elif isinstance(_schema, HgTSTypeMetaData):
        if isinstance(_schema.value_scalar_tp, HgCompoundScalarType):
            tp = _schema.value_scalar_tp.py_type
            tp_schema = {k: v.py_type for k, v in _schema.value_scalar_tp.meta_data_schema.items()}
            process_row = lambda row, i: tp(**{k: tp_schema[k](row[k]) for k in row if k not in i and k != "index"})
        else:
            process_row = lambda row, i: row["value"]
    else:
        raise ValueError(f"Unsupported schema type '{_schema}'")

    _key = HgScalarTypeMetaData.parse_type(_key)
    if isinstance(_key, HgTupleFixedScalarType):
        if index_col_name:
            index = [s.strip() for s in index_col_name.split(",")]
        else:
            index = [f"index_{i}" for i in range(len(_key.py_type.__args__))]

        def on_update(data: View):
            # print(data.to_dict())
            data = {tuple(row[i] for i in index): process_row(row, index) for row in data.to_records()}
            sender(data)

    else:
        index = [index_col_name or "index"]

        def on_update(data: View):
            # print(data.to_records())
            data = {row[index[0]]: process_row(row, index) for row in data.to_records()}
            sender(data)

    manager = PerspectiveTablesManager.current()
    manager.subscribe_table_updates(name, on_update)
