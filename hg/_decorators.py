__all__ = (
    "compute_node", "sink_node", "graph", "service", "service_adaptor", "register_service", "generator")

from functools import partial
from typing import TypeVar, Callable, Type, Sequence, TYPE_CHECKING


if TYPE_CHECKING:
    from hg._wiring._wiring import WiringNodeClass
    from hg._wiring._wiring_node_signature import WiringNodeType


def compute_node(fn=None, /, cpp_impl=None, ticked: Sequence[str] = None, valid: Sequence[str] = None):
    """
    Used to define a python function to be a compute-node. A compute-node is the worker unit in the graph and
    will be called each time of the inputs to the compute node ticks.
    A compute-node requires inputs and outputs.
    """
    from hg._wiring._wiring_node_signature import WiringNodeType
    return _node_decorator(WiringNodeType.COMPUTE_NODE, fn, cpp_impl, ticked, valid)


def pull_source_node(cpp_impl):
    """
    Used to indicate the signature for a C++ source node. For Python source nodes use either the
    generator or source_adapter annotations.
    """
    from hg._wiring._wiring import CppWiringNodeClass
    from hg._wiring._wiring_node_signature import WiringNodeType
    return partial(_create_node, WiringNodeType.PULL_SOURCE_NODE, CppWiringNodeClass, cpp_impl)


def push_source_node(cpp_impl):
    """
    Used to indicate the signature for a C++ push source node.
    :param cpp_impl:
    :return:
    """
    from hg._wiring._wiring import CppWiringNodeClass
    from hg._wiring._wiring_node_signature import WiringNodeType
    return partial(_create_node, WiringNodeType.PUSH_SOURCE_NODE, CppWiringNodeClass, cpp_impl)


def sink_node(fn = None, /, cpp_impl=None, ticked: Sequence[str] = None, valid: Sequence[str] = None):
    """
    Indicates the function definition represents a sink node. This type of node has no return type.
    Other than that it behaves in much the same way as compute node.
    """
    from hg._wiring._wiring_node_signature import WiringNodeType
    return _node_decorator(WiringNodeType.SINK_NODE, fn, cpp_impl, ticked, valid)


def graph(fn):
    """
    Wraps a wiring function. The function can take the form of a function that looks like a compute_node,
    sink_node, souce_node, or a graph with no inputs or outputs. There is generally at least one graph in
    any application. The main graph.
    """
    from hg._wiring._wiring_node_signature import WiringNodeType
    return _node_decorator(WiringNodeType.GRPAH, fn)


def generator(fn):
    """
    Creates a pull source node that supports generating a sequence of ticks that will be fed into the
    graph. The generator wraps a function that is implemented as a python generator which returns a tuple of
    time (or timedelta) and value.

    For example:
    ```Python
    @generator
    def signal() -> TS[bool]:
        while True:
            yield (timedelta(milliseconds=1), True)


    This will cause an infinite sequence of ticks (with value of True) that will tick one a millisecond.
    ```
    """
    from hg._wiring._wiring import PythonGeneratorWiringNodeClass
    from hg._wiring._wiring_node_signature import WiringNodeType
    return _node_decorator(WiringNodeType.PULL_SOURCE_NODE, fn, node_class=PythonGeneratorWiringNodeClass)


def service(fn):
    """
    Decorates a function that describes the service signature. A service requires an implementation
    to describes it behavior.
    A service implementation must be registered by the graph.

    A service definition cannot take any scalar values except for the path.

    for example:

        @service
        def my_service(path: str, ts1: TIME_SERIES, ...) -> OUT_TIME_SERIES:
            pass

    """


SERVICE_DEFINITION = TypeVar('SERVICE_DEFINITION', bound=Callable)


def service_impl(fn=None, /, interface: SERVICE_DEFINITION = None):
    """
    Wraps a service implementation. The service is defined to implement the declared interface.
    """


def register_service(path: str, interface, implementation, **kwargs):
    """
    Binds the implementation of the interface to the path provided. The additional kwargs
    are passed to the implementation. These should be defined on the implementation and are independent of the
    attributes defined in the service.
    :param path:
    :param interface:
    :param implementation:
    :param kwargs:
    :return:
    """


def service_adaptor(interface):
    """
    @service
    def my_interface(ts1: TIME_SERIES, ...) -> OUT_TIME_SERIES:
        pass

    @service_adapter(my_interface)
    class MyAdapter:

        def __init__(self, sender: Sender, ...):
            ''' The sender has a method called send on it that takes a Python object that will enqueue into the out
                shape, use this to send a message'''

        def on_data(ts1: TIME_SERIES, ...):
            ''' Is called each time one of the inputs ticks '''

    Use the register_service method to with the class as the impl value.
    """


def _node_decorator(node_type: "WiringNodeType", signature_fn, cpp_impl=None, ticked: Sequence[str] = None,
                    valid: Sequence[str] = None, node_class: Type["WiringNodeClass"] = None):
    from hg._wiring._wiring import CppWiringNodeClass, GraphWiringNodeClass, PythonWiringNodeClass
    from hg._wiring._wiring_node_signature import WiringNodeType

    kwargs = dict(node_type=node_type,
                  node_class=PythonWiringNodeClass if node_class is None else node_class,
                  ticked=ticked,
                  valid=valid)
    if cpp_impl is not None:
        kwargs['node_class'] = CppWiringNodeClass
        kwargs['impl_fn'] = cpp_impl

    if node_type is WiringNodeType.GRPAH:
        kwargs['node_class'] = GraphWiringNodeClass

    if signature_fn is None:
        return partial(_create_node, **kwargs)
    else:
        return _create_node(signature_fn, **kwargs)


def _create_node(signature_fn, impl_fn=None, node_type: "WiringNodeType"=None, node_class: Type[
    "WiringNodeClass"] = None,
                 ticked: Sequence[str] = None, valid: Sequence[str] = None) -> "WiringNodeClass":
    """
    Create the wiring node using the supplied node_type and impl_fn, for non-cpp types the impl_fn is assumed to be
    the signature fn as well.
    """
    from hg._wiring._wiring_node_signature import extract_signature
    if impl_fn is None:
        impl_fn = signature_fn

    return node_class(extract_signature(signature_fn, node_type), impl_fn)
