import asyncio, secrets, pymysql, os, bcrypt

def hacher_mot_de_passe(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verifier_mot_de_passe(password: str, hash_stocke: str) -> bool:
    return bcrypt.checkpw(password.encode(), hash_stocke.encode())

def list_all_servers(db, exclure_expires=True):
    with db.cursor() as c:
        if exclure_expires:
            c.execute("SELECT server_name FROM server WHERE expires_at IS NULL OR expires_at > NOW()")
        else:
            c.execute("SELECT server_name FROM server")
        rows = c.fetchall()
    return [r[0] for r in rows]

def list_user_servers(username, db):
    """Salons déjà rejoints par cet utilisateur — pour remplir la sidebar au login."""
    u = check_user(username, db)
    if u is None:
        return []
    user_id = u[0]
    with db.cursor() as c:
        c.execute("""
            SELECT s.server_name FROM server s
            JOIN server_members sm ON sm.server_id = s.id
            WHERE sm.user_id = %s
        """, (user_id,))
        rows = c.fetchall()
    return [r[0] for r in rows]

def create_ephemeral_server(server_name, username, duree_secondes, db):
    try:
        duree_secondes = int(duree_secondes)
        if duree_secondes <= 0:
            return False
    except (TypeError, ValueError):
        return False  # duree absente ou non numérique : on refuse proprement, pas de crash SQL

    c_id = check_user(username, db)
    if c_id is None:
        return False
    creator_id = c_id[0]
    with db.cursor() as c:
        try:
            c.execute(
                "INSERT INTO server(server_name, user_id, expires_at) VALUES(%s, %s, NOW() + INTERVAL %s SECOND)",
                (server_name, creator_id, duree_secondes)
            )
            server_id = c.lastrowid
            c.execute("INSERT INTO server_members(server_id,user_id,role) VALUES(%s,%s,%s)", (server_id, creator_id, "admin"))
            db.commit()
            return True
        except (pymysql.IntegrityError, pymysql.err.OperationalError):
            return False

def delete_e_server(server_name, db):
    s_id = get_server(server_name, db)
    if not s_id:
        return False
    server_id = s_id[0]
    with db.cursor() as c:
        c.execute("DELETE FROM messages WHERE server_id=%s", (server_id,))
        c.execute("DELETE FROM server_members WHERE server_id=%s", (server_id,))
        c.execute("DELETE FROM server WHERE id=%s", (server_id,))
        db.commit()
    return True


def get_user_server(username,db):
    with db.cursor() as c:
        c.execute("""
                  SELECT s.id, s.server_name FROM server s 
                  JOIN server_members sm ON s.id = sm.server_id
                  JOIN user u ON u.id = sm.user_id
                  WHERE username=%s



                  """,(username,))
        return c.fetchall()
def get_db():
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl={"ssl": {}}  # active le SSL requis par Aiven côté pymysql
    )

def ban(username,ip,reason="Violation",db=None):
    u_id = check_user(username,db)
    if not u_id:
        return
    user_id = u_id[0]
    with db.cursor() as c:
        c.execute("SELECT server_id FROM server_members WHERE user_id=%s",(user_id,))
        row = c.fetchall()
        olders_server= ",".join([str(r[0]) for r in row]) if row else ""
        c.execute("INSERT INTO ban(user_id,ip,reason,old_servers) VALUES(%s,%s,%s,%s)",(user_id,ip,reason,olders_server))
        c.execute("DELETE FROM server_members WHERE user_id=%s",(user_id,))
    db.commit()
    return True

def uban_user(username,db=None):
    u_id = check_user(username,db)
    if not u_id:
        return False
    user_id = u_id[0]
    with db.cursor() as c:
        c.execute("SELECT old_servers from ban WHERE user_id=%s ORDER BY id DESC LIMIT 1",(user_id,))
        row = c.fetchone()
        if row is None:
            return False
        old_servers = row[0]
        c.execute("DELETE FROM ban WHERE user_id=%s",(user_id,))
        if old_servers:
            for sid in old_servers.split(","):
                if not sid:
                    continue
                try:
                    c.execute("INSERT INTO server_members(server_id,user_id,role) VALUES(%s,%s,%s)",(int(sid),user_id,"member"))
                except pymysql.IntegrityError:
                    pass  # déjà remis dans ce serveur, ou serveur supprimé entre-temps : on continue les autres
        db.commit()
    return True




def is_ban(username,ip,db=None):
    u_id = check_user(username,db)
    if not u_id:
        return False
    user_id = u_id[0]
    with db.cursor() as c:
        c.execute("SELECT user_id,ip FROM ban WHERE user_id=%s",(user_id,))
        result = c.fetchone()
    if result:
        return True
    else:
        return False




