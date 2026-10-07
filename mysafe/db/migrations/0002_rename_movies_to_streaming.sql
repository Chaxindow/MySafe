-- 0002: the default "Movies & Series" category becomes "Streaming" (Netflix, Disney+, ...)

UPDATE categories
SET name = 'Streaming', icon = 'tv'
WHERE name = 'Movies & Series'
  AND NOT EXISTS (SELECT 1 FROM categories WHERE name = 'Streaming');
