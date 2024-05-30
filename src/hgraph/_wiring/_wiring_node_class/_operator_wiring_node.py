from typing import Mapping, Any, TypeVar, Callable, TYPE_CHECKING, List, Tuple

from hgraph._wiring._wiring_errors import WiringError
from hgraph._wiring._wiring_errors import WiringFailureError
from hgraph._wiring._wiring_node_class._wiring_node_class import WiringNodeClass, HgTypeMetaData, WiringNodeSignature, \
    PreResolvedWiringNodeWrapper, validate_and_resolve_signature
from hgraph._wiring._wiring_node_signature import WiringNodeType, AUTO_RESOLVE
from hgraph._wiring._wiring_port import WiringPort

if TYPE_CHECKING:
    from hgraph._builder._node_builder import NodeBuilder
    from hgraph._runtime._node import NodeSignature

__all_ = ("OperatorWiringNodeClass", "OverloadedWiringNodeHelper")


class OperatorWiringNodeClass(WiringNodeClass):

    def __init__(self, signature: WiringNodeSignature, fn: Callable):
        super().__init__(signature, fn)
        self._overload_helper: OverloadedWiringNodeHelper = OverloadedWiringNodeHelper(self)

    def overload(self, other: "WiringNodeClass"):
        self._overload_helper.overload(other)

    def _check_overloads(self, *args, **kwargs) -> tuple[bool, "WiringPort"]:
        best_overload = self._overload_helper.get_best_overload(*args, **kwargs)
        best_overload: WiringNodeClass
        if best_overload is not self:
            return True, best_overload(*args, **kwargs)
        else:
            return False, None

    def __call__(self, *args, __pre_resolved_types__: dict[TypeVar, HgTypeMetaData] = None,
                 **kwargs) -> "WiringNodeInstance":
        found_overload, r = self._check_overloads(*args, **kwargs, __pre_resolved_types__=__pre_resolved_types__)
        if found_overload:
            return r
        else:
            raise NotImplementedError(f"No overload found for {repr(self)} and parameters: {args}, {kwargs}")

    def __getitem__(self, item) -> "WiringNodeClass":
        if item:
            return PreResolvedWiringNodeWrapper(
                signature=self.signature,
                fn=self.fn,
                underlying_node=self,
                resolved_types=self._convert_item(item)
            )
        else:
            return self

    def resolve_signature(self, *args, __pre_resolved_types__: dict[TypeVar, HgTypeMetaData | Callable] = None,
                          **kwargs) -> "WiringNodeSignature":
        _, resolved_signature, _ = validate_and_resolve_signature(
            self.signature,
            *args,
            __pre_resolved_types__=__pre_resolved_types__,
            **kwargs)
        return resolved_signature

    def create_node_builder_instance(self, node_signature: "NodeSignature",
                                     scalars: Mapping[str, Any]) -> "NodeBuilder":
        raise RuntimeError("Should not be instantiating an operator definition")

    def __repr__(self):
        from inspect import signature
        s = signature(self.fn)
        return f"{self.fn.__name__}{str(s)}"


class OverloadedWiringNodeHelper:
    """
    This meta wiring node class deals with graph/node declaration overloads, for example when we have an implementation
    of a node that is generic

        def n(t: TIME_SERIES_TYPE)

    and another one that is more specific like

        def n(t: TS[int])

    in this case if wired with TS[int] input we should choose the more specific implementation and the generic one in
    other cases.

    This problem becomes slightly trickier with more inputs or more complex types, consider:

        def m(t1: TIME_SERIES_TYPE, t2: TIME_SERIES_TYPE)  # choice 1
        def m(t1: TS[SCALAR], t2: TS[SCALAR])  # choice 2
        def m(t1: TS[int], t2: TIME_SERIES_TYPE)  # choice 3

    What should we wire provided two TS[int] inputs? In this case choice 2 is the right answer because it is more
    specific about ints inputs even if choice 3 matches one of the input types exactly. We consider a signature with
    top level generic inputs as always less specified than a signature with generics as parameters to specific
    collection types. This rule applies recursively so TSL[V, 2] is less specific than TSL[TS[SCALAR], 2]
    """

    overloads: List[Tuple[WiringNodeClass, float]]

    def __init__(self, base: WiringNodeClass):
        self.overloads = [(base, self._calc_rank(base.signature))]

    def overload(self, impl: WiringNodeClass):
        self.overloads.append((impl, self._calc_rank(impl.signature)))

    @staticmethod
    def _calc_rank(signature: WiringNodeSignature) -> float:
        if signature.node_type == WiringNodeType.OPERATOR:
            return 1e6  # Really not a good ranking
        return sum(t.operator_rank * (0.001 if t.is_scalar else 1)
                   for k, t in signature.input_types.items()
                   if signature.defaults.get(k) != AUTO_RESOLVE)

    def get_best_overload(self, *args, **kwargs):
        candidates = []
        rejected_candidates = []
        for c, r in self.overloads:
            try:
                # Attempt to resolve the signature, if this fails then we don't have a candidate
                c.resolve_signature(*args, **kwargs,
                                    __enforce_output_type__=c.signature.node_type != WiringNodeType.GRAPH)
                candidates.append((c, r))
            except (WiringError, SyntaxError) as e:
                if isinstance(e, WiringFailureError):
                    e = e.__cause__

                p = lambda x: str(x.output_type.py_type) if isinstance(x, WiringPort) else str(x)
                reject_reason = (f"Did not resolve {c.signature.name} with {','.join(p(i) for i in args)}, "
                                 f"{','.join(f'{k}:{p(v)}' for k, v in kwargs.items())} : {e}")

                rejected_candidates.append((c.signature.signature, reject_reason))
            except Exception as e:
                raise

        if not candidates:
            args_tp = [str(a.output_type) if isinstance(a, WiringPort) else str(a) for a in args]
            kwargs_tp = [(str(k), str(v.output_type) if isinstance(v, WiringPort) else str(v)) for k, v in
                         kwargs.items() if not k.startswith("_")]
            _msg_part = '\n'.join(str(c) for c in rejected_candidates)
            raise WiringError(
                f"{self.overloads[0][0].signature.name} cannot be wired with given parameters - no matching candidates found\n"
                f"{args_tp}, {kwargs_tp}"
                f"\nRejected candidates: {_msg_part}"
            )

        best_candidates = sorted(candidates, key=lambda x: x[1])
        if len(best_candidates) > 1 and best_candidates[0][1] == best_candidates[1][1]:
            p = lambda x: str(x.output_type) if isinstance(x, WiringPort) else str(x)
            raise WiringError(
                f"{self.overloads[0][0].signature.name} overloads are ambiguous with given parameters - more than one top candidate: "
                f"{','.join(c.signature.signature for c, r in best_candidates if r == best_candidates[0][1])}"
                f"\nwhen wired with {','.join(p(i) for i in args)}, {','.join(f'{k}:{p(v)}' for k, v in kwargs.items())}")

        return best_candidates[0][0]