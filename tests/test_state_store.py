from pathlib import Path

from src.state_store import RunRecord, SQLiteStateStore, create_state_store


def test_state_store_tracks_and_clips_order(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = SQLiteStateStore(db_path)

    store.mark_track_used("track_1.mp3")
    store.mark_track_used("track_2.mp3")
    store.mark_clips_used(["clip_a", "clip_b"])

    tracks = store.recent_tracks(5)
    clips = store.recent_clips(5)

    assert len(tracks) == 2
    assert set(tracks) == {"track_1.mp3", "track_2.mp3"}
    assert clips == ["clip_a", "clip_b"]
    store.close()


def test_state_store_saves_run_record(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = SQLiteStateStore(db_path)

    store.save_run(
        RunRecord(
            run_id="run_001",
            status="success",
            track_path="assets/tracks/a.mp3",
            output_path="temp/renders/final.mp4",
            youtube_video_id="abc123",
            error_message="",
            created_at=1710000000,
        )
    )

    cursor = store.conn.cursor()
    cursor.execute("SELECT run_id, status, youtube_video_id FROM runs")
    row = cursor.fetchone()
    store.close()

    assert row["run_id"] == "run_001"
    assert row["status"] == "success"
    assert row["youtube_video_id"] == "abc123"


def test_create_state_store_defaults_to_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = create_state_store(db_path, database_url="")
    try:
        assert isinstance(store, SQLiteStateStore)
    finally:
        store.close()