def get_members(server_name,db):
    s_id = get_server(server_name,db)
    if s_id is None:
        return
    server_id = s_id[0]
    with db.cursor() as c:
        c.execute("SELECT  user.username FROM server_members JOIN user ON user.id = server_members.user_id WHERE server_members.server_id=%s",(server_id,))
        resulta = c.fetchall()
        if resulta:
            return [row[0] for row in resulta]
        else:
            return None

def is_member(server_name,username,db):
    u_id = check_user(username,db)
    s_id = get_server(server_name,db)
    if u_id is None or s_id is None:
        return
    server_id = s_id[0]
    user_id = u_id[0]
    with db.cursor() as c:
        c.execute("SELECT * FROM server_members WHERE server_id=%s AND user_id=%s",(server_id,user_id))
        res = c.fetchone()
        if res:
            return res
        else:
            return None

def get_historique(server_name, db, last_id=None, limit=50):
    s_id = get_server(server_name, db)
    if not s_id:
        return [], None
    server_id = s_id[0]

    with db.cursor() as c:
        if last_id is None:
            # premier chargement : les 50 derniers
            c.execute("""
                SELECT m.id, u.username, s.server_name, m.msg, m.date
                FROM messages m
                JOIN user u ON u.id = m.user_id
                JOIN server s ON s.id = m.server_id
                WHERE m.server_id = %s
                ORDER BY m.id DESC LIMIT %s
            """, (server_id, limit))
        else:
            # chargement suivant : 50 AVANT last_id
            c.execute("""
                SELECT m.id, u.username, s.server_name, m.msg, m.date
                FROM messages m
                JOIN user u ON u.id = m.user_id
                JOIN server s ON s.id = m.server_id
                WHERE m.server_id = %s AND m.id < %s
                ORDER BY m.id DESC LIMIT %s
            """, (server_id, last_id, limit))

        rows = c.fetchall()
        if not rows:
            return [], None

        # on prépare le next_cursor
        next_cursor = rows[-1][0] # l'id le plus vieux qu'on vient de charger

        historique = []
        for msg_id, username, server_name, msg, date in reversed(rows):
            historique.append({
                "id": msg_id,
                "user": username,
                "server": server_name,
                "msg": msg,
                "date": date.strftime("%H:%M:%S %d/%m/%Y")
            })
        return historique, next_cursor

def save_msg(server_name,username,content,db):
    u_id = check_user(username,db)
    s_id = get_server(server_name,db)
    if u_id is None or s_id is None:
        return None
    server_id = s_id[0]
    user_id = u_id[0]
    with db.cursor() as c:
        try:
            c.execute("""INSERT INTO messages(user_id,server_id,msg) VALUES(%s,%s,%s)""",(user_id,server_id,content))
            db.commit()
            return True
        except pymysql.IntegrityError:
            return False
    return True





def create_server(server_name,username,db):
    c_id = check_user(username,db)
    if c_id is None:
        return False
    creator_id = c_id[0]
    with db.cursor() as c:
        try:
            c.execute("INSERT INTO server(server_name,user_id) VALUES(%s,%s)",(server_name,creator_id))
            server_id = c.lastrowid
            c.execute("INSERT INTO server_members(server_id,user_id,role) VALUES(%s,%s,%s)",(server_id,creator_id,"admin"))
            db.commit()
            return True
        except pymysql.IntegrityError:
            return False

def get_server(server_name,db):
    result = None
    with db.cursor() as c:
        try:
            c.execute("SELECT id,server_name FROM server WHERE server_name=%s",(server_name,))
            result = c.fetchone()
        except pymysql.IntegrityError:
            print("Error")
    return result

def join_server(server_name,username,db):
    s_id = get_server(server_name,db)
    u_id = check_user(username,db)
    if s_id and u_id is not None:
        server_id = s_id[0]
        user_id = u_id[0]
        with db.cursor() as c:
            try:
                c.execute("INSERT INTO server_members(server_id,user_id,role) VALUES(%s,%s,%s)",(server_id,user_id,"member"))
                db.commit()
                return True
            except pymysql.IntegrityError:
                return False
    else:
        return False



def create(username,password,public_key,db):
    token = secrets.token_hex(32)
    pwd_hash = hacher_mot_de_passe(password)
    with db.cursor() as c:
        try:
            c.execute("INSERT INTO user (username,password,token,public_key) VALUES(%s,%s,%s,%s)",(username,pwd_hash,token,public_key))
            db.commit()
            return True
        except pymysql.IntegrityError:
            return False

def check_user(username,db):
    with db.cursor() as c:
        c.execute("SELECT id,username,token,public_key FROM user WHERE username=%s",(username,))
        result = c.fetchone()
    if result:
        return result
    return None


def login(username,password,db):
    with db.cursor() as c:
        c.execute("SELECT id,username,password FROM user WHERE username=%s",(username,))
        row = c.fetchone()
        if not row:
            return None
        if verifier_mot_de_passe(password,row[2]):
            return row
        else:
            return None





# ============================================================
# Comptes G-SOCIETY — la société mère. Indépendant du compte
# GLITCH : un compte G-SOCIETY sert à obtenir des clés API pour
# accéder aux services (GLITCH aujourd'hui, d'autres plus tard).
# ============================================================
import hashlib
from datetime import datetime, timedelta

def creer_compte_gsociety(username, password, avatar_id, db):
    pwd_hash = hacher_mot_de_passe(password)
    with db.cursor() as c:
        try:
            c.execute(
                "INSERT INTO gsociety_accounts (username,password,avatar_id) VALUES (%s,%s,%s)",
                (username, pwd_hash, avatar_id)
            )
            db.commit()
            return True
        except pymysql.IntegrityError:
            return False


def login_gsociety(username, password, db):
    with db.cursor() as c:
        c.execute("SELECT id,username,password,avatar_id FROM gsociety_accounts WHERE username=%s", (username,))
        row = c.fetchone()
    if row is None:
        return None
    if verifier_mot_de_passe(password, row[2]):
        return row
    return None


# ============================================================
# Session — après connexion, un jeton évite de redemander le
# mot de passe à chaque action (ex: générer une clé).
# ============================================================
def creer_session(gsociety_id, db, duree_jours=30):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expiration = datetime.now() + timedelta(days=duree_jours)
    with db.cursor() as c:
        c.execute(
            "INSERT INTO gsociety_sessions (gsociety_id, token_hash, expires_at) VALUES (%s,%s,%s)",
            (gsociety_id, token_hash, expiration)
        )
        db.commit()
    return token


def verifier_session(token, db):
    """Renvoie (id, username, avatar_id) si le jeton est valide, sinon None."""
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db.cursor() as c:
        c.execute("""
            SELECT g.id, g.username, g.avatar_id FROM gsociety_sessions s
            JOIN gsociety_accounts g ON g.id = s.gsociety_id
            WHERE s.token_hash = %s AND s.expires_at > NOW()
        """, (token_hash,))
        row = c.fetchone()
    return row


