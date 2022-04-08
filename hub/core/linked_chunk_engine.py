from typing import Optional, Dict, Any
from hub.core.chunk.base_chunk import BaseChunk
from hub.core.chunk_engine import ChunkEngine
from hub.core.link_creds import LinkCreds
from hub.core.linked_sample import LinkedSample
from hub.core.meta.encode.creds import CredsEncoder
from hub.core.storage import LRUCache
from hub.core.compression import _read_video_shape, _decompress_video
import hub
from hub.util.exceptions import ReadOnlyModeError
from hub.util.keys import get_creds_encoder_key
from hub.util.video import normalize_index


class LinkedChunkEngine(ChunkEngine):
    def __init__(
        self,
        key: str,
        cache: LRUCache,
        version_state: Dict[str, Any],
        meta_cache: LRUCache = None,
        link_creds: Optional[LinkCreds] = None,
    ):
        super().__init__(key, cache, version_state, meta_cache)
        self.link_creds = link_creds
        self._creds_encoder: Optional[CredsEncoder] = None
        self._creds_encoder_commit_id: Optional[str] = None

    @property
    def creds_encoder(self):
        commit_id = self.commit_id
        if self._creds_encoder is None or self._creds_encoder_commit_id != commit_id:
            commit_id = self.commit_id
            key = get_creds_encoder_key(self.key, commit_id)
            if not self.creds_encoder_exists:
                enc = CredsEncoder()
                try:
                    self.meta_cache[key] = enc
                except ReadOnlyModeError:
                    pass
            else:
                enc = self.meta_cache.get_hub_object(key, CredsEncoder)
            self._creds_encoder = enc
            self._creds_encoder_commit_id = commit_id
            self.meta_cache.register_hub_object(key, enc)
        return self._creds_encoder

    @property
    def creds_encoder_exists(self):
        commit_id = self.commit_id
        if (
            self._creds_encoder is not None
            and self._creds_encoder_commit_id == commit_id
        ):
            return True
        try:
            key = get_creds_encoder_key(self.key, commit_id)
            self.meta_cache[key]
            return True
        except KeyError:
            return False

    @property
    def is_data_cachable(self):
        return False

    def get_video_sample(self, global_sample_index, index):
        creds_encoder = self.creds_encoder
        sample_path: str = super().get_basic_sample(global_sample_index, index)[0]
        sample_creds_encoded = creds_encoder.get_encoded_creds_key(global_sample_index)
        sample_creds_key = self.link_creds.get_creds_key(sample_creds_encoded)
        storage = None
        if sample_path.startswith(("gcs://", "gcp://", "s3://")):
            provider_type = "s3" if sample_path.startswith("s3://") else "gcs"
            storage = self.link_creds.get_storage_provider(
                sample_creds_key, provider_type
            )
            url = storage.get_presigned_url(sample_path, full=True)
        else:
            url = sample_path
        squeeze = isinstance(index, int)
        shape = _read_video_shape(url)
        sub_index = index.values[1].value if len(index.values) > 1 else None  # type: ignore
        start, stop, step, reverse = normalize_index(sub_index, shape[0])
        video_sample = _decompress_video(
            url,
            start,
            stop,
            step,
            reverse,
        )
        if squeeze:
            video_sample.squeeze(0)
        return video_sample

    def get_basic_sample(self, global_sample_index, index):
        creds_encoder = self.creds_encoder
        sample_path: str = super().get_basic_sample(global_sample_index, index)[0]
        sample_creds_encoded = creds_encoder.get_encoded_creds_key(global_sample_index)
        sample_creds_key = self.link_creds.get_creds_key(sample_creds_encoded)
        if sample_path.startswith(("gcs://", "gcp://", "s3://")):
            provider_type = "s3" if sample_path.startswith("s3://") else "gcs"
            storage = self.link_creds.get_storage_provider(
                sample_creds_key, provider_type
            )
            sample = hub.read(sample_path, storage=storage)
        else:
            sample = hub.read(sample_path)
        sample = sample.array[tuple(entry.value for entry in index.values[1:])]
        return sample

    # TODO, override def extend for callbacks

    def check_each_sample(self, samples):
        for sample in samples:
            if not isinstance(sample, LinkedSample):
                raise TypeError(
                    f"Expected LinkedSample, got {type(sample)} instead. Use hub.link() to link samples."
                )

    def register_new_creds(self, num_samples_added, samples):
        assert isinstance(num_samples_added, int)
        link_creds = self.link_creds
        creds_encoder = self.creds_encoder
        for i in range(num_samples_added):
            creds_key = samples[i].creds_key
            encoded_creds_key = link_creds.get_encoding(creds_key)
            creds_encoder.register_samples(encoded_creds_key, 1)

    def update_creds(self, sample_index: int, sample: LinkedSample):
        link_creds = self.link_creds
        creds_key = sample.creds_key
        encoded_creds_key = link_creds.get_encoding(creds_key)
        self.creds_encoder[sample_index] = encoded_creds_key
