from typing import TYPE_CHECKING
from uuid import UUID

from endstone import Player

if TYPE_CHECKING:
    from jwinventoryapi.manager import Session

sessions: dict[UUID, 'Session'] = {}


def find_session(player: Player) -> 'Session | None':
    return sessions.get(player.unique_id)


def create_session(player: Player) -> 'Session':
    from jwinventoryapi.manager import Session
    session = Session(player=player)
    sessions[player.unique_id] = session
    return session


def close_session(player: Player):
    session = sessions.pop(player.unique_id, None)
    if session is not None:
        if session.menu is not None:
            session.menu._remove_session(session)
        session.close()