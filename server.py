from fastapi import FastAPI,WebSocket,WebSocketDisconnect
from fastapi.responses import HTMLResponse
from auth import *
from datetime import datetime
import time
from pydantic import BaseModel
from itsdangerous import URLSafeTimedSerializer
serveur_ephemere_token = {}
app = FastAPI()
with open(".env","r") as f:
    key = f.read().strip()
s = URLSafeTimedSerializer(key)

@app.get("/")
async def status_page():
    """Page publique quand on visite l'URL Render — juste un statut visuel,
    aucune donnée réelle exposée, thème identique au client."""
    html = """<!DOCTYPE html>
<html><head><title>GLITCH</title>
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
KEY_VIOLATION_IPS = set()

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

    if ip in KEY_VIOLATION_IPS:
        await ws.close(code=1008)
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

                key_s = rep.get("key")
                if key_s != key:
                    data = await result(c_result="key_error", statut="345", msg="Vous N'utilisez pas Notre Script Officiel, vous n'êtes plus autorisés à créer ni vous connecter à un compte existant")
                    await ws.send_json(data)
                    KEY_VIOLATION_IPS.add(ip)
                    await ws.close(code=1008)
                    return

                if type_ == "signup":
                    u = rep.get("username")
                    password = rep.get("password")
                    public_key = rep.get("public_key")

                    resulta = create(u, password, public_key, db)
                    if resulta:
                        data = await result(c_result="c_result", statut="900", msg=f"Votre compte à été créé avec succès...!, vous pouvez à présent rejoindre ou créé un serveur N'oublie pas de visiter notre canal télégram https://t.me/glitch_chanel pour consulter les serveur les plus populaires ✨")
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
                        await ws.send_json(pa)  # <- corrigé : le message part bien avant la fermeture
                        await ws.close(code=1008)
                        return

                    req = login(u, password, db)
                    if req is not None:
                        data = await result(c_result="l_result", statut="900", msg="Vous Etes à nouveau Connecter")
                        await ws.send_json(data)
                        username = u
                        await manager.connect(username, ws)
                    else:
                        data = await result(c_result="l_result", statut="405", msg="username ou password incorrect veuillez réessayer..!")
                        await ws.send_json(data)

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

with open(".sys", "r") as f:
    sys_key = f.read().strip()

@app.websocket("/ws/glitch/system")
async def system(ws: WebSocket):
    ip = ws.client.host
    if ip in KEY_VIOLATION_IPS:
        await ws.close(code=1008)
        return

    await ws.accept()

    rep = await ws.receive_json()
    if not rep:
        return

    key_sys = rep.get("key_sys")
    if key_sys != sys_key:
        pa = await payload(type="sy_key_error",statut="888",msg="KeyError")
        await ws.send_json(pa)
        KEY_VIOLATION_IPS.add(ip)
        await ws.close(code=1008)
        return

    admin_ = rep.get("name")
    if rep.get("password") != sys_key:
        pa = await payload(type="PassError",statut="306",msg="Mot de passe Incorect ")
        await ws.send_json(pa)
        await ws.close()
        return

    await admin_manager.conn_admin(admin_,ws)

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

            else:
                err = await payload(type="error", msg=f"Commande admin inconnue : {cmd}")
                await ws.send_json(err)
    except WebSocketDisconnect:
        await admin_manager.disco_admin(admin_)







