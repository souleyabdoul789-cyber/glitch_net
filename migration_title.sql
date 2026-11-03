-- À lancer une fois sur la base MySQL (la colonne est trop courte)
ALTER TABLE service_posts MODIFY title VARCHAR(255) NOT NULL;
