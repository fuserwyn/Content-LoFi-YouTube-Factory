import pytest

from src.entrypoint import main


def test_main_oneshot_mode_runs_pipeline(mocker, monkeypatch) -> None:
    # Set up required env vars
    monkeypatch.setenv("PEXELS_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test_id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "test_token")
    monkeypatch.setenv("RUN_MODE", "oneshot")

    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mock_run = mocker.patch("src.entrypoint.run_pipeline")

    # Configure mock config to return oneshot mode
    mock_config.return_value.run_mode = "oneshot"

    main()

    mock_logger.assert_called_once()
    mock_config.assert_called_once()
    mock_run.assert_called_once()


def test_main_webhook_mode_starts_server(mocker, monkeypatch) -> None:
    # Set up required env vars
    monkeypatch.setenv("PEXELS_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test_id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "test_token")
    monkeypatch.setenv("RUN_MODE", "webhook")

    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mock_server = mocker.patch("src.entrypoint.start_trigger_server")
    mock_run = mocker.patch("src.entrypoint.run_pipeline")

    # Configure mock config to return webhook mode
    mock_config.return_value.run_mode = "webhook"

    main()

    mock_logger.assert_called_once()
    mock_config.assert_called_once()
    mock_server.assert_called_once_with(mock_config.return_value)
    mock_run.assert_not_called()


def test_main_loads_config(mocker, monkeypatch) -> None:
    # Set up required env vars
    monkeypatch.setenv("PEXELS_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test_id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "test_token")

    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mocker.patch("src.entrypoint.run_pipeline")

    mock_config.return_value.run_mode = "oneshot"

    main()

    mock_config.assert_called_once()


def test_main_sets_up_logger(mocker, monkeypatch) -> None:
    # Set up required env vars
    monkeypatch.setenv("PEXELS_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test_id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "test_token")

    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mocker.patch("src.entrypoint.run_pipeline")

    mock_config.return_value.run_mode = "oneshot"

    main()

    mock_logger.assert_called_once()


def test_main_handles_config_error(mocker, monkeypatch) -> None:
    # Don't set required env vars to trigger config error
    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mock_config.side_effect = ValueError("Missing required env var: PEXELS_API_KEY")

    with pytest.raises(ValueError, match="Missing required env var"):
        main()

    mock_logger.assert_called_once()


def test_main_handles_pipeline_error(mocker, monkeypatch) -> None:
    # Set up required env vars
    monkeypatch.setenv("PEXELS_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test_id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "test_token")

    mock_logger = mocker.patch("src.entrypoint.setup_logger")
    mock_config = mocker.patch("src.entrypoint.load_config")
    mock_run = mocker.patch("src.entrypoint.run_pipeline")

    mock_config.return_value.run_mode = "oneshot"
    mock_run.side_effect = RuntimeError("Pipeline failed")

    with pytest.raises(RuntimeError, match="Pipeline failed"):
        main()
