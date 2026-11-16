"""Release source K/V records after native concatenation, before prediction."""
from functools import update_wrapper
from types import FunctionType


def release_encoding_records(native, concat, *, offload_reference_weights=False):
    if offload_reference_weights:
        # This is the tested upstream _make_wrapper closure protocol.
        adapter = native.__closure__[native.__code__.co_freevars.index("adapter")].cell_contents

    def concatenate(records):
        result = concat(records)
        # SnapRef next reads token counts from these records. Preserve their
        # tensor metadata without retaining a second set of GPU K/V storage.
        # Replace only the outer list: the single-reference result may alias
        # an original inner record and must keep its real tensors intact.
        records[:] = [
            [tuple(tensor.to(device="meta") for tensor in pair) for pair in record]
            for record in records
        ]
        if offload_reference_weights:
            # Only the reference encoder uses this stream. Native SnapRef
            # brings it back to the required device/dtype on a later miss.
            # Keep the lists intact: installed hooks hold these same objects.
            for streams in adapter.lora.values():
                if "ref" in streams:
                    weights = streams["ref"]
                    weights[0] = weights[0].to(device="cpu")
                    weights[1] = weights[1].to(device="cpu")
        return result

    # Bind this helper to this model's native wrapper only. Do not replace
    # SnapRef module globals or affect other models using ordinary SnapRef.
    namespace = {**native.__globals__, "_concat_kv": concatenate}
    wrapped = FunctionType(
        native.__code__, namespace, native.__name__, native.__defaults__, native.__closure__)
    wrapped.__kwdefaults__ = native.__kwdefaults__
    return update_wrapper(wrapped, native)
