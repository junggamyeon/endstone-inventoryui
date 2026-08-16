from endstone.plugin import Plugin
from jwinventoryapi.listener import EventListener


class JWInventoryAPI(Plugin):
    prefix = "JWInventoryAPI"
    api_version = "0.11"
    load = "POSTWORLD"

    instance: 'JWInventoryAPI' = None

    def on_enable(self) -> None:
        JWInventoryAPI.instance = self
        self.register_events(EventListener(self))

    def on_disable(self) -> None:
        from jwinventoryapi.manager.player_manager import sessions
        for session in list(sessions.values()):
            session.close()
        sessions.clear()
        JWInventoryAPI.instance = None
