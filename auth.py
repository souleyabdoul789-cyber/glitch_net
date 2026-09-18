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





