from pathlib import Path

import pytest

from src.bot import BotConfig
from src.highlights import Highlight
from src.remote_assets import S3SyncConfig
from src.shorts_cut import ShortClip
from src.shorts_pipeline import PipelineResult
from src.tenant_store import ClaimedJob
from src.transcribe import TranscriptSegment
from src.worker import WorkerSettings, load_worker_settings, process_job, run_once


def _cfg() -> BotConfig:
    return BotConfig(
        token="123:abc", database_url="postgresql://x", webhook_secret="s",
        public_base_url="", admin_chat_id="",
        s3=S3SyncConfig(
            enabled=True, bucket="b", endpoint_url="", region="auto",
            access_key_id="k", secret_access_key="s",
            videos_prefix="v", tracks_prefix="t",
        ),
    )


def _settings() -> WorkerSettings:
    return WorkerSettings(
        enabled=True, worker_id="worker-test", whisper_model="tiny",
        whisper_download_root="", language="ru",
        max_shorts=5, min_seconds=20, max_seconds=60,
    )


def _job() -> ClaimedJob:
    return ClaimedJob(id=1, user_id=2, source_id=3, highlight_id=None,
                      schedule_id=None, attempts=1)


def _result(*, speech=True, clips=1, highlights=1) -> PipelineResult:
    return PipelineResult(
        clips=[ShortClip(Path(f"c{i}.mp4"), 0, 25_000, True) for i in range(clips)],
        highlights=[Highlight(0, 25_000, 0.9, "t", "r") for _ in range(highlights)],
        segments=[TranscriptSegment(0, 25_000, "текст")],
        source_duration_ms=600_000,
        had_speech=speech,
    )


def _wire(mocker, result: PipelineResult):
    mocker.patch("src.worker.download_source", return_value=Path("/tmp/src.mp4"))
    def fake_build(*_a, on_clip_ready=None, **_kw):
        # Настоящий build_shorts зовёт колбэк на каждый готовый клип —
        # без этого воркер считает, что не отдал ничего.
        if on_clip_ready is not None:
            for clip, highlight in zip(result.clips, result.highlights):
                on_clip_ready(clip, highlight)
        return result

    mocker.patch("src.worker.build_shorts", side_effect=fake_build)
    send = mocker.patch("src.worker.send_clip")
    notify = mocker.patch("src.worker.notify_text")
    db = mocker.MagicMock()
    db.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "uploads/2/x/video.mp4", 555,
    )
    return db, send, notify


def test_process_job_marks_source_ready(mocker) -> None:
    db, _, _ = _wire(mocker, _result())

    process_job(_job(), db, _cfg(), _settings())

    assert db.set_source_status.call_args[0][1] == "ready"
    db.finish_job.assert_called_once()


def test_process_job_stores_transcript_and_highlights(mocker) -> None:
    db, _, _ = _wire(mocker, _result())

    process_job(_job(), db, _cfg(), _settings())

    db.save_transcript.assert_called_once()
    db.save_highlights.assert_called_once()


def test_process_job_fails_when_source_missing(mocker) -> None:
    _, _, _ = _wire(mocker, _result())
    db = mocker.MagicMock()
    db.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None

    assert process_job(_job(), db, _cfg(), _settings()) == 0
    db.fail_job.assert_called_once()


def test_silent_video_is_not_retried(mocker) -> None:
    # Повторная попытка речь не создаст — задачу закрываем, а не возвращаем в очередь.
    db, _, notify = _wire(mocker, _result(speech=False))

    process_job(_job(), db, _cfg(), _settings())

    db.fail_job.assert_not_called()
    db.finish_job.assert_called_once()
    assert "не нашлось речи" in notify.call_args[0][2]


def test_silent_video_tells_the_user_why(mocker) -> None:
    # Молчание вместо объяснения читается как поломка сервиса.
    db, _, notify = _wire(mocker, _result(speech=False))

    process_job(_job(), db, _cfg(), _settings())

    notify.assert_called_once()


