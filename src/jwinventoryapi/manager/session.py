from collections import deque
from enum import Enum
from typing import TYPE_CHECKING

from bedrock_protocol.packets.types import BlockPos
from endstone import Player
from endstone.inventory import ItemStack

from jwinventoryapi.manager.container_manager.container_manager import ContainerManager
from jwinventoryapi.menu.graphic.block_graphic import BlockGraphic
from jwinventoryapi.menu.graphic.block_pair_graphic import BlockPairGraphic
from jwinventoryapi.menu.graphic.graphic import Graphic

if TYPE_CHECKING:
    from jwinventoryapi.menu import Menu

from jwinventoryapi.network.inventory_content_packet import InventoryContentPacket
from jwinventoryapi.network.inventory_slot_packet import InventorySlotPacket
from jwinventoryapi.network.item_stack_wrapper import ItemStackWrapper
from jwinventoryapi.util.item_utils import is_air
from jwinventoryapi.util.utils import send_ack_packet, get_block_behind

_PLAYER_CONTAINER_ID = 28


class Session:
    CONTAINER_ID: int = 2
    MAX_OPEN_ATTEMPTS: int = 10

    class State(Enum):
        NONE = 0
        GRAPHIC_SENT = 1
        GRAPHIC_RECEIVED = 2
        GRAPHIC_DATA_SENT = 3
        GRAPHIC_DATA_RECEIVED = 4
        OPENING = 5
        OPEN = 6
        CLOSING = 7

    def __init__(self, player: Player):
        self.player: Player = player
        self._menu: 'Menu | None' = None
        self.state: Session.State = self.State.NONE
        self.graphic: Graphic | None = None
        self.container_manager: ContainerManager | None = None
        self.block_pos: list[BlockPos] = []
        self.open_attempts: int = 0
        self.ack_timestamp: int = 0
        self.pending: deque['Menu'] = deque()
        self._next_stack_id: int = 1

    def _alloc_stack_id(self) -> int:
        sid = self._next_stack_id
        self._next_stack_id += 1
        if self._next_stack_id > 2147483000:
            self._next_stack_id = 1
        return sid

    @property
    def menu(self) -> 'Menu | None':
        return self._menu

    @menu.setter
    def menu(self, value: 'Menu | None') -> None:
        if self._menu is not None:
            self._menu._remove_session(self)
        self._menu = value
        if value is not None:
            value._add_session(self)
            self.container_manager = ContainerManager(self.player, value.inventory)

    def send_menu(self):
        self.open_attempts = 0
        self.ack_timestamp = 0
        pos = get_block_behind(self.player, 2)
        if self.menu.type.is_pair:
            self.graphic = BlockPairGraphic(self.menu, pos)
        else:
            self.graphic = BlockGraphic(self.menu, pos)
        self._send_graphic()

    def _send_graphic(self):
        self.graphic.send(self.player)
        self.state = self.State.GRAPHIC_SENT
        self.ack_timestamp = send_ack_packet(self.player)

    def send_graphic_data(self):
        self.graphic.send_data(self.player)
        self.state = self.State.GRAPHIC_DATA_SENT
        self.ack_timestamp = send_ack_packet(self.player)

    def open(self):
        self.state = self.State.OPENING
        self.graphic.open(self.player)
        self.ack_timestamp = send_ack_packet(self.player)

    def send_contents(self):
        inventory = self.menu.inventory
        pk = InventoryContentPacket(self.CONTAINER_ID)
        for i in range(inventory.size):
            item_stack = inventory.get_item(i)
            stack_id = self.container_manager.assign_virtual_slot(i, item_stack)
            pk.items.append(ItemStackWrapper(stack_id, item_stack))
        self.player.send_packet(pk.get_packet_id(), pk.serialize())

    def send_player_inventory(self):
        player_inv = self.player.inventory
        pk = InventoryContentPacket(_PLAYER_CONTAINER_ID)
        for i in range(player_inv.size):
            item = player_inv.get_item(i)
            if item is None or is_air(item):
                pk.items.append(ItemStackWrapper(0, ItemStack("minecraft:air")))
            else:
                pk.items.append(ItemStackWrapper(self._alloc_stack_id(), item))
        self.player.send_packet(pk.get_packet_id(), pk.serialize())

    def update_slot(self, slot: int):
        item = self.menu.inventory.get_item(slot)
        stack_id = self.container_manager.assign_virtual_slot(slot, item)
        pk = InventorySlotPacket(self.CONTAINER_ID, slot=slot, item=ItemStackWrapper(stack_id, item))
        self.player.send_packet(pk.get_packet_id(), pk.serialize())

    def close(self, sync_inventory: bool = False):
        self.state = self.State.CLOSING
        if self.graphic is not None:
            self.graphic.remove(self.player)
        if self.container_manager is not None:
            cursor_item = self.container_manager.cursor_container.get(0)
            if cursor_item is not None:
                self.player.inventory.add_item(cursor_item)
                self.container_manager.cursor_container.set(0, None)
            if sync_inventory:
                self.container_manager.sync_player_inventory()

    def update_state(self, state: State):
        self.state = state
        match state:
            case self.State.GRAPHIC_RECEIVED:
                self.send_graphic_data()
            case self.State.GRAPHIC_DATA_RECEIVED:
                self.open()
            case self.State.OPEN:
                self.send_contents()

    def __del__(self):
        self.close()