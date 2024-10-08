Exception Handling
==================

There are two key mechanisms to capture exceptions in the graph: 
one is to capture an exception on a specific node, the other is
to create the equivalent of a ``try`` ``catch`` block which will
capture the exceptions of the nodes included in a graph.

exception_time_series
---------------------

The single node approach will effectively wrap the evaluation function
with a try/catch block and then convert the error into a ``NodeError``
data structure. This contains information such as the error message, 
the node details (signature) and the information about why the node was
activated. This can be configured to include additional meta-data such
as the call graph including some details of the values.

The single node approach behaves slightly differently with map_
then it does with ordinary nodes in that the errors are captured
on a branch-by-branch basis (a branch is an instance of the mapped
node / graph for a single key). The error returned is a TSD where the
key is the map key and the value is the standard error stream.

Here is an example of capturing an exception:

```python
from hgraph import graph, exception_time_series, const, debug_print


@graph
def capture_an_exception():
    a = const(1.0)
    b = const(0.0)
    c = a / b
    e = exception_time_series(c)
    debug_print("a / b", c)
    debug_print("exception", e)
```
```
>> [1970-01-01 00:00:00.000534][1970-01-01 00:00:00.000001] exception: div_(lhs: TS[float], rhs: TS[float]) -> TS[float]
>> NodeError: float division by zero
>> Stack trace:
>> Traceback (most recent call last):
>>  File "/Users/hhenson/PycharmProjects/hgraph/src/hgraph/_impl/_runtime/_node.py", line 166, in eval
>>    out = self.eval_fn(**self._kwargs)
>>          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
>>  File "/Users/hhenson/PycharmProjects/hgraph/src/hgraph/nodes/_math.py", line 36, in div_
>>    return lhs.value / rhs.value
>>           ~~~~~~~~~~^~~~~~~~~~~
>> ZeroDivisionError: float division by zero
>> Activation Back Trace:
>> div_(*lhs*, *rhs*)
>> lhs:
>>   const(value, tp, delay, _clock)
>> 
>> rhs:
>>   const(value, tp, delay, _clock)
```
In this example, we capture the exception generated by the div_ operator.
Here it is the divide by zero we are catching.

Note the ``*``'s wrapping the input names. This indicates that the argument was
modified in this evaluation cycle. It is helpful to know which inputs caused
the node to be evaluated.

The output can be adjusted to describe more or less information. By default,
only one level of traceback is captured and no values. It is possible to adjust
these parameters when requesting the the exception output.

For example:

```python
from hgraph import graph, const, exception_time_series, debug_print

@graph
def capture_an_exception():
    a = const(1.0) + const(2.0)
    b = const(0.0)
    c = a / b
    e = exception_time_series(c, trace_back_depth = 2, capture_values = True)
    debug_print("a / b", c)
    debug_print("exception", e)
```

try_except
----------

The ``try_except`` function effectively wraps a graph into a ``try`` \ ``except`` block.
The return of the function is a TSB with a schema containing 'exception' and 'out' where ``exception``
is a time-series of ``ErrorNode`` (in the same way as ``exception_time_series``). The ``out`` is the time-series
type of the wrapped graph.

If ``try_except`` is given a node, it will effectively delegate to ``exception_time_series``, so you can use
this for all use-cases, the key difference being how the output is returned.

Here is an example using this:

```python
from hgraph import graph, TS, try_except, const, debug_print, run_graph

@graph
def a_graph(lhs: TS[float], rhs: TS[float]) -> TS[float]:
    return lhs / rhs


@graph
def capture_an_exception():
    result = try_except(a_graph, const(1.0), const(0.0))
    debug_print("(1.0 + 2.0) / 0.0", result.out)
    debug_print("exception", result.exception)


run_graph(capture_an_exception)
```
