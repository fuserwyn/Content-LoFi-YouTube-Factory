-- 002: настройки юзера, которые он крутит сам из бота.
--
-- Держим на юзере, а не на загрузке: это предпочтение человека, а не свойство
-- конкретного видео, и переспрашивать его на каждой загрузке незачем.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS max_fragments INTEGER NOT NULL DEFAULT 5
        CHECK (max_fragments BETWEEN 1 AND 20);
