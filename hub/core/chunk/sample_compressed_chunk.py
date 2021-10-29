from typing import List, Optional, Union

import numpy as np
import hub
from hub.core import sample
from hub.core.compression import compress_bytes, decompress_array, decompress_bytes

from hub.core.sample import Sample
from hub.core.serialize import (
    bytes_to_text,
    serialize_numpy_and_base_types,
    text_to_bytes,
)
from hub.util.casting import intelligent_cast
from .base_chunk import BaseChunk

SampleValue = Union[Sample, np.ndarray, int, float, bool, dict, list, str]
SerializedOutput = tuple(bytes, Optional[tuple])


class SampleCompressedChunk(BaseChunk):
    """Responsibility: Case where we are using sample-wise compression.
    Case:
        - sample_compression=compressed
        - chunk_compression=None
    Input pipeline:
        - hub.read(...) ->
            - if incoming compression matches, use unprocessed bytes
            - if incoming compression doesn't match, decompress then compress bytes
        - numpy -> compressed bytes
    """

    def serialize_sample(self, incoming_sample: SampleValue) -> SerializedOutput:
        dt, ht = self.dtype, self.htype
        if self.is_text_like:
            incoming_sample, shape = text_to_bytes(incoming_sample, dt, ht)
            incoming_sample = compress_bytes(incoming_sample, self.compression)
        elif isinstance(incoming_sample, Sample):
            shape = incoming_sample.shape
            if self.is_byte_compression:
                # Byte compressions don't store dtype, need to cast to expected dtype
                arr = intelligent_cast(incoming_sample.array, dt, ht)
                incoming_sample = Sample(array=arr)
            incoming_sample = incoming_sample.compressed_bytes(self.compression)
        else:  # np.ndarray, int, float, bool
            incoming_sample, shape = serialize_numpy_and_base_types(
                incoming_sample, dt, ht, self.compression
            )
        if shape is not None and len(shape) == 0:
            shape = (1,)
        return incoming_sample, shape

    def extend_if_has_space(
        self, incoming_samples: Union[List[Union[bytes, Sample, np.array]], np.array]
    ) -> int:
        self.prepare_for_write()
        for i, incoming_sample in enumerate(incoming_samples):
            serialized_sample, shape = self.serialize_sample(incoming_sample)
            sample_nbytes = len(serialized_sample)

            # optimization so that even if this sample doesn't fit, it isn't recompressed next time we try
            incoming_samples[i] = Sample(
                buffer=serialized_sample, compression=self.compression, shape=shape
            )

            if self.num_data_bytes + sample_nbytes > self.max_chunk_size:
                return i

            self.data_bytes += serialized_sample
            self.shapes.append(shape)
            self.register_sample_to_headers(sample_nbytes, shape)

        return len(incoming_samples)

    def read_sample(
        self, local_sample_index: int, cast: bool = True, copy: bool = False
    ):
        sb, eb = self.byte_positions_encoder[local_sample_index]
        buffer = self.memoryview_data[sb:eb]
        shape = self.shapes_encoder[local_sample_index]
        if self.is_text_like:
            buffer = decompress_bytes(buffer, compression=self.compression)
            buffer = bytes(buffer)
            return bytes_to_text(buffer, self.htype)

        sample = decompress_array(
            buffer, shape, dtype=self.dtype, compression=self.compression
        )
        if cast and sample.dtype != self.dtype:
            sample = sample.astype(self.dtype)
        return np.frombuffer(buffer, dtype=self.dtype).reshape(shape)

    def update_sample(
        self, local_sample_index: int, new_buffer: memoryview, new_shape: Tuple[int]
    ):
        raise NotImplementedError
