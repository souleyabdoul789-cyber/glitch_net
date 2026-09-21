import asyncio, os
from fastapi import FastAPI,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from auth import *
from datetime import datetime
import time
from pydantic import BaseModel
serveur_ephemere_token = {}
app = FastAPI()

# Le site G-SOCIETY vit sur un domaine Render différent de Pluton — sans
# CORS, le navigateur bloquerait tout appel fetch() entre les deux.
# ⚠️ Remplace "*" par l'URL exacte du site G-SOCIETY une fois connue,
# plus strict pour la prod (ex: ["https://g-society-xxxx.onrender.com"]).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/status")
async def status_page():
    """Ancienne page de statut (pluie Matrix) — utile pour vérifier que
    le process tourne, séparée du vrai site maintenant."""
    html = """<!DOCTYPE html>
<html><head><title>GLITCH — status</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#0f0;font-family:'Courier New',monospace;height:100vh;overflow:hidden}
canvas{position:fixed;top:0;left:0;z-index:0}
.msg{position:relative;z-index:1;height:100vh;display:flex;flex-direction:column;
     align-items:center;justify-content:center;text-align:center}
.msg h1{font-size:3rem;letter-spacing:0.3rem;text-shadow:0 0 12px #0f0}
.msg p{margin-top:0.5rem;opacity:0.85}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;
     background:#0f0;box-shadow:0 0 8px #0f0;margin-right:8px;
     animation:pulse 1.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
</style></head>
<body>
<canvas id="c"></canvas>
<div class="msg">
  <h1>GLITCH</h1>
  <p><span class="dot"></span>server online — anonymous — encrypted (v2)</p>
</div>
<script>
const c=document.getElementById('c'),ctx=c.getContext('2d');
function resize(){c.width=innerWidth;c.height=innerHeight}
resize(); addEventListener('resize',resize);
const chars="アイウエオカキクケコサシスセソ0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const size=16;
let cols=Math.floor(c.width/size);
let drops=Array(cols).fill(1);
function draw(){
  ctx.fillStyle="rgba(0,0,0,0.08)";ctx.fillRect(0,0,c.width,c.height);
  ctx.fillStyle="#0f0";ctx.font=size+"px monospace";
  drops.forEach((y,i)=>{
    const ch=chars[Math.floor(Math.random()*chars.length)];
    ctx.fillText(ch,i*size,y*size);
    if(y*size>c.height && Math.random()>0.975) drops[i]=0;
    drops[i]++;
  });
}
setInterval(draw,45);
</script>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/")
async def racine():
    """Pluton n'affiche plus de pages — juste une confirmation JSON que
    l'API/WebSocket tourne. Le site G-SOCIETY vit sur un service séparé
    et appelle ces routes par le réseau."""
    return {"status": "Pluton en ligne", "services": ["glitch"]}


# ============================================================
# API de la plateforme web — HTTP classique (pas WebSocket),
# c'est un navigateur qui appelle ça, pas le client terminal.
# ============================================================
class CompteGSociety(BaseModel):
    username: str
    password: str

class InscriptionGSociety(BaseModel):
    username: str
    password: str
    avatar_id: int

@app.post("/api/gsociety/signup")
async def api_gsociety_signup(data: InscriptionGSociety):
    db = get_db()
    ok = creer_compte_gsociety(data.username, data.password, data.avatar_id, db)
    db.close()
    if not ok:
        return {"success": False, "error": "Ce nom de compte est déjà pris"}
    return {"success": True, "message": "Compte créé avec succès"}


@app.post("/api/gsociety/login")
async def api_gsociety_login(data: CompteGSociety):
    db = get_db()
    req = login_gsociety(data.username, data.password, db)
    db.close()
    if req is None:
        return {"success": False, "error": "Identifiants incorrects"}
    return {"success": True, "message": "Connexion réussie", "username": req[1], "avatar_id": req[3]}


class DemandeCle(BaseModel):
    username: str    # identifiants G-SOCIETY, pas GLITCH
    password: str
    categorie: str = "glitch"
    duree_jours: int = 90

@app.post("/api/request-key")
async def api_request_key(data: DemandeCle):
    db = get_db()
    req = login_gsociety(data.username, data.password, db)
    if req is None:
        db.close()
        return {"success": False, "error": "Identifiants G-SOCIETY incorrects"}
    resultat = generer_api_key(data.username, db, categorie=data.categorie, duree_jours=data.duree_jours)
    db.close()
    if not resultat["ok"]:
        return {"success": False, "error": resultat["error"]}
    return {"success": True, "api_key": resultat["api_key"], "categorie": resultat["categorie"], "expires_in_days": resultat["expires_in_days"]}


class Signalement(BaseModel):
    api_key: str
    glitch_username: str  # le compte GLITCH au nom duquel le signalement est fait
    type: str  # "user" ou "bug"
    target: str | None = None
    motif: str
    details: str | None = None

@app.post("/api/report")
async def api_report(data: Signalement):
    db = get_db()
    if not verifier_api_key(data.api_key, db, categorie_attendue="glitch"):
        db.close()
        return {"success": False, "error": "Clé API invalide ou expirée. Demande-en une nouvelle sur /report"}
    if data.type not in ("user", "bug"):
        db.close()
        return {"success": False, "error": "Type de signalement invalide"}
    creer_signalement(data.type, data.glitch_username, data.target, data.motif, data.details, db)
    db.close()
    return {"success": True, "message": "Signalement transmis à l'équipe. Merci."}


class SuppressionServeur(BaseModel):
    api_key: str
    glitch_username: str  # doit être l'admin/créateur du serveur ciblé
    server_name: str
    motif: str | None = None

@app.post("/api/delete-server")
async def api_delete_server(data: SuppressionServeur):
    db = get_db()
    if not verifier_api_key(data.api_key, db, categorie_attendue="glitch"):
        db.close()
        return {"success": False, "error": "Clé API invalide ou expirée. Demande-en une nouvelle sur /report"}

    statut = est_admin_du_serveur(data.glitch_username, data.server_name, db)

    if statut == "server_not_found":
        db.close()
        return {"success": False, "error": f"Le serveur '{data.server_name}' n'existe pas"}
    if statut in ("not_a_member", "not_admin", "user_not_found"):
        db.close()
        return {"success": False, "error": "Tu dois être l'admin/créateur de ce serveur pour le supprimer"}

    # statut == "ok" : suppression réelle, on prévient les membres avant
    pa = await payload(type="e-expired", msg=f"{data.server_name} a été supprimé par son créateur")
    await send_in_server(data.server_name, pa)
    supprimer_serveur_definitivement(data.server_name, db)
    db.close()
    return {"success": True, "message": f"Serveur '{data.server_name}' supprimé définitivement"}


class AdminManager:
    def __init__(self):
        self.admin_aliive: dict[str,WebSocket] = {}
    async def conn_admin(self,admin_name,ws: WebSocket):
        self.admin_aliive[admin_name] = ws
    async def disco_admin(self,admin_name):
        self.admin_aliive.pop(admin_name,None)
    async def send_to_admin(self,msg:dict):
        for ws in self.admin_aliive.values():
            await ws.send_json(msg)
    async def send(self,admin_name,msg: dict,ws: WebSocket):
        await self.admin_aliive[admin_name].send_json(msg)


    
        
admin_manager = AdminManager()
class ConnexionManager:
    def __init__(self):
        self.user_alive: dict[str,WebSocket] = {}
    async def connect(self,username:str, wsb:WebSocket):
        self.user_alive[username] = wsb
    def disconnect(self,username):
        self.user_alive.pop(username,None)
    async def send_to(self,username:str,message: dict):
        if username in self.user_alive:
            await self.user_alive[username].send_json(message)
    async def BAN(self,username,ip,server_name,db):
        ban(username=username,ip=ip,db=db)  # toujours enregistré en DB, connecté ou non

        if username in self.user_alive:
            pa = await payload(type="BAN",statut="666",msg="Ce Compte Ne peut plus utilisée Glitch les activités ressens ne respecte pas Nos conditions d'utilisation, Vous Pouvez Demandé Un examen les examen prennent 24h Nous vous prie de patientez")
            await self.user_alive[username].send_json(pa)
            await self.user_alive[username].close(code=1008)
            self.disconnect(username)
            await disconnect_notif(username,server_name)

        date = datetime.now()
        pa_admin = await payload(type="new_ban",username=username,server_name=server_name,date=str(date),raison="Violation Des regles")
        await admin_manager.send_to_admin(pa_admin)
manager = ConnexionManager()

async def send_in_server(server_name,message:dict,exclure:str =None):
    db = get_db()
    members = get_members(server_name,db)
    db.close()
    if members is None:
        return False
    for username in members:
        if username == exclure:
            continue
        await manager.send_to(username,message)

async def payload(**kwargs):
    return kwargs
async def notif_all(msg:dict):
    for ws in manager.user_alive.values():
        await ws.send_json(msg)
async def join_notif(username,server_name):
    pa = await payload(type="notif",event="joined",username=username,msg=f"{username} Vient De Rejoindre La discussion Soyez Sympa avec lui")
    await send_in_server(server_name,pa,exclure=None)

async def disconnect_notif(username,server_name):
    db = get_db()
    pa = await payload(type="offline",msg=f"{username} Vient de se DECONECTÉE")
    _server = get_user_server(username,db)
    db.close()
    if not _server:
        return
    for s_id,s_name in _server:
        await send_in_server(s_name,pa,exclure=None)

async def result(c_result=None,statut=None,msg=None):
    data = {"type": c_result,"statut": statut,"msg":msg}
    return data
async def nettoyer_serveurs_expires():
    while True:
        await asyncio.sleep(60)
        db = get_db()
        with db.cursor() as c:
            c.execute("SELECT server_name FROM server WHERE expires_at IS NOT NULL AND expires_at <= NOW()")
            expires = c.fetchall()
        for (server_name,) in expires:
            pa = await payload(type="e-expired", msg=f"{server_name} a expiré et a été supprimé")
            await send_in_server(server_name, pa)
            delete_e_server(server_name, db)
        db.close()

@app.on_event("startup")
async def startup():
    asyncio.create_task(nettoyer_serveurs_expires())

@app.websocket("/ws/glitch")
async def glitch(ws: WebSocket):
    db = get_db()
    ip = ws.client.host

    if est_ip_bloquee(ip, db):
        await ws.close(code=1008)
        db.close()
        return

    await ws.accept()

    username = None

    try:
        while True:
            rep = await ws.receive_json()
            type_ = rep.get("type")

            # --- Pas encore authentifié : seules "signup"/"login" sont acceptées ---
            if username is None:
                if type_ not in ("signup", "login"):
                    data = await result(c_result="error", statut="401", msg="Vous devez d'abord vous inscrire ou vous connecter")
                    await ws.send_json(data)
                    continue

                # 3 champs obligatoires dans les deux cas : username, password, api_key.
                # La clé prouve un accès légitime au service "glitch", délivrée par
                # G-SOCIETY — plus aucune clé de script partagée.
                api_key = rep.get("api_key")
                if not verifier_api_key(api_key, db, categorie_attendue="glitch"):
                    data = await result(c_result="key_error", statut="345", msg="Clé API invalide, expirée, ou absente. Génère-en une sur https://glitch-wbfo.onrender.com/report (compte G-SOCIETY requis)")
                    await ws.send_json(data)
                    bloquer_ip(ip, "Clé API invalide au signup/login", db)
                    await ws.close(code=1008)
                    db.close()
                    return

                if type_ == "signup":
                    u = rep.get("username")
                    password = rep.get("password")
                    public_key = rep.get("public_key")

                    resulta = create(u, password, public_key, db)
                    if resulta:
                        data = await result(
                            c_result="c_result", statut="900",
                            msg=f"Votre compte à été créé avec succès...!, vous pouvez à présent rejoindre ou créé un serveur N'oublie pas de visiter notre canal télégram https://t.me/glitch_chanel pour consulter les serveur les plus populaires ✨"
                        )
                        await ws.send_json(data)
                        username = u
                        await manager.connect(username, ws)
                    else:
                        data = await result(c_result="c_result", statut="405", msg=f"Nous sommes désolés Il semble que ce {u} est déjà pris ou une erreur de notre part")
                        await ws.send_json(data)

                elif type_ == "login":
                    u = rep.get("username")
                    password = rep.get("password")

                    if is_ban(u, ip, db):
                        pa = await payload(type="BAN", statut="666", msg="Ce Compte Ne peut plus utilisée Glitch les activités ressens ne respecte pas Nos conditions d'utilisation, Vous Pouvez Demandé Un examen les examen prennent 24h Nous vous prie de patientez")
                        await ws.send_json(pa)
                        await ws.close(code=1008)
                        db.close()
                        return

                    req = login(u, password, db)
                    if req is None:
                        data = await result(c_result="l_result", statut="405", msg="username ou password incorrect veuillez réessayer..!")
                        await ws.send_json(data)
                        continue

                    data = await result(c_result="l_result", statut="900", msg="Vous Etes à nouveau Connecter")
                    await ws.send_json(data)
                    username = u
                    await manager.connect(username, ws)

                continue

            if type_ == "create_room":
                server_name = rep.get("server_name")
                server_type = rep.get("server_type")
                duree = rep.get("duree")
                if server_type == "ephemere":
                    ok = create_ephemeral_server(server_name, username, duree, db)
                else:
                    ok = create_server(server_name, username, db)
                if ok:
                    pa = await payload(type="created", server_name=server_name, msg=f"Serveur {server_name} créé avec succès")
                    await ws.send_json(pa)
                elif server_type == "ephemere":
                    pa = await payload(type="error", statut="400", msg="Nom déjà pris ou durée invalide (envoie 'duree' en secondes, un nombre positif)")
                    await ws.send_json(pa)
                else:
                    pa = await payload(type="error", statut="400", msg="Ce nom de serveur existe déjà")
                    await ws.send_json(pa)
                
            elif type_ == "join_room":
                server_name = rep.get("server_name")
                if join_server(server_name, username, db):
                    await join_notif(username, server_name)
                    pa = await payload(type="join", server_name=server_name, msg=f"Vous Avez Rejoins {server_name} N'oubliez pas Notre Chaine telgram https://t.me/glitch_chanel")
                    await ws.send_json(pa)
                else:
                    pa = await payload(type="JoinError", msg="Nom du serveur Incorect Veuillez Vous Assurez de Taper Le bon Nom ou consulter Notre Chaine pour plus d'info https://t.me/glitch_chanel")
                    await ws.send_json(pa)

            elif type_ == "list_rooms":
                rooms = list_all_servers(db)
                pa = await payload(type="rooms_list", rooms=rooms)
                await ws.send_json(pa)

            elif type_ == "my_rooms":
                rooms = list_user_servers(username, db)
                pa = await payload(type="my_rooms_list", rooms=rooms)
                await ws.send_json(pa)

            elif type_ == "switch_room":
                server_name = rep.get("server_name")
                if not is_member(server_name, username, db):
                    pa = await payload(type="error", statut="403", msg="Tu n'es pas membre de ce salon")
                    await ws.send_json(pa)
                    continue
                last_id = rep.get("last_id")

                hist,next_cursor = get_historique(server_name,db,last_id,50)
                pa = await payload(type="history", server_name=server_name, messages=hist,next_cursor=next_cursor)
                await ws.send_json(pa)

            elif type_ == "message":
                server_name = rep.get("server_name")
                contenu = rep.get("contenu")

                if not is_member(server_name, username, db):
                    pa = await payload(type="error", statut="403", msg="Tu n'es pas membre de ce salon")
                    await ws.send_json(pa)
                    continue

                save_msg(server_name, username, contenu, db)
                pa = await payload(type="message", server_name=server_name, sender=username, contenu=contenu)
                await send_in_server(server_name, pa, exclure=username)

            else:
                pa = await payload(type="error", statut="400", msg=f"Type inconnu : {type_}")
                await ws.send_json(pa)

    except WebSocketDisconnect:
        if username:
            manager.disconnect(username)
            await disconnect_notif(username, None)
    finally:
        db.close()

sys_key = os.getenv("SYS_KEY")

@app.websocket("/ws/glitch/system")
async def system(ws: WebSocket):
    ip = ws.client.host
    db = get_db()
    if est_ip_bloquee(ip, db):
        db.close()
        await ws.close(code=1008)
        return

    await ws.accept()

    rep = await ws.receive_json()
    if not rep:
        db.close()
        return

    key_sys = rep.get("key_sys")
    if key_sys != sys_key:
        pa = await payload(type="sy_key_error",statut="888",msg="KeyError")
        await ws.send_json(pa)
        bloquer_ip(ip, "Mauvaise clé système sur /system", db)
        db.close()
        await ws.close(code=1008)
        return

    admin_ = rep.get("name")
    if rep.get("password") != sys_key:
        pa = await payload(type="PassError",statut="306",msg="Mot de passe Incorect ")
        await ws.send_json(pa)
        await ws.close()
        return

    await admin_manager.conn_admin(admin_,ws)
    db.close()  # la vérification initiale est finie ; chaque commande ouvre sa propre db plus bas

    try:
        while True:
            req = await ws.receive_json()
            cmd = req.get("type")

            if cmd == "broadcast":
                msg = req.get("msg")
                pa = await payload(type="admin_notif", msg=msg)
                await notif_all(pa)
                ack = await payload(type="ack", msg=f"Notification envoyée à {len(manager.user_alive)} utilisateur(s) connecté(s)")
                await ws.send_json(ack)

            elif cmd == "ban":
                username = req.get("username")
                ip = req.get("ip")
                server_name = req.get("server_name")
                db = get_db()
                await manager.BAN(username, ip, server_name, db)
                db.close()
                ack = await payload(type="ack", msg=f"{username} banni")
                await ws.send_json(ack)

            elif cmd == "unban":
                username = req.get("username")
                db = get_db()
                ok = uban_user(username, db)
                db.close()
                ack = await payload(type="ack", msg=f"{username} débanni" if ok else "Aucun ban trouvé pour cet utilisateur")
                await ws.send_json(ack)

            elif cmd == "list_reports":
                db = get_db()
                rows = lister_signalements(db, statut=req.get("statut", "pending"))
                db.close()
                reports = [
                    {"id": r[0], "type": r[1], "reporter": r[2], "target": r[3], "motif": r[4], "details": r[5], "date": str(r[6])}
                    for r in rows
                ]
                pa = await payload(type="reports_list", reports=reports)
                await ws.send_json(pa)

            elif cmd == "resolve_report":
                db = get_db()
                resoudre_signalement(req.get("report_id"), req.get("statut", "resolved"), db)
                db.close()
                ack = await payload(type="ack", msg=f"Signalement #{req.get('report_id')} marqué {req.get('statut','resolved')}")
                await ws.send_json(ack)

            else:
                err = await payload(type="error", msg=f"Commande admin inconnue : {cmd}")
                await ws.send_json(err)
    except WebSocketDisconnect:
        await admin_manager.disco_admin(admin_)