def test_empty_selection_is_explained(mocker) -> None:
    db, _, notify = _wire(mocker, _result(clips=0, highlights=0))

    process_job(_job(), db, _cfg(), _settings())

    assert "не нашлось" in notify.call_args[0][2]


def test_run_once_returns_zero_on_empty_queue(mocker) -> None:
    db = mocker.Mock()
    db.claim_jobs.return_value = []
    mocker.patch("src.worker.TenantStore", return_value=db)

    assert run_once(_cfg(), _settings()) == 0
    db.close.assert_called_once()


def test_run_once_returns_job_to_queue_on_crash(mocker) -> None:
    # Падение одной задачи не должно ронять воркер и терять её молча.
    db = mocker.Mock()
    db.claim_jobs.return_value = [_job()]
    mocker.patch("src.worker.TenantStore", return_value=db)
    mocker.patch("src.worker.process_job", side_effect=RuntimeError("ffmpeg упал"))

    assert run_once(_cfg(), _settings()) == 0
    db.fail_job.assert_called_once()
    assert "ffmpeg упал" in db.fail_job.call_args[0][1]


def test_run_once_closes_connection_even_on_crash(mocker) -> None:
    db = mocker.Mock()
    db.claim_jobs.return_value = [_job()]
    mocker.patch("src.worker.TenantStore", return_value=db)
    mocker.patch("src.worker.process_job", side_effect=RuntimeError("boom"))

    run_once(_cfg(), _settings())

    db.close.assert_called_once()


def test_worker_is_off_by_default(mocker) -> None:
    mocker.patch.dict("os.environ", {"SHORTS_WORKER_ENABLED": ""}, clear=False)

    assert load_worker_settings().enabled is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE"])
def test_worker_enable_flag_accepts_common_spellings(mocker, value) -> None:
    mocker.patch.dict("os.environ", {"SHORTS_WORKER_ENABLED": value}, clear=False)

    assert load_worker_settings().enabled is True


def test_worker_id_is_unique_per_process(mocker) -> None:
    # locked_by показывает, кто держит задачу; одинаковые имена сделали бы
    # зависшую задачу неотслеживаемой.
    mocker.patch.dict("os.environ", {"RAILWAY_REPLICA_ID": ""}, clear=False)

    assert load_worker_settings().worker_id != load_worker_settings().worker_id


def test_timecode_formats_minutes_and_hours() -> None:
    from src.worker import timecode

    assert timecode(0) == "0:00"
    assert timecode(75_000) == "1:15"
    assert timecode(3_725_000) == "1:02:05"


def test_caption_carries_source_position() -> None:
    # Без таймкода юзер не может ни проверить выбор, ни найти это место
    # в исходнике.
    from src.worker import clip_caption

    caption = clip_caption(Highlight(75_000, 105_000, 0.9, "Заголовок", "Почему цепляет"), 2)

    assert "1:15–1:45" in caption
    assert "#2" in caption
    assert "30 с" in caption
    assert "Заголовок" in caption
    assert "Почему цепляет" in caption


def test_caption_survives_missing_title_and_reason() -> None:
    from src.worker import clip_caption

    caption = clip_caption(Highlight(0, 30_000, 0.5, "", ""), 1)

    assert "0:00–0:30" in caption


def test_clips_are_sent_with_their_timecodes(mocker) -> None:
    db, send, _ = _wire(mocker, _result())

    process_job(_job(), db, _cfg(), _settings())

    caption = send.call_args[0][3]
    assert "0:00–0:25" in caption


def test_summary_lists_every_timecode(mocker) -> None:
    db, _, notify = _wire(mocker, _result(clips=1, highlights=1))

    process_job(_job(), db, _cfg(), _settings())

    summary = notify.call_args[0][2]
    assert "Готово: 1" in summary
    assert "0:00–0:25" in summary
