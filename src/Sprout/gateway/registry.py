"""Named gateway registry."""

from Sprout.gateway.base import Gateway
from Sprout.registry.base import Registry


class GatewayRegistry:
    def __init__(self) -> None:
        self._registry: Registry[Gateway] = Registry()

    def register(self, name: str, gateway: Gateway, *, replace: bool = True) -> None:
        self._registry.register(name, gateway, replace=replace)

    def get(self, name: str) -> Gateway:
        return self._registry.get(name)

    def list(self) -> dict[str, Gateway]:
        return self._registry.list()
