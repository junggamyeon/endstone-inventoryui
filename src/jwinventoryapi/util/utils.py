import math
import random

from bedrock_protocol.packets.packet import UpdateBlockPacket
from bedrock_protocol.packets.types import BlockPos
from endstone import Player

from jwinventoryapi.network.network_stack_latency_packet import NetworkStackLatencyPacket

def send_ack_packet(player: Player) -> int:
    timestamp = random.randint(1, 32767)
    pk = NetworkStackLatencyPacket(timestamp, True)
    player.send_packet(pk.get_packet_id(), pk.serialize())
    return timestamp * 1_000_000


def send_block(player: Player, name: str, pos: BlockPos):
    block_data = player.server.create_block_data(name)
    pk = UpdateBlockPacket(BlockPos(pos.x, pos.y, pos.z), block_data.runtime_id, 0b0010, 0)
    player.send_packet(pk.get_packet_id(), pk.serialize())


def get_block_behind(player: Player, distance: int = 1) -> BlockPos:
    location = player.location
    yaw_rad = math.radians(location.yaw + 180)
    x = location.x - math.sin(yaw_rad) * distance
    z = location.z + math.cos(yaw_rad) * distance
    return BlockPos(math.floor(x), math.floor(location.y + 1), math.floor(z))


def west(pos: BlockPos) -> BlockPos:
    return BlockPos(pos.x - 1, pos.y, pos.z)


def east(pos: BlockPos) -> BlockPos:
    return BlockPos(pos.x + 1, pos.y, pos.z)
