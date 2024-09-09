import re
from typing import Union

from frozendict import frozendict
from multimethod import multimethod

from hgraph import Node, Graph, PythonTimeSeriesValueInput, PythonTimeSeriesValueOutput, \
    PythonTimeSeriesReferenceOutput, PythonTimeSeriesReferenceInput, PythonTimeSeriesReference, \
    TimeSeriesList, TimeSeriesDict, TimeSeriesBundle, TimeSeriesSet, TimeSeriesInput, TimeSeriesOutput, \
    PythonNestedNodeImpl, PythonTsdMapNodeImpl, PythonServiceNodeImpl, PythonReduceNodeImpl, PythonSwitchNodeImpl, \
    PythonTryExceptNodeImpl, HgTSBTypeMetaData, PythonPushQueueNodeImpl
from hgraph._impl._runtime._component_node import PythonComponentNodeImpl
from hgraph._impl._runtime._mesh_node import PythonMeshNodeImpl

STR_ID_SYMBOLS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
STR_ID_NUMBERS = [STR_ID_SYMBOLS.find(chr(i)) for i in range(128)]


def base62(i: int) -> str:
    return f"{STR_ID_SYMBOLS[i // 3844]}{STR_ID_SYMBOLS[i // 62 % 62]}{STR_ID_SYMBOLS[i % 62]}"


def str_node_id(id: tuple[int, ...]) -> str:
    return ''.join(base62(i) for i in id)


def node_id_from_str(s: str) -> tuple:
    return tuple(
        STR_ID_NUMBERS[ord(s[i])] * 3844 + STR_ID_NUMBERS[ord(s[i + 1])] * 62 + STR_ID_NUMBERS[ord(s[i + 2])] for i in
        range(0, len(s), 3))


# These are visitors that are used to extract information from the graph objects to display in the inspector

@multimethod
def format_name(value, key="?"):
    return str(key)


@format_name.register
def _(graph: "Graph", key=None) -> str:
    if key:
        return str(key)

    return graph.label or "_"


@format_name.register
def _(node: "Node", key=None) -> str:
    long_name = (
        f"{node.signature.wiring_path_name}.{node.signature.name}"
        f"{(':' + node.signature.label) if node.signature.label else ''}"
    )
    
    if node.graph.parent_node:
        return long_name.replace(node.graph.parent_node.signature.wiring_path_name + ".", "")
    else:
        return long_name


@multimethod
def format_value(value):
    if type(value) in (dict, frozendict, tuple, set, frozenset):
        return f"{len(value)} items"
    else:
        s = str(value)
        if len(s) > 256:
            s = s[:253] + "..."
        return s


@format_value.register
def _(value: Graph):
    return format_name(value)


@format_value.register
def _(value: Node):
    if (out := value.output) is not None:
        return format_value(out)
    else:
        return "-"


@format_value.register
def _(value: PythonPushQueueNodeImpl):
    return f"{value.messages_in_queue} items in the queue"


@format_value.register
def _(value: Union[PythonTimeSeriesValueOutput]):
    # Very specific types here because want to check the _tp attribute to avoid potentially costly .value call
    if value.valid:
        if value._tp in (frozendict, frozenset):
            return f"{len(value.value)} items"
        else:
            s = str(value.value)
            if len(s) > 256:
                s = s[:253] + "..."
            return s
    else:
        return "INVALID"


@format_value.register
def _(value: Union[PythonTimeSeriesValueInput]):
    if value.output is not None:
        return format_value(value.output)
    else:
        return "INVALID"


@format_value.register
def _(value: Union[PythonTimeSeriesReferenceOutput, PythonTimeSeriesReferenceInput]):
    if value.valid:
        ref = value.value
        if ref.valid:
            if not ref.has_peer and ref.items:
                return f"{len(ref.items)} items"
            else:
                return str(ref)
    else:
        return "INVALID"


@format_value.register
def _(value: PythonTimeSeriesReference):
    if value.valid:
        if not value.has_peer and value.items:
            return f"{len(value.items)} items"
        else:
            return str(value)
    else:
        return "INVALID"


@format_value.register
def _(value: Union[TimeSeriesList, TimeSeriesSet, TimeSeriesBundle, TimeSeriesDict]):
    if value.valid:
        return f"{len(value)} items"
    else:
        return "INVALID"


