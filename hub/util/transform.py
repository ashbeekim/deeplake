from hub.api.dataset import Dataset
from hub.util.exceptions import InvalidTransformOutputError
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
from hub.util.keys import get_chunk_key, get_tensor_meta_key, get_chunk_id_encoder_key
from hub.core.storage.provider import StorageProvider
from hub.core.meta.tensor_meta import TensorMeta
from hub.constants import DEFAULT_MAX_CHUNK_SIZE
import numpy as np


def transform_sample(
    sample: Any,
    pipeline: Sequence[Callable],
    kwarg_list: List[dict],
) -> List[dict]:
    """Calls all the functions one after the other on a single sample.
    Can return 0 or more samples.
    Args:
        sample: The sample on which the pipeline of functions is to be applied.
        pipeline: The Sequence of functions to apply on the sample.
        kwarg_list: A list of kwargs to be used with functions in the pipeline.
    Returns:
        List[Dict]: Containing a dictionary of all the output samples generated.
    """
    result = sample
    for index in range(len(pipeline)):
        fn = pipeline[index]
        kwargs = kwarg_list[index]
        if isinstance(result, (list, tuple)) and index != 0:
            result = [fn(data, **kwargs) for data in result]
        else:
            result = fn(result, **kwargs)
        if isinstance(result, list):
            result = flatten_list_of_list(result)
        verify_transform_output(result)
    return result if isinstance(result, list) else [result]


def flatten_list_of_list(ls: List) -> List:
    """Flattens list of list into 1D list"""
    items = []
    for r in ls:
        if isinstance(r, dict):
            items.append(r)
        else:
            items.extend(r)
    return items


def verify_transform_output(output):
    """Checks whether the output of a transform is valid."""
    if isinstance(output, (list, tuple)):
        for item in output:
            if not isinstance(item, dict):
                raise InvalidTransformOutputError(item)
    elif not isinstance(output, dict):
        raise InvalidTransformOutputError


def get_first_chunk(index_meta: dict) -> Tuple[str, int]:
    """Finds the name and size of the first chunk in the index_meta."""
    chunk_name = ""
    chunk_size = 0

    if (
        len(index_meta["entries"]) > 0
        and len(index_meta["entries"][0]["chunk_names"]) > 0
    ):
        chunk_name = index_meta["entries"][0]["chunk_names"][0]
        chunk_size = 0

        for entry in index_meta["entries"]:
            if entry["chunk_names"] == [chunk_name]:
                chunk_size = entry["end_byte"]
            elif (
                len(entry["chunk_names"]) > 1 and entry["chunk_names"][0] == chunk_name
            ):
                chunk_size = DEFAULT_MAX_CHUNK_SIZE
            else:
                break

    return chunk_name, chunk_size


def merge_chunks(
    chunk_min_target: int,
    tensor: str,
    storage: StorageProvider,
    current_meta: Dict,
    first_chunk_name: str = "",
    first_chunk_size: int = 0,
    last_chunk_name: str = "",
    last_chunk_size: int = 0,
):
    """Merges 2 chunks which are the last chunk of worker n and first chunk of worker n+1 into a single one if possible.
    This is done to reduce the number of suboptimal chunks generated.
    """
    if (
        first_chunk_size < chunk_min_target
        and first_chunk_size + last_chunk_size <= DEFAULT_MAX_CHUNK_SIZE
    ):
        first_chunk_key = get_chunk_key(tensor, first_chunk_name)
        last_chunk_key = get_chunk_key(tensor, last_chunk_name)

        last_chunk_content: bytes = storage[last_chunk_key]
        first_chunk_content: bytes = storage[first_chunk_key]

        new_chunk = bytearray(last_chunk_content) + first_chunk_content
        del storage[first_chunk_key]
        storage[last_chunk_key] = new_chunk

        offset = last_chunk_size

        for i in range(len(current_meta["entries"])):
            if current_meta["entries"][i]["chunk_names"] == [first_chunk_name]:
                current_meta["entries"][i]["chunk_names"] = [last_chunk_name]
                current_meta["entries"][i]["start_byte"] += offset
                current_meta["entries"][i]["end_byte"] += offset
            else:
                break


def merge_all_chunk_engines(all_workers_chunk_engines, ds_out):
    merge_tensor_metas(all_workers_chunk_engines, ds_out)
    merge_chunk_id_encoders(all_workers_chunk_engines, ds_out)


def merge_tensor_metas(all_workers_chunk_engines, ds_out):
    tensors = list(ds_out.meta.tensors)
    for tensor in tensors:
        tensor_meta = ds_out[tensor].meta
        for chunk_engine in all_workers_chunk_engines:
            current_meta = chunk_engine[tensor].tensor_meta
            # tensor meta is empty, copy attributes from current_meta
            if len(tensor_meta.max_shape) == 0 or tensor_meta.dtype is None:
                tensor_meta.dtype = current_meta.dtype
                tensor_meta.length += current_meta.length
                tensor_meta.max_shape = current_meta.max_shape
                tensor_meta.min_shape = current_meta.min_shape

            # len of min_shape will be 0 if 0 outputs from worker
            elif len(current_meta.min_shape) != 0:
                assert tensor_meta.dtype == current_meta.dtype
                # TODO we can support this once we have ragged tensor support
                assert len(tensor_meta.max_shape) == len(current_meta.max_shape)
                assert len(tensor_meta.min_shape) == len(current_meta.min_shape)
                tensor_meta.length += current_meta.length
                tensor_meta._update_shape_interval(tuple(current_meta.max_shape))
                tensor_meta._update_shape_interval(tuple(current_meta.min_shape))
        meta_key = get_tensor_meta_key(tensor)
        ds_out[tensor].chunk_engine.cache[meta_key] = tensor_meta
    ds_out.flush()


