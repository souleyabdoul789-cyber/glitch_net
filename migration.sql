-- Normalement INUTILE : server.py applique ces changements tout seul au démarrage.
-- À lancer à la main seulement si les logs Render affichent « Migration échouée ».
ALTER TABLE gsociety_accounts ADD COLUMN suspended_at DATETIME NULL;
ALTER TABLE gsociety_accounts ADD COLUMN cgu_accepted_at DATETIME NULL;
ALTER TABLE gsociety_accounts ADD COLUMN cgu_version VARCHAR(16) NULL;
ALTER TABLE service_posts MODIFY title VARCHAR(255) NOT NULL;
ALTER TABLE service_posts MODIFY body TEXT NOT NULL;
ALTER TABLE service_post_comments MODIFY comment VARCHAR(500) NOT NULL;
ALTER TABLE service_posts ADD COLUMN font_style VARCHAR(16) NULL;
CREATE TABLE IF NOT EXISTS post_media (id INT AUTO_INCREMENT PRIMARY KEY, post_id INT NULL, uploader_id INT NOT NULL, mime VARCHAR(20) NOT NULL, data MEDIUMBLOB NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_post_media_post (post_id));
CREATE TABLE IF NOT EXISTS service_post_comment_likes (comment_id INT NOT NULL, gsociety_id INT NOT NULL, PRIMARY KEY (comment_id, gsociety_id));
