import re
from asyncio import Future
from collections import deque

from hgraph import Node, PythonNestedNodeImpl, TimeSeriesInput, PythonTimeSeriesReferenceOutput, \
    PythonTimeSeriesReference, PythonTimeSeriesReferenceInput
from hgraph.adaptors.tornado.http_server_adaptor import HttpGetRequest, HttpResponse, HttpRequest
from hgraph.debug._inspector_item_id import InspectorItemId, NodeValueType
from hgraph.debug._inspector_state import InspectorState
from hgraph.debug._inspector_util import enum_items, format_type, format_value, format_timestamp, format_name


def graph_object_from_id(state: InspectorState, item_id: InspectorItemId):
    gi = state.observer.get_graph_info(item_id.graph)
    if gi is None:
        raise ValueError(f"Graph {item_id.graph} not found")

    graph = gi.graph

    value = item_id.find_item_on_graph(graph)
    if value is None:
        raise ValueError(f"Item {item_id} not found")

    return graph, value


def item_iterator(item_id, value):
    if isinstance(value, Node):
        items = []
        if value.input:
            items.append(("INPUTS", value.input, item_id.sub_item("INPUTS", NodeValueType.Inputs)))
        if value.output:
            items.append(("OUTPUT", value.output, item_id.sub_item("OUTPUT", NodeValueType.Output)))
        if isinstance(value, PythonNestedNodeImpl):
            items.append(("GRAPHS", value.nested_graphs(), item_id.sub_item("GRAPHS", NodeValueType.Graphs)))
        if value.scalars:
            items.append(("SCALARS", value.scalars, item_id.sub_item("SCALARS", NodeValueType.Scalars)))
        item_iter = items
    else:
        item_iter = ((k, v, item_id.sub_item(k, v)) for k, v in enum_items(value))

    return item_iter


def inspector_expand_item(state: InspectorState, item_id: InspectorItemId):
    graph, value = graph_object_from_id(state, item_id)

    item_iter = item_iterator(item_id, value)

    data = state.value_data
    items = 0
    for k, v, i in item_iter:
        if i.graph != graph.graph_id:
            gi = state.observer.get_graph_info(i.graph)
            if gi is None:
                continue
            else:
                graph = gi.graph

        data.append(dict(
            id=i.to_str(),
            ord=i.sort_key(),
            X="+",
            name=i.indent(graph) + format_name(v, k),
            type=format_type(v),
            value=format_value(v),
            timestamp=format_timestamp(v)
        ))

        subscribe_item(state, i)
        items += 1

    if item_id.graph != () or item_id.node is not None:
        if items:
            data.append(dict(id=item_id.to_str(), X="-"))
        else:
            data.append(dict(id=item_id.to_str(), X="º"))

    return "", []


def inspector_show_item(state: InspectorState, item_id: InspectorItemId):
    if item_id.node is None:
        if item_id.graph in state.graph_subscriptions:
            return "", []
    elif item_id.value_type is None:
        if item_id.graph + (item_id.node,) in state.node_subscriptions:
            return "", []
    elif subscriptions := state.node_item_subscriptions.get(item_id.graph + (item_id.node,)):
        if item_id in subscriptions:
            return "", []

    graph, value = graph_object_from_id(state, item_id)

    key = item_id.value_path[-1] if item_id.value_path else item_id.value_type.value if item_id.value_type else None

    state.value_data.append(dict(
        id=item_id.to_str(),
        ord=item_id.sort_key(),
        X="+",
        name=item_id.indent(graph) + format_name(value, key),
        type=format_type(value),
        value=format_value(value),
        timestamp=format_timestamp(value)
    ))

    subscribe_item(state, item_id)

    return "", []