def merge_chunk_id_encoders(all_workers_chunk_engines, ds_out):
    tensors = list(ds_out.meta.tensors)
    for tensor in tensors:
        chunk_id_encoder = ds_out[tensor].chunk_engine.chunk_id_encoder
        offset = chunk_id_encoder.num_samples
        for chunk_engine in all_workers_chunk_engines:
            current_chunk_id_encoder = chunk_engine[tensor].chunk_id_encoder
            num_samples = current_chunk_id_encoder.num_samples
            encoded_ids = current_chunk_id_encoder._encoded_ids
            if encoded_ids is not None:
                for encoded_id in encoded_ids:
                    encoded_id[1] += offset
                    if chunk_id_encoder._encoded_ids is None:
                        chunk_id_encoder._encoded_ids = np.reshape(encoded_id, (-1, 2))
                    else:
                        chunk_id_encoder._encoded_ids = np.vstack(
                            [chunk_id_encoder._encoded_ids, encoded_id]
                        )
            offset += num_samples
        chunk_id_key = get_chunk_id_encoder_key(tensor)
        ds_out[tensor].chunk_engine.cache[chunk_id_key] = chunk_id_encoder
    ds_out.flush()


# def merge_tensor_metas(
#     all_workers_tensor_meta: List[Dict[str, dict]],
#     storage: StorageProvider,
#     tensors: List[str],
# ):
#     for tensor in tensors:
#         tensor_meta = TensorMeta.load(tensor, storage)

#         for all_tensor_meta in all_workers_tensor_meta:
#             current_meta = all_tensor_meta[tensor]

#             # tensor meta is empty, copy attributes from current_meta
#             if len(tensor_meta.max_shape) == 0 or tensor_meta.dtype is None:
#                 tensor_meta.dtype = current_meta["dtype"]
#                 tensor_meta.length += current_meta["length"]
#                 tensor_meta.max_shape = current_meta["max_shape"]
#                 tensor_meta.min_shape = current_meta["min_shape"]

#             # len of min_shape will be 0 if 0 outputs from worker
#             elif len(current_meta["min_shape"]) != 0:
#                 assert tensor_meta.dtype == current_meta["dtype"]
#                 # TODO we can support this once we have ragged tensor support
#                 assert len(tensor_meta.max_shape) == len(current_meta["max_shape"])
#                 assert len(tensor_meta.min_shape) == len(current_meta["min_shape"])
#                 tensor_meta.length += current_meta["length"]
#                 tensor_meta._update_shape_interval(tuple(current_meta["max_shape"]))
#                 tensor_meta._update_shape_interval(tuple(current_meta["min_shape"]))

#         tensor_meta.length += 0


# def merge_index_metas(
#     all_workers_index_meta: List[Dict[str, Dict]],
#     storage: StorageProvider,
#     tensors: List[str],
# ):
#     """Merges all of the separate index metas generated across workers.
#     Also merges "corner chunks" generated by each worker in case the size of those chunks is small.
#     """
#     for tensor in tensors:
#         index_meta = IndexMeta.load(tensor, storage)
#         tensor_meta = TensorMeta.load(tensor, storage)

#         last_chunk_name = ""
#         last_chunk_size = 0
#         chunk_min_target = tensor_meta.chunk_size

#         for all_index_meta in all_workers_index_meta:
#             current_meta = all_index_meta[tensor]
#             first_chunk_name, first_chunk_size = get_first_chunk(current_meta)
#             if first_chunk_name and last_chunk_name:
#                 merge_chunks(
#                     chunk_min_target,
#                     tensor,
#                     storage,
#                     current_meta,
#                     first_chunk_name,
#                     first_chunk_size,
#                     last_chunk_name,
#                     last_chunk_size,
#                 )

#             index_meta.entries.extend(current_meta["entries"])

#             # if there was atleast one chunk before
#             if (
#                 len(index_meta.entries) > 0
#                 and len(index_meta.entries[-1]["chunk_names"]) > 0
#             ):
#                 last_chunk_name = index_meta.entries[-1]["chunk_names"][-1]
#                 last_chunk_size = index_meta.entries[-1]["end_byte"]


def pipeline_to_list(
    pipeline: Union[Callable, Sequence[Callable]],
    kwargs: Optional[Union[Dict, Sequence[Dict]]] = None,
) -> Tuple[List[Callable], List[Dict]]:
    """Converts pipeline and kwargs to lists. Also makes the length of both lists equal to length of pipleine."""
    kwargs = kwargs or []
    kwargs = list(kwargs) if isinstance(kwargs, Sequence) else [kwargs]
    pipeline = list(pipeline) if isinstance(pipeline, Sequence) else [pipeline]

    kwargs = list(kwargs[: len(pipeline)])
    kwargs += [dict()] * (len(pipeline) - len(kwargs))
    return pipeline, kwargs


def load_updated_meta(ds_out: Dataset):
    """Clears the dataset's cache which may contain outdated meta file and loads updated meta after transform."""
    ds_out.clear_cache()
    ds_out._load_meta()
