from hub.constants import UNCOMPRESSED
from hub.util.compress import decompress_array
import warnings
import os
from typing import Optional
import numpy as np

import numpy as np

from hub.core.typing import StorageProvider


def sample_from_index_entry(
    key: str,
    storage: StorageProvider,
    index_entry: dict,
    dtype: str,
) -> np.ndarray:
    """Get the un-chunked sample from a single `index_meta` entry.

    Args:
        key (str): Key relative to `storage` where this instance.
        storage (StorageProvider): Storage of the sample.
        index_entry (dict): Index metadata of sample with `chunks_names`, `start_byte` and `end_byte` keys.
        dtype (str): Data type of the sample.

    Returns:
        Numpy array from the bytes of the sample.
    """

    chunk_names = index_entry["chunk_names"]
    shape = index_entry["shape"]

    # sample has no data
    if len(chunk_names) <= 0:
        return np.zeros(shape, dtype=dtype)

    buffer = bytearray()
    for chunk_name in chunk_names:
        chunk_key = os.path.join(key, "chunks", chunk_name)
        last_b_len = len(buffer)
        buffer.extend(storage[chunk_key])

    start_byte = index_entry["start_byte"]
    end_byte = last_b_len + index_entry["end_byte"]

    mv = memoryview(buffer)[start_byte:end_byte]
    compression = index_entry["compression"]

    if compression == UNCOMPRESSED:
        # TODO: chunk-wise compression

        return array_from_buffer(
            mv,
            dtype,
            shape=shape,
        )

    return decompress_array(mv, compression)


def array_from_buffer(
    b: memoryview,
    dtype: str,
    shape: tuple = None,
) -> np.ndarray:
    """Reconstruct a sample from bytearray (memoryview) only using the bytes `b[start_byte:end_byte]`. By default all
    bytes are used.

    Args:
        b (memoryview): Bytes that should be decompressed and converted to array.
        dtype (str): Data type of the sample.
        compression (str): Compression type this sample was encoded with.
        shape (tuple): Array shape from index entry.
        start_byte (int): Get only bytes starting from start_byte.
        end_byte (int, optional): Get only bytes up to end_byte.

    Returns:
        Numpy array from the bytes of the sample.

    Raises:
        ArrayShapeInfoNotFound: If no info about sample shape is in meta.
    """
    # TODO update docstring

    array = np.frombuffer(b, dtype=dtype)

    if shape is not None:
        array = array.reshape(shape)
    else:
        warnings.warn(
            "Could not find `shape` for a sample. It was missing from the IndexMeta entry. The array is being returned flat."
        )

    return array
