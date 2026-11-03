-- Normalement INUTILE : server.py applique ces changements tout seul au démarrage.
-- À lancer à la main seulement si les logs Render affichent « Migration échouée ».
ALTER TABLE gsociety_accounts ADD COLUMN suspended_at DATETIME NULL;
ALTER TABLE gsociety_accounts ADD COLUMN cgu_accepted_at DATETIME NULL;
ALTER TABLE gsociety_accounts ADD COLUMN cgu_version VARCHAR(16) NULL;
ALTER TABLE service_posts MODIFY title VARCHAR(255) NOT NULL;
ALTER TABLE service_posts MODIFY body TEXT NOT NULL;
ALTER TABLE service_post_comments MODIFY comment VARCHAR(500) NOT NULL;