# ============================================================
# Clés API — émises par G-SOCIETY, catégorisées par service
# ("glitch" pour l'instant). Une clé prouve un accès légitime au
# service, elle n'est pas liée 1:1 à un compte GLITCH précis.
# ============================================================
def generer_api_key(gsociety_username, db, categorie="glitch", duree_jours=90):
    """Génère une clé ght_xxxx, hachée avant stockage (jamais en clair
    en base). Limité à 1 génération tous les 3 jours, par catégorie."""
    with db.cursor() as c:
        c.execute("SELECT id FROM gsociety_accounts WHERE username=%s", (gsociety_username,))
        compte = c.fetchone()
    if compte is None:
        return {"ok": False, "error": "Compte G-SOCIETY introuvable"}
    gsociety_id = compte[0]

    with db.cursor() as c:
        c.execute(
            "SELECT created_at FROM api_keys WHERE gsociety_id=%s AND categorie=%s ORDER BY created_at DESC LIMIT 1",
            (gsociety_id, categorie)
        )
        derniere = c.fetchone()
    if derniere is not None:
        prochaine_dispo = derniere[0] + timedelta(days=3)
        if datetime.now() < prochaine_dispo:
            attente = prochaine_dispo - datetime.now()
            heures = int(attente.total_seconds() // 3600)
            return {"ok": False, "error": f"Une clé '{categorie}' a déjà été générée récemment. Réessaie dans environ {heures}h."}

    duree_jours = max(1, min(int(duree_jours), 90))
    suffixe_service = categorie[:3].lower()  # ex: "glt" pour glitch — visible à l'oeil, identifie le service
    cle_brute = "ght_" + secrets.token_urlsafe(28) + "_" + suffixe_service
    cle_hash = hashlib.sha256(cle_brute.encode()).hexdigest()
    expiration = datetime.now() + timedelta(days=duree_jours)

    with db.cursor() as c:
        c.execute(
            "INSERT INTO api_keys (gsociety_id, categorie, key_hash, expires_at) VALUES (%s,%s,%s,%s)",
            (gsociety_id, categorie, cle_hash, expiration)
        )
        db.commit()
    return {"ok": True, "api_key": cle_brute, "categorie": categorie, "expires_in_days": duree_jours}


def verifier_api_key(cle, db, categorie_attendue="glitch"):
    """True si la clé est valide, pas expirée, et de la bonne catégorie.
    Ne renvoie pas d'identité GLITCH — la clé prouve un droit d'accès
    au service, pas une identité GLITCH précise."""
    if not cle or not cle.startswith("ght_"):
        return False
    cle_hash = hashlib.sha256(cle.encode()).hexdigest()
    with db.cursor() as c:
        c.execute(
            "SELECT id FROM api_keys WHERE key_hash=%s AND categorie=%s AND expires_at > NOW()",
            (cle_hash, categorie_attendue)
        )
        row = c.fetchone()
    return row is not None


def verifier_api_key_identite(cle, db, categorie_attendue):
    """Comme verifier_api_key, mais renvoie le username G-SOCIETY réel
    propriétaire de la clé (ou None). Pour les services externes (GRIND,
    et les suivants) qui ne doivent JAMAIS faire confiance à un username
    fourni par le client — une seule clé ne doit pouvoir désigner qu'une
    seule identité, jamais celle que le client prétend être."""
    if not cle or not cle.startswith("ght_"):
        return None
    cle_hash = hashlib.sha256(cle.encode()).hexdigest()
    with db.cursor() as c:
        c.execute("""
            SELECT g.username FROM api_keys ak
            JOIN gsociety_accounts g ON g.id = ak.gsociety_id
            WHERE ak.key_hash=%s AND ak.categorie=%s AND ak.expires_at > NOW()
        """, (cle_hash, categorie_attendue))
        row = c.fetchone()
    return row[0] if row else None


# ============================================================
# Blocage IP permanent — remplace définitivement les listes
# temporaires en mémoire (BAN_LIST / KEY_VIOLATION_IPS).
# ============================================================
def bloquer_ip(ip, reason, db):
    with db.cursor() as c:
        try:
            c.execute("INSERT INTO blocked_ips (ip, reason) VALUES (%s,%s)", (ip, reason))
            db.commit()
        except pymysql.IntegrityError:
            pass  # déjà bloquée, rien à faire


def est_ip_bloquee(ip, db):
    with db.cursor() as c:
        c.execute("SELECT 1 FROM blocked_ips WHERE ip=%s", (ip,))
        return c.fetchone() is not None


# ============================================================
# Vérification de propriété d'un serveur — le point de sécurité
# central pour toute demande de suppression via la plateforme web
# ============================================================
def est_admin_du_serveur(username, server_name, db):
    """True seulement si `username` a le rôle 'admin' sur CE serveur
    précis. Renvoie aussi un statut pour distinguer les cas d'erreur."""
    s = get_server(server_name, db)
    if s is None:
        return "server_not_found"
    server_id = s[0]
    u = check_user(username, db)
    if u is None:
        return "user_not_found"
    user_id = u[0]
    with db.cursor() as c:
        c.execute(
            "SELECT role FROM server_members WHERE server_id=%s AND user_id=%s",
            (server_id, user_id)
        )
        row = c.fetchone()
    if row is None:
        return "not_a_member"
    if row[0] != "admin":
        return "not_admin"
    return "ok"


def supprimer_serveur_definitivement(server_name, db):
    s = get_server(server_name, db)
    if s is None:
        return False
    delete_e_server(server_name, db)
    return True


# ============================================================
# Signalements — anonymes vis-à-vis des autres utilisateurs,
# mais tracés pour l'admin (username du rapporteur conservé
# côté serveur, jamais affiché publiquement).
# ============================================================
def creer_signalement(type_, reporter_username, target, motif, details, db):
    with db.cursor() as c:
        c.execute(
            "INSERT INTO reports (type, reporter_username, target, motif, details) VALUES (%s,%s,%s,%s,%s)",
            (type_, reporter_username, target, motif, details)
        )
        db.commit()


def lister_signalements(db, statut="pending"):
    with db.cursor() as c:
        c.execute(
            "SELECT id, type, reporter_username, target, motif, details, created_at FROM reports WHERE status=%s ORDER BY id DESC",
            (statut,)
        )
        rows = c.fetchall()
    return rows


def resoudre_signalement(report_id, nouveau_statut, db):
    with db.cursor() as c:
        c.execute("UPDATE reports SET status=%s WHERE id=%s", (nouveau_statut, report_id))
        db.commit()
