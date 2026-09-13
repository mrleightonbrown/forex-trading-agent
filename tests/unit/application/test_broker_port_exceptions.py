from forex_agent.application.ports.exceptions import (
    BrokerPortError,
    BrokerUnavailableError,
    InstrumentNotAvailableError,
)
from forex_agent.domain.instrument import Instrument


def test_instrument_not_available_error_is_a_broker_port_error() -> None:
    instrument = Instrument(base_currency="EUR", quote_currency="USD")

    error = InstrumentNotAvailableError(instrument)

    assert isinstance(error, BrokerPortError)
    assert instrument.symbol in str(error)
    assert error.instrument == instrument


def test_broker_unavailable_error_is_a_broker_port_error() -> None:
    assert issubclass(BrokerUnavailableError, BrokerPortError)