def inspector_collapse_item(state, item_id):
    graphs_to_unsubscribe = []
    for k, v in state.graph_subscriptions.items():
        if item_id.is_parent_of(v):
            graphs_to_unsubscribe.append(k)

    nodes_to_unsubscribe = []
    for k, v in state.node_subscriptions.items():
        if item_id.is_parent_of(v):
            nodes_to_unsubscribe.append(k)

    items_to_unsubscribe = []
    if item_id.node is not None:
        subscriptions = state.node_item_subscriptions.get(item_id.graph + (item_id.node,))
        if subscriptions is not None:
            if item_id.value_type is None:  # everything under the node has to go, but not the node itself
                items_to_unsubscribe.extend(subscriptions - {item_id})
            else:
                for sub_item_id in subscriptions:
                    if item_id.is_parent_of(sub_item_id):
                        items_to_unsubscribe.append(sub_item_id)

    for graph_id in graphs_to_unsubscribe:
        i = state.graph_subscriptions.pop(graph_id)
        state.observer.unsubscribe_graph(graph_id)
        state.value_removals.add(i.to_str())

    for node_id in nodes_to_unsubscribe:
        i = state.node_subscriptions.pop(node_id)
        state.observer.unsubscribe_node(node_id)
        state.value_removals.add(i.to_str())
        for sub_item_id in state.node_item_subscriptions.get(node_id, set()):
            state.value_removals.add(sub_item_id.to_str())

    for sub_item_id in items_to_unsubscribe:
        unsubscribe_item(state, sub_item_id)
        state.value_removals.add(sub_item_id.to_str())

    state.value_data.append(dict(id=item_id.to_str(), X="+"))

    return "", []


def inspector_pin_item(state, item_id):
    return "", []


def inspector_follow_ref(state, item_id):
    graph, value = graph_object_from_id(state, item_id)

    if isinstance(value, Node) and value.output:
        value = value.output

    if isinstance(value, TimeSeriesInput):
        if value.output:
            item_id = InspectorItemId.from_object(value.output)
        elif isinstance(value, PythonTimeSeriesReferenceInput):
            if value.valid and value.value.output:
                item_id = InspectorItemId.from_object(value.value.output)
            else:
                raise ValueError(f"Reference input {item_id} has no output and no value")
        else:
            raise ValueError(f"Input {item_id} has no output")
    elif isinstance(value, PythonTimeSeriesReferenceOutput):
        if value.valid and value.value.output:
            item_id = InspectorItemId.from_object(value.value.output)
        else:
            raise ValueError(f"TimeSeriesReference {item_id} references no output")
    elif isinstance(value, PythonTimeSeriesReference):
        if value.valid and value.output:
            item_id = InspectorItemId.from_object(value.output)
        else:
            raise ValueError(f"TimeSeriesReference {item_id} references no output")
    else:
        raise ValueError(f"Item {item_id} is not a reference or bound inputs")

    if item_id is None:
        raise ValueError(f"Referenced item not found")

    commands = [
        ("show", i) for i in item_id.parent_item_ids()
    ] + [
        ("show", item_id)
    ]

    return item_id.to_str(), commands


def inspector_pin_ref(state, item_id):
    return "", []


def inspector_unpin_item(state, item_id):
    return "", []


def inspector_search_item(state, item_id, search_re, depth=0, limit=10):
    graph, value = graph_object_from_id(state, item_id)

    item_iter = item_iterator(item_id, value)

    items = 0
    for k, v, i in item_iter:
        name = format_name(v, k)
        if search_re.search(name) is None:
            if depth:
                found, new_commands = inspector_search_item(state, i, search_re, depth-1)
                if found:
                    return found, new_commands

            continue

        if i.graph != graph.graph_id:
            gi = state.observer.get_graph_info(i.graph)
            if gi is None:
                continue
            else:
                graph = gi.graph

        state.value_data.append(dict(
            id=i.to_str(),
            ord=i.sort_key(),
            X="?",
            name=i.indent(graph) + name,
            type=format_type(v),
            value=format_value(v),
            timestamp=format_timestamp(v)
        ))

        items += 1

        if not is_item_subscribed(state, i):
            state.found_items.add(i.to_str())

        if items >= limit:
            return i.to_str(), []

    return "", []


def handle_requests(state: InspectorState):
    publish = False
    while f_r := state.requests.dequeue():
        f, r = f_r
        handle_inspector_request(state, r, f)
        publish = True

    return publish


