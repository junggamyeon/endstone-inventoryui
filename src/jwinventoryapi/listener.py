from bedrock_protocol.packets import MinecraftPacketIds
from bedrock_protocol.packets.enums import ItemStackRequestActionType
from bedrock_protocol.packets.packet import ContainerClosePacket, ItemRegistryPacket, ItemStackRequestPacket
from bstream import BinaryStream
from endstone.event import event_handler, EventPriority, PlayerQuitEvent, PacketReceiveEvent, PacketSendEvent
from endstone.inventory import ItemStack
from endstone.plugin import Plugin

from .manager import Session
from .manager.player_manager import find_session, close_session
from .network.network_stack_latency_packet import NetworkStackLatencyPacket
from .util.item_utils import all_item_data, add_item_data, is_air

_CONTAINER_ENUM_GUI = 7
_ITEM_STACK_RESPONSE_ID = 148


def _build_reject_response(request_ids: list[int]) -> bytes:
    stream = BinaryStream()
    stream.write_unsigned_varint(len(request_ids))
    for rid in request_ids:
        stream.write_byte(1)  # result = Error/Reject
        stream.write_varint(rid)
    return stream.copy_buffer()


class EventListener:
    def __init__(self, plugin: Plugin):
        self._plugin = plugin

    @event_handler(priority=EventPriority.HIGHEST)
    def on_packet_receive(self, event: PacketReceiveEvent):
        player = event.player
        if player is None:
            return

        packet_id = event.packet_id

        if packet_id == MinecraftPacketIds.Ping:
            self._handle_ping(event)
        elif packet_id == MinecraftPacketIds.ContainerClose:
            self._handle_container_close(event)
        elif packet_id == MinecraftPacketIds.PacketViolationWarning:
            self._handle_violation_warning(event)
        elif packet_id == MinecraftPacketIds.ItemStackRequest:
            self._handle_item_stack_request(event)

    @event_handler
    def on_packet_send(self, event: PacketSendEvent):
        if event.packet_id == MinecraftPacketIds.ItemRegistryPacket and len(all_item_data()) == 0:
            pk = ItemRegistryPacket()
            pk.deserialize(event.payload)
            for item in pk.item_registry:
                add_item_data(item.item_name, item)

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        close_session(event.player)

    def _handle_ping(self, event: PacketReceiveEvent):
        session = find_session(event.player)
        if session is None:
            return

        pk = NetworkStackLatencyPacket()
        pk.deserialize(event.payload)

        if session.ack_timestamp != pk.timestamp:
            return

        match session.state:
            case Session.State.GRAPHIC_SENT:
                session.update_state(Session.State.GRAPHIC_RECEIVED)
            case Session.State.OPENING:
                if session.open_attempts >= Session.MAX_OPEN_ATTEMPTS:
                    session.close()
                    return
                session.open_attempts += 1
                session.open()

    def _handle_container_close(self, event: PacketReceiveEvent):
        player = event.player
        session = find_session(player)
        if session is None:
            return

        pk = ContainerClosePacket()
        pk.deserialize(event.payload)

        if pk.container_id != Session.CONTAINER_ID:
            return

        if session.menu is not None and session.menu._close_listener is not None:
            session.menu._close_listener(player)

        if session.pending:
            if session.state != Session.State.CLOSING:
                session.close()
            session.menu = session.pending.popleft()
            session.send_menu()
        else:
            close_session(player)

    def _handle_violation_warning(self, event: PacketReceiveEvent):
        session = find_session(event.player)
        if session is None:
            return

        if session.state == Session.State.OPENING:
            session.update_state(Session.State.OPEN)
            if session.menu is not None and session.menu._open_listener is not None:
                session.menu._open_listener(event.player)

    def _handle_item_stack_request(self, event: PacketReceiveEvent):
        player = event.player
        session = find_session(player)
        if session is None or session.state != Session.State.OPEN:
            return

        menu = session.menu

        if menu.is_locked:
            self._handle_locked(event, session)
        elif menu.is_editable:
            self._handle_editable(event, session)
        else:
            self._handle_click_only(event, session)

    def _handle_locked(self, event: PacketReceiveEvent, session: Session):
        event.is_cancelled = True
        # Send explicit rejection so client snaps items back immediately
        pk = ItemStackRequestPacket()
        pk.deserialize(event.payload)
        request_ids = [rd.client_request_id for rd in pk.request.request_data]
        if request_ids:
            payload = _build_reject_response(request_ids)
            session.player.send_packet(_ITEM_STACK_RESPONSE_ID, payload)
        session.send_contents()
        session.send_player_inventory()

    def _handle_editable(self, event: PacketReceiveEvent, session: Session):
        player = event.player
        menu = session.menu
        inv = menu.inventory

        pk = ItemStackRequestPacket()
        pk.deserialize(event.payload)

        inv.begin_batch()
        try:
            for req_data in pk.request.request_data:
                for action in req_data.request_actions:
                    action_type = action.action_type

                    if action_type == ItemStackRequestActionType.Destroy:
                        continue

                    if action_type not in (
                        ItemStackRequestActionType.Take,
                        ItemStackRequestActionType.Place,
                        ItemStackRequestActionType.Swap,
                    ):
                        continue

                    if action_type == ItemStackRequestActionType.Swap:
                        self._process_swap(action, inv, player)
                    else:
                        self._process_move(action, inv, player)
        finally:
            inv._dirty_slots.clear()
            inv._batch_mode = False

        event.is_cancelled = True
        request_ids = [rd.client_request_id for rd in pk.request.request_data]
        if request_ids:
            payload = _build_reject_response(request_ids)
            session.player.send_packet(_ITEM_STACK_RESPONSE_ID, payload)
        session.send_contents()
        session.send_player_inventory()

    def _handle_click_only(self, event: PacketReceiveEvent, session: Session):
        player = event.player
        menu = session.menu

        pk = ItemStackRequestPacket()
        pk.deserialize(event.payload)

        for req_data in pk.request.request_data:
            for action in req_data.request_actions:
                if action.action_type not in (
                    ItemStackRequestActionType.Take,
                    ItemStackRequestActionType.Place,
                ):
                    continue

                src = action.action_data.source
                source_is_gui = src.container.container_enum == _CONTAINER_ENUM_GUI

                if source_is_gui:
                    item_clicked = menu.inventory.get_item(src.slot)
                    menu._handle_click(player, src.slot, item_clicked)
                else:
                    if menu._place_listener is not None:
                        item_from_player = player.inventory.get_item(src.slot)
                        menu._place_listener(player, src.slot, item_from_player, menu.inventory)

                event.is_cancelled = True
                # Reject so client doesn't hold item on cursor
                request_ids = [rd.client_request_id for rd in pk.request.request_data]
                if request_ids:
                    payload = _build_reject_response(request_ids)
                    session.player.send_packet(_ITEM_STACK_RESPONSE_ID, payload)
                session.send_contents()
                session.send_player_inventory()
                return

    def _process_move(self, action, inv, player):
        src = action.action_data.source
        dst = action.action_data.distination
        count = action.action_data.amount

        src_is_gui = src.container.container_enum == _CONTAINER_ENUM_GUI
        dst_is_gui = dst.container.container_enum == _CONTAINER_ENUM_GUI

        if src_is_gui and not dst_is_gui:
            self._take_from_gui(inv, player, src.slot, count)
        elif dst_is_gui and not src_is_gui:
            self._place_into_gui(inv, player, src.slot, dst.slot, count)
        elif src_is_gui and dst_is_gui:
            self._move_within_gui(inv, src.slot, dst.slot, count)

    def _process_swap(self, action, inv, player):
        src = action.action_data.source
        dst = action.action_data.distination

        src_is_gui = src.container.container_enum == _CONTAINER_ENUM_GUI
        dst_is_gui = dst.container.container_enum == _CONTAINER_ENUM_GUI

        if src_is_gui and dst_is_gui:
            item_a = inv.get_item(src.slot)
            item_b = inv.get_item(dst.slot)
            inv.set_item(src.slot, item_b if not is_air(item_b) else None)
            inv.set_item(dst.slot, item_a if not is_air(item_a) else None)
        elif src_is_gui and not dst_is_gui:
            gui_item = inv.get_item(src.slot)
            player_item = player.inventory.get_item(dst.slot)
            inv.set_item(src.slot, player_item if player_item and not is_air(player_item) else None)
            player.inventory.set_item(dst.slot, gui_item if not is_air(gui_item) else None)
        elif not src_is_gui and dst_is_gui:
            player_item = player.inventory.get_item(src.slot)
            gui_item = inv.get_item(dst.slot)
            player.inventory.set_item(src.slot, gui_item if not is_air(gui_item) else None)
            inv.set_item(dst.slot, player_item if player_item and not is_air(player_item) else None)

    def _take_from_gui(self, inv, player, slot: int, count: int):
        current = inv.get_item(slot)
        if current is None or is_air(current):
            return

        take_count = min(count, current.amount)
        new_amount = current.amount - take_count

        if new_amount <= 0:
            inv.set_item(slot, None)
        else:
            updated = ItemStack(current.type.id, new_amount, current.data)
            updated.set_item_meta(current.item_meta)
            inv.set_item(slot, updated)

        give_item = ItemStack(current.type.id, take_count, current.data)
        give_item.set_item_meta(current.item_meta)
        player.inventory.add_item(give_item)

    def _place_into_gui(self, inv, player, player_slot: int, gui_slot: int, count: int):
        player_item = player.inventory.get_item(player_slot)
        if player_item is None or is_air(player_item):
            return

        take_count = min(count, player_item.amount)
        existing = inv.get_item(gui_slot)

        if existing is not None and not is_air(existing):
            if existing.type.id == player_item.type.id:
                cap = min(inv.max_stack_size, existing.max_stack_size)
                space = cap - existing.amount
                actual = min(take_count, space)
                if actual <= 0:
                    return
                merged = ItemStack(existing.type.id, existing.amount + actual, existing.data)
                merged.set_item_meta(existing.item_meta)
                inv.set_item(gui_slot, merged)
                take_count = actual
            else:
                return
        else:
            placed = ItemStack(player_item.type.id, take_count, player_item.data)
            placed.set_item_meta(player_item.item_meta)
            inv.set_item(gui_slot, placed)

        new_player_amount = player_item.amount - take_count
        if new_player_amount <= 0:
            player.inventory.set_item(player_slot, None)
        else:
            remaining = ItemStack(player_item.type.id, new_player_amount, player_item.data)
            remaining.set_item_meta(player_item.item_meta)
            player.inventory.set_item(player_slot, remaining)

    def _move_within_gui(self, inv, src_slot: int, dst_slot: int, count: int):
        current = inv.get_item(src_slot)
        if current is None or is_air(current):
            return

        take_count = min(count, current.amount)
        existing_dst = inv.get_item(dst_slot)

        new_src_amount = current.amount - take_count
        if new_src_amount <= 0:
            inv.set_item(src_slot, None)
        else:
            updated_src = ItemStack(current.type.id, new_src_amount, current.data)
            updated_src.set_item_meta(current.item_meta)
            inv.set_item(src_slot, updated_src)

        if existing_dst is not None and not is_air(existing_dst) and existing_dst.type.id == current.type.id:
            cap = min(inv.max_stack_size, existing_dst.max_stack_size)
            merged_amount = min(existing_dst.amount + take_count, cap)
            merged = ItemStack(existing_dst.type.id, merged_amount, existing_dst.data)
            merged.set_item_meta(existing_dst.item_meta)
            inv.set_item(dst_slot, merged)
        else:
            moved = ItemStack(current.type.id, take_count, current.data)
            moved.set_item_meta(current.item_meta)
            inv.set_item(dst_slot, moved)
