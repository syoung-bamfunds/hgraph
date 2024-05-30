from hgraph import graph, TSB, TS_SCHEMA, OUT, TS
from hgraph.nodes import convert


@graph(overloads=convert)
def convert_tsb_to_bool(ts: TSB[TS_SCHEMA], to: type[TS[bool]]) -> TS[bool]:
    return ts.valid