@multimethod
def format_timestamp(value):
    return None


@format_timestamp.register
def _(value: Node):
    return value.graph._schedule[value.node_ndx]


@format_timestamp.register
def _(value: Graph):
    return value.parent_node.last_evaluation_time if value.parent_node else None


@format_timestamp.register
def _(value: Union[TimeSeriesOutput, TimeSeriesInput]):
    if value.valid:
        return value.last_modified_time
    else:
        return None


@multimethod
def enum_items(value):
    yield from ()


@enum_items.register
def _(value: dict):
    yield from value.items()


@enum_items.register
def _(value: frozendict):
    yield from value.items()


@enum_items.register
def _(value: frozenset):
    yield from ((k, k) for k in value)


@enum_items.register
def _(value: set):
    yield from ((k, k) for k in value)


@enum_items.register
def _(value: Union[PythonTimeSeriesReferenceOutput, PythonTimeSeriesReferenceInput]):
    if value.valid:
        ref = value.value
        if ref.valid:
            if not ref.has_peer and ref.items:
                yield from enumerate(ref.items)
    yield from ()


@enum_items.register
def _(value: Union[TimeSeriesList, TimeSeriesBundle, TimeSeriesDict]):
    if value.valid:
        yield from value.items()
    yield from ()


@enum_items.register
def _(value: TimeSeriesSet):
    if value.valid:
        yield from ((k, k) for k in value.values())
    yield from ()


@enum_items.register
def _(value: PythonNestedNodeImpl):
    yield from value.nested_graphs().items()


@enum_items.register
def _(value: Graph):
    yield from enumerate(value.nodes)


@multimethod
def format_type(value):
    return type(value).__name__


@format_type.register
def _(value: Node):
    return value.signature.node_type.name.replace("_NODE", "")


@format_type.register
def _(value: PythonNestedNodeImpl):
    return {
        PythonTsdMapNodeImpl: "MAP",
        PythonMeshNodeImpl: "MESH",
        PythonServiceNodeImpl: "SERVICE",
        PythonReduceNodeImpl: "REDUCE",
        PythonSwitchNodeImpl: "SWITCH",
        PythonTryExceptNodeImpl: "TRY_EXCEPT",
        PythonComponentNodeImpl: "COMPONENT",
    }.get(type(value), "?")


@format_type.register
def _(value: PythonTimeSeriesReference):
    return "REF"

@format_type.register
def _(value: TimeSeriesInput):
    path = []
    while value.parent_input:
        if isinstance(value.parent_input, TimeSeriesBundle):
            path.append(next(k for i, (k, v) in enumerate(value.parent_input._ts_values.items()) if v is value))
        else:
            path.append(0)
        value = value.parent_input

    if not path:
        return "INPUTS"

    tp = value.owning_node.signature.time_series_inputs[path[-1]]
    for i in reversed(path[:-1]):
        if isinstance(tp, HgTSBTypeMetaData):
            tp = tp.bundle_schema_tp.meta_data_schema[i]
        else:
            tp = tp.value_tp

    return str(tp)


@format_type.register
def _(value: TimeSeriesOutput):
    path = []
    while value.parent_output:
        if isinstance(value.parent_output, TimeSeriesBundle):
            path.append(next(k for i, (k, v) in enumerate(value.parent_output._ts_values.items()) if v is value))
        else:
            path.append(0)
        value = value.parent_output

    tp = value.owning_node.signature.time_series_output
    for i in reversed(path):
        if isinstance(tp, HgTSBTypeMetaData):
            tp = tp.bundle_schema_tp.meta_data_schema[i]
        else:
            tp = tp.value_tp

    return re.sub(r"<class '(?:\w+\.)+", r"", str(tp)).replace("'>", "")


@multimethod
def inspect_item(value, key):
    return value[key]


@inspect_item.register
def _(value: PythonNestedNodeImpl, key):
    return value.nested_graphs().get(key)


@inspect_item.register
def _(value: PythonTimeSeriesReference, key):
    return value.items[key]


@inspect_item.register
def _(value: Union[PythonTimeSeriesReferenceInput | PythonTimeSeriesReferenceOutput], key):
    return value.value.items[key]
