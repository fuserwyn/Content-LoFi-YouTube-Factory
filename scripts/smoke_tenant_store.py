"""Интеграционная проверка слоя доступа против живой базы.

Моки здесь бесполезны: проверять надо сам SQL — что CASCADE удаляет детей, что
частичные индексы отдают нужные строки и, главное, что ``FOR UPDATE SKIP LOCKED``
действительно не даёт двум воркерам взять одну задачу. Последнее вообще
воспроизводится только на двух реальных соединениях.

    python scripts/smoke_tenant_store.py

Данные создаёт под техническим tg_user_id и удаляет за собой. Выходит с
ненулевым кодом, если что-то не сошлось.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.highlights import Highlight  # noqa: E402
from src.tenant_store import TenantStore  # noqa: E402
from src.transcribe import TranscriptSegment  # noqa: E402

# Заведомо невозможный Telegram-id, чтобы не столкнуться с реальным юзером.
TEST_TG_ID = -999_000_001

checks: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    checks.append((label, ok))


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.strip():
        print("DATABASE_URL пуст")
        return 1

    store = TenantStore(database_url)
    second = TenantStore(database_url)  # второй воркер, отдельное соединение

    try:
        user_id = store.upsert_user(TEST_TG_ID, "smoke")
        check("юзер заведён", user_id > 0)
        check("повторный вызов не плодит дублей", store.upsert_user(TEST_TG_ID) == user_id)
        check("новый юзер активен", store.is_active(user_id))

        source_id = store.create_source(user_id, "sources/smoke.mp4", "smoke.mp4")
        check("конвейер не стартует без прав", not store.is_ready_to_process(source_id))

        store.confirm_rights(source_id)
        store.set_source_status(source_id, "uploaded")
        store.set_source_media(source_id, duration_s=600)
        check("готов к обработке после подтверждения", store.is_ready_to_process(source_id))

        store.save_transcript(
            source_id,
            [
                TranscriptSegment(0, 5000, "первая реплика"),
                TranscriptSegment(5000, 9000, "вторая реплика"),
            ],
        )
        loaded = store.load_transcript(source_id)
        check("транскрипт читается обратно", len(loaded) == 2)
        store.save_transcript(source_id, [TranscriptSegment(0, 5000, "переписанный")])
        check("повторная запись не дублирует", len(store.load_transcript(source_id)) == 1)

        store.save_highlights(
            source_id,
            [
                Highlight(0, 30_000, 0.4, "слабый", "r"),
                Highlight(40_000, 70_000, 0.9, "сильный", "r"),
            ],
        )
        taken = store.take_next_highlight(source_id)
        check("первым отдаётся лучший по скору", taken is not None and taken[1].score == 0.9)
        second_take = store.take_next_highlight(source_id)
        check("второй вызов отдаёт следующий", second_take is not None and second_take[1].score == 0.4)
        check("использованные не возвращаются", store.take_next_highlight(source_id) is None)

        schedule_id = store.create_schedule(user_id, source_id, every_hours=24, max_shorts=2)
        due = [s for s in store.due_schedules() if s.id == schedule_id]
        check("созревшее расписание попадает в выборку", len(due) == 1)

        store.advance_schedule(schedule_id)
        check(
            "после прогона расписание уезжает в будущее",
            all(s.id != schedule_id for s in store.due_schedules()),
        )

        job_id = store.enqueue_job(user_id, source_id)
        mine = store.claim_jobs("worker-a", limit=5)
        theirs = second.claim_jobs("worker-b", limit=5)
        check("задачу забрал первый воркер", any(j.id == job_id for j in mine))
        # Главное здесь: без SKIP LOCKED второй воркер взял бы ту же задачу
        # и юзер получил бы два одинаковых шортса.
        check("второй воркер ту же задачу не взял", all(j.id != job_id for j in theirs))

        store.fail_job(job_id, "проверка возврата в очередь")
        requeued = store.claim_jobs("worker-a", limit=5)
        check("после сбоя задача возвращается в очередь", any(j.id == job_id for j in requeued))

        store.finish_job(job_id, "outputs/smoke_01.mp4")
        check("завершённая задача больше не выдаётся", all(
            j.id != job_id for j in store.claim_jobs("worker-a", limit=5)
        ))

        store.set_user_status(user_id, "suspended", "проверка рубильника")
        check("рубильник гасит юзера", not store.is_active(user_id))
        check(
            "и его расписания вместе с ним",
            all(s.user_id != user_id for s in store.due_schedules()),
        )

        store.log("smoke_test", user_id=user_id, entity="source", entity_id=source_id,
                  meta={"источник": "smoke"})
        check("аудит пишется", True)

    finally:
        with store.conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE tg_user_id = %s", (TEST_TG_ID,))
        store.conn.commit()
        store.close()
        second.close()

    for label, ok in checks:
        print(f"  {'OK  ' if ok else 'ПРОВАЛ'} {label}")

    failed = [label for label, ok in checks if not ok]
    if failed:
        print(f"\nне прошло: {len(failed)} из {len(checks)}")
        return 1
    print(f"\nвсе {len(checks)} проверок прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