def handle_inspector_request(state: InspectorState, request: HttpGetRequest, f: Future):
    command = request.url_parsed_args[0]
    item_str = request.url_parsed_args[1]
    item_id = InspectorItemId.from_str(item_str)

    commands = deque()
    commands.append((command, item_id))

    total_response = ""

    while commands:
        command, item_id = commands.popleft()

        try:
            match command:
                case "expand":
                    response, new_commands = inspector_expand_item(state, item_id)
                case "show":
                    response, new_commands = inspector_show_item(state, item_id)
                case "search":
                    if "q" not in request.query:
                        raise ValueError("Search command requires a query parameter")

                    search = re.compile(request.query["q"], re.I)
                    depth = int(request.query.get("depth", 3))
                    limit = request.query.get("limit", 10)

                    prev_found_items = state.found_items
                    state.found_items = set()

                    response, new_commands = inspector_search_item(state, item_id, search, depth=depth, limit=limit)

                    state.value_removals.update(prev_found_items - state.found_items)

                case "applysearch":
                    new_commands = []
                    for i in state.found_items:
                        item_id = InspectorItemId.from_str(i)
                        new_commands += [("show", i) for i in item_id.parent_item_ids()] + [("show", item_id)]
                    state.found_items.clear()

                    response = "OK"

                case "stopsearch":
                    state.value_removals.update(state.found_items)
                    response = "OK"
                    new_commands = []

                case "collapse":
                    response, new_commands = inspector_collapse_item(state, item_id)
                case "pin":
                    response, new_commands = inspector_pin_item(state, item_id)
                case "ref":
                    response, new_commands = inspector_follow_ref(state, item_id)
                case "pin_ref":
                    response, new_commands = inspector_pin_ref(state, item_id)
                case "unpin":
                    response, new_commands = inspector_unpin_item(state, item_id)
                case _:  # pragma: no cover
                    set_result(f, HttpResponse(404, body="Invalid command"))
                    return
        except Exception as e:
            set_result(f, HttpResponse(500, body=f"Error: {e}"))
            # return
            raise e

        total_response += response if not total_response else (f"\n{response}" if response else "")
        commands.extend(new_commands)

    set_result(f, HttpResponse(200, body=total_response))


def subscribe_item(state, sub_item_id):
    if sub_item_id.node is None:
        state.graph_subscriptions[sub_item_id.graph] = sub_item_id
        state.observer.subscribe_graph(sub_item_id.graph)
    elif sub_item_id.value_type is None:
        node_id = sub_item_id.graph + (sub_item_id.node,)
        state.node_subscriptions[node_id] = sub_item_id
        state.observer.subscribe_node(node_id)
    else:
        node_id = sub_item_id.graph + (sub_item_id.node,)
        state.node_item_subscriptions[node_id].add(sub_item_id)
        if node_id not in state.node_subscriptions:
            state.node_subscriptions[node_id] = sub_item_id
            state.observer.subscribe_node(node_id)


def unsubscribe_item(state, sub_item_id):
    if sub_item_id.node is None:
        state.graph_subscriptions.pop(sub_item_id.graph, None)
        state.observer.unsubscribe_graph(sub_item_id.graph)
    elif sub_item_id.value_type is None:
        node_id = sub_item_id.graph + (sub_item_id.node,)
        state.node_subscriptions.pop(node_id, None)
        if not state.node_item_subscriptions.get(node_id):
            state.observer.unsubscribe_node(sub_item_id.graph + (sub_item_id.node))
    else:
        node_id = sub_item_id.graph + (sub_item_id.node,)
        subscriptions = state.node_item_subscriptions.get(node_id)
        if subscriptions is not None:
            subscriptions.remove(sub_item_id)
            if not subscriptions:
                del state.node_item_subscriptions[node_id]
                if node_id not in state.node_subscriptions:
                    state.observer.unsubscribe_node(node_id)


def is_item_subscribed(state, item_id):
    if item_id.node is None:
        return item_id.graph in state.graph_subscriptions
    elif item_id.value_type is None:
        return item_id.graph + (item_id.node,) in state.node_subscriptions
    else:
        return item_id in state.node_item_subscriptions.get(item_id.graph + (item_id.node,), set())


def set_result(f, r):
    def apply_result(fut, res):
        try:
            fut.set_result(res)
        except:
            pass

    from hgraph.adaptors.tornado._tornado_web import TornadoWeb
    TornadoWeb.get_loop().add_callback(lambda f, r: apply_result(f, r), f, r)


