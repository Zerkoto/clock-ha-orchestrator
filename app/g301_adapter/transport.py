from __future__ import annotations

from typing import Protocol


class G301TransportError(RuntimeError):
    """Base error raised by a G301 transport implementation."""

    retryable = True


class G301TransportTimeout(G301TransportError):
    """The gateway did not complete an operation before its deadline."""


class G301ModbusException(G301TransportError):
    """A Modbus exception response was returned by the target."""

    retryable = False

    def __init__(self, message: str, *, exception_code: int | None = None) -> None:
        super().__init__(message)
        self.exception_code = exception_code


class G301DeviceOffline(G301TransportError):
    """The addressed G301 did not respond or is not present."""


class G301ProtocolError(G301TransportError):
    """The transport returned a malformed or incomplete response."""

    retryable = False


class G301RegisterClient(Protocol):
    async def write_register(
        self,
        *,
        slave_address: int,
        address: int,
        value: int,
    ) -> None: ...

    async def read_holding_registers(
        self,
        *,
        slave_address: int,
        address: int,
        count: int,
    ) -> list[int]: ...
