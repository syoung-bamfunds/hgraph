from datetime import timedelta

from hg import generator, SCALAR, compute_node, PythonWiringNodeClass, sink_node, graph, GraphWiringNodeClass
from hg._types._ts_type import TS
from hg._wiring._wiring import PythonGeneratorWiringNodeClass
from hg._wiring._wiring_node_signature import WiringNodeType, WiringNodeSignature


def test_generator_node():

    @generator
    def simple_generator(value: SCALAR) -> TS[SCALAR]:
        yield timedelta(), value

    assert type(simple_generator) is PythonGeneratorWiringNodeClass
    signature: WiringNodeSignature = simple_generator.signature
    assert signature.node_type is WiringNodeType.PULL_SOURCE_NODE
    assert signature.name is "simple_generator"
    assert simple_generator.fn is not None


def test_compute_node():

    @compute_node
    def simple_compute_node(ts: TS[int], s1: str = "test") -> TS[str]:
        return f"{s1}: {ts.value}"

    assert type(simple_compute_node) is PythonWiringNodeClass
    signature: WiringNodeSignature = simple_compute_node.signature
    assert signature.node_type is WiringNodeType.COMPUTE_NODE
    assert signature.name is "simple_compute_node"
    assert simple_compute_node.fn is not None


def test_sink_node():

    @sink_node
    def simple_sink_node(ts: TS[int], s1: str = "test"):
        ...

    assert type(simple_sink_node) is PythonWiringNodeClass
    signature: WiringNodeSignature = simple_sink_node.signature
    assert signature.node_type is WiringNodeType.SINK_NODE
    assert signature.name is "simple_sink_node"
    assert simple_sink_node.fn is not None


def test_graph():

    @graph
    def simple_graph():
        ...

    assert type(simple_graph) is GraphWiringNodeClass
    signature: WiringNodeSignature = simple_graph.signature
    assert signature.node_type is WiringNodeType.GRPAH
    assert signature.name is "simple_graph"
    assert simple_graph.fn is not None