from typing import Any, Tuple
from uuid import UUID, uuid4, uuid5
from hub.constants import ENCODING_DTYPE, UUID_SHIFT_AMOUNT
from binascii import hexlify, unhexlify


def _str_hexlify(payload: Any) -> bytes:
    return hexlify(bytes(str(payload), "utf-8"))


def _str_unhexlify(encoded_payload: bytes) -> str:
    return unhexlify(encoded_payload).decode("utf-8")


def _cast_to_encoding_dtype(uuid: UUID) -> ENCODING_DTYPE:
    return ENCODING_DTYPE(uuid.int >> UUID_SHIFT_AMOUNT)



def random_chunk_id() -> ENCODING_DTYPE:
    return _cast_to_encoding_dtype(uuid4())


def derive_tile_chunk_id(root_chunk_id: ENCODING_DTYPE, tile_shape: Tuple[int, ...]) -> ENCODING_DTYPE:
    """Tile chunks store their tile shape inside the chunk ID using uuid5. 
    The `root_chunk_id` is used as the namespace, and the `tile_shape` is the name.
    
    https://docs.python.org/3/library/uuid.html#uuid.uuid5
    """

    root_chunk_uuid = chunk_uuid_from_id(root_chunk_id)
    hex_tile_shape = _str_hexlify(tile_shape)
    print('test')
    print(hex_tile_shape, _str_unhexlify(hex_tile_shape))

    root_chunk_name = chunk_name_from_id(root_chunk_id)
    print(root_chunk_name)
    exit()

    # return _cast_to_encoding_dtype(uuid5(root_chunk_uuid, str(tile_shape)))


def is_tile_chunk_id(tile_chunk_id: ENCODING_DTYPE):
    # TODO: docstring

    # uuid = chunk_uuid_from_id(tile_chunk_id)
    raise NotImplementedError


def derive_tile_shape(tile_chunk_id: ENCODING_DTYPE) -> Tuple[int, ...]:
    # TODO
    raise NotImplementedError


def chunk_uuid_from_id(id: ENCODING_DTYPE) -> UUID:
    chunk_name = chunk_name_from_id(id)
    padded_chunk_name = chunk_name + ("0" * 24)
    return UUID(hex=padded_chunk_name)


def chunk_name_from_id(id: ENCODING_DTYPE) -> str:
    """Returns the hex of `id` with the "0x" prefix removed. This is the chunk's name and should be used to determine the chunk's key.
    Can convert back into `id` using `chunk_id_from_name`."""

    return hex(id)[2:]


def chunk_id_from_name(name: str) -> ENCODING_DTYPE:
    """Returns the 64-bit integer from the hex `name` generated by `chunk_name_from_id`."""

    return int("0x" + name, 16)
