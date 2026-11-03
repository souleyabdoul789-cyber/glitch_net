"""Sécurité de Pluton : validation des entrées, limitation de débit,
migrations idempotentes et en-têtes HTTP. Aucun état en base nécessaire
pour le limiteur (mémoire du process : suffisant pour une seule instance
Render ; à déplacer en base si on passe à plusieurs instances)."""
import re, time, logging
from collections import defaultdict, deque
from fastapi.responses import JSONResponse

log = logging.getLogger("pluton.security")

# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
NOMS_RESERVES = {
    "admin", "administrator", "root", "system", "support", "moderateur", "moderator",
    "gsociety", "g-society", "g_society", "pluton", "glitch", "grind", "staff", "officiel",
    "official", "equipe", "team", "null", "undefined", "anonymous", "anonyme",
}
MOTS_DE_PASSE_FAIBLES = {
    "password", "motdepasse", "12345678", "123456789", "1234567890", "azertyui", "azerty123",
    "qwertyui", "qwerty123", "password1", "00000000", "11111111", "iloveyou", "abcd1234",
}
SERVICES = {"glitch", "grind"}
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-+_]{0,31}$")


def valider_username(username: str):
    """Renvoie un message d'erreur, ou None si le nom est valide."""
    if not USERNAME_RE.match(username or ""):
        return "Identifiant : 3 à 20 caractères (lettres, chiffres, point, tiret, underscore)."
    bas = username.lower()
    if bas in NOMS_RESERVES or bas.replace("-", "").replace("_", "").replace(".", "") in NOMS_RESERVES:
        return "Cet identifiant est réservé."
    return None


def valider_mot_de_passe(password: str, username: str = ""):
    if password is None or len(password) < 8:
        return "Le mot de passe doit contenir au moins 8 caractères."
    if len(password.encode("utf-8")) > 72:
        return "Mot de passe trop long (72 octets maximum)."
    if password.lower() in MOTS_DE_PASSE_FAIBLES or (username and password.lower() == username.lower()):
        return "Mot de passe trop facile à deviner."
    if len(set(password)) < 4:
        return "Mot de passe trop répétitif."
    return None


def url_https_valide(url: str, max_len: int = 500) -> bool:
    """Seuls les liens https:// sont acceptés (bloque javascript:, data:, http:)."""
    if not url or len(url) > max_len or any(ch.isspace() for ch in url):
        return False
    return bool(re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?(/[^\s<>\"']*)?$", url))


# ------------------------------------------------------------------
# Limiteur de débit (fenêtre glissante, en mémoire)
# ------------------------------------------------------------------
class Limiteur:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._dernier_menage = time.time()

    def _menage(self, maintenant):
        if maintenant - self._dernier_menage < 300:
            return
        self._dernier_menage = maintenant
        for k in [k for k, d in self._hits.items() if not d or maintenant - d[-1] > 86400]:
            del self._hits[k]

    def autorise(self, cle: str, limite: int, fenetre_s: int) -> bool:
        """Enregistre un essai ; False si la limite est dépassée."""
        now = time.time()
        self._menage(now)
        d = self._hits[cle]
        while d and now - d[0] > fenetre_s:
            d.popleft()
        if len(d) >= limite:
            return False
        d.append(now)
        return True

    def compte(self, cle: str, fenetre_s: int) -> int:
        now = time.time()
        d = self._hits.get(cle)
        if not d:
            return 0
        while d and now - d[0] > fenetre_s:
            d.popleft()
        return len(d)

    def enregistre(self, cle: str):
        self._hits[cle].append(time.time())

    def oublie(self, cle: str):
        self._hits.pop(cle, None)


limiteur = Limiteur()
MSG_TROP_DE_REQUETES = "Trop de tentatives. Patientez quelques minutes avant de réessayer."


def ip_client(request) -> str:
    return request.client.host if request.client else "inconnue"


# ------------------------------------------------------------------
# Migrations idempotentes : lancées au démarrage, sans action manuelle
# ------------------------------------------------------------------
def _colonne(c, table, colonne):
    c.execute(
        "SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, colonne),
    )
    return c.fetchone()


def migrer_schema(db):
    etapes = []
    with db.cursor() as c:
        for col, ddl in (
            ("suspended_at", "DATETIME NULL"),
            ("cgu_accepted_at", "DATETIME NULL"),
            ("cgu_version", "VARCHAR(16) NULL"),
        ):
            if _colonne(c, "gsociety_accounts", col) is None:
                etapes.append(f"ALTER TABLE gsociety_accounts ADD COLUMN {col} {ddl}")

        info = _colonne(c, "service_posts", "title")
        if info and info[0] == "varchar" and (info[1] or 0) < 255:
            etapes.append("ALTER TABLE service_posts MODIFY title VARCHAR(255) NOT NULL")
        info = _colonne(c, "service_posts", "body")
        if info and info[0] == "varchar":
            etapes.append("ALTER TABLE service_posts MODIFY body TEXT NOT NULL")
        info = _colonne(c, "service_post_comments", "comment")
        if info and info[0] == "varchar" and (info[1] or 0) < 500:
            etapes.append("ALTER TABLE service_post_comments MODIFY comment VARCHAR(500) NOT NULL")

        for sql in etapes:
            try:
                c.execute(sql)
                log.warning("Migration appliquée : %s", sql)
            except Exception as e:  # une migration ratée ne doit pas empêcher le démarrage
                log.error("Migration échouée (%s) : %s", sql, e)
        db.commit()
        try:  # ménage : sessions expirées
            c.execute("DELETE FROM gsociety_sessions WHERE expires_at < NOW()")
            db.commit()
        except Exception as e:
            log.error("Nettoyage des sessions impossible : %s", e)
    return etapes


# ------------------------------------------------------------------
# Middleware : en-têtes de sécurité + erreurs internes en JSON propre
# ------------------------------------------------------------------
async def securite_middleware(request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Erreur interne sur %s %s", request.method, request.url.path)
        response = JSONResponse(
            {"success": False, "error": "Erreur interne du serveur. Réessayez dans un instant."},
            status_code=500,
        )
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "no-referrer"
    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
        h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        h["X-Frame-Options"] = "DENY"
    return response
