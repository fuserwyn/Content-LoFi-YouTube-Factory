import logging

from src.logger import setup_logger


def test_setup_logger_creates_logger() -> None:
    logger = setup_logger()
    assert logger is not None
    assert isinstance(logger, logging.Logger)


def test_setup_logger_sets_correct_name() -> None:
    logger = setup_logger()
    assert logger.name == "content_factory"


def test_setup_logger_sets_info_level() -> None:
    logger = setup_logger()
    assert logger.level == logging.INFO


def test_setup_logger_adds_stream_handler() -> None:
    logger = setup_logger()
    assert len(logger.handlers) > 0
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_setup_logger_formats_correctly() -> None:
    logger = setup_logger()
    handler = logger.handlers[0]
    formatter = handler.formatter
    assert formatter is not None
    assert "%(asctime)s" in formatter._fmt
    assert "%(levelname)s" in formatter._fmt
    assert "%(name)s" in formatter._fmt
    assert "%(message)s" in formatter._fmt


def test_setup_logger_returns_same_instance() -> None:
    logger1 = setup_logger()
    logger2 = setup_logger()
    assert logger1 is logger2


def test_setup_logger_does_not_duplicate_handlers() -> None:
    logger1 = setup_logger()
    initial_handler_count = len(logger1.handlers)
    logger2 = setup_logger()
    assert len(logger2.handlers) == initial_handler_count
