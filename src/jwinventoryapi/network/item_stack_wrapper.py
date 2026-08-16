from bedrock_protocol.packets.types import ItemData
from bstream import BinaryStream
from endstone.inventory import ItemStack

from jwinventoryapi.util.item_utils import build_tag, is_air, get_item_data


class ItemStackWrapper:
    def __init__(self, stack_id: int = 0, item_stack: ItemStack | None = None, stack_id_variant: int = 0):
        self.stack_id: int = stack_id
        self.stack_id_variant: int = stack_id_variant
        self.item_stack: ItemStack = item_stack or ItemStack("minecraft:air")
        data = get_item_data(self.item_stack.type.id)
        if data is None:
            data = get_item_data("minecraft:air")
        self.data: ItemData = data

    def write_footer(self, stream: BinaryStream):
        item_meta = self.item_stack.item_meta
        tag = build_tag(item_meta)
        if not tag.empty():
            stream.write_signed_short(-1)
            stream.write_byte(1)
            stream.write_raw_bytes(tag.to_binary_nbt())
        else:
            stream.write_signed_short(0)
        stream.write_unsigned_int(0)
        stream.write_unsigned_int(0)

    def write(self, stream: BinaryStream):
        is_air_item = is_air(self.item_stack)
        has_net_id = self.stack_id != 0

        stream.write_signed_short(0 if is_air_item else self.data.item_id)
        stream.write_unsigned_short(self.item_stack.amount)
        stream.write_unsigned_varint(self.item_stack.data)

        stream.write_bool(has_net_id)
        if has_net_id:
            stream.write_varint(self.stack_id)

        stream.write_unsigned_varint(0)
        if is_air_item:
            stream.write_unsigned_varint(0)
            return

        user_data = BinaryStream()
        self.write_footer(user_data)
        stream.write_bytes(user_data.copy_buffer())