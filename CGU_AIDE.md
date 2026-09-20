# GLITCH — Conditions d'utilisation & Aide

## Qu'est-ce que GLITCH

GLITCH est un réseau social 100% terminal. Pas d'application, pas de navigateur. Chaque utilisateur peut créer ou rejoindre des salons indépendants, comme des groupes séparés — pas une messagerie privée classique.

## Comment démarrer

1. Lance le client : `python glitch_client.py`
2. Crée un compte (pseudo + mot de passe) ou connecte-toi si tu en as déjà un
3. Rejoins un salon existant (`j` pour la liste), ou crée le tien (`n`)
4. Écris, envoie — l'historique du salon te suit tant que tu restes connecté

## Salons éphémères

Un salon peut être créé avec une durée de vie limitée (en secondes). Une fois ce délai écoulé, le salon **et tous ses messages** sont supprimés automatiquement, pour tout le monde — irréversible.

## Règles d'utilisation

- Pas de contenu illégal, pas de harcèlement, pas de diffusion de données personnelles d'autrui sans consentement
- Chaque salon peut avoir ses propres règles supplémentaires, définies par son créateur (admin du salon)
- Le non-respect des règles peut mener à une **suspension de compte**

## Système de suspension (ban)

Si ton compte est suspendu :
- Tu reçois un message explicite à ta prochaine tentative de connexion
- Tu peux **demander un examen** de cette décision — délai de traitement : **24h**
- Contact pour un examen : (à compléter — ton canal Telegram ou autre moyen de contact)

## Vie privée — état actuel du projet

**Important, en toute transparence** : à ce stade (v1), les messages **ne sont pas chiffrés de bout en bout**. Le chiffrement multi-clés est prévu pour une v2 future. Ne partage pas d'informations sensibles en attendant.

Ce qui est déjà en place :
- Aucune IP n'est affichée publiquement aux autres utilisateurs
- Les messages d'un salon éphémère sont définitivement supprimés à expiration

## Canal officiel

Chaîne Telegram : https://t.me/glitch_chanel — annonces, nouveaux salons populaires, mises à jour du projet.

## Problèmes techniques

Si le client n'arrive pas à se connecter :
1. Vérifie que le serveur est bien en ligne
2. Vérifie l'URL configurée dans `glitch_client.py` (`SERVER_URL`)
3. Contacte l'équipe via la chaîne Telegram ci-dessus
