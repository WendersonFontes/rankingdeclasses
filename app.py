# app.py
# Painel em orientação a objetos — Etapa 3 (otimizado)
# Funcionalidades principais:
# - Auth (Diretor/Gerente/Coordenador/Projetista)
# - Salas dinâmicas (criar por Diretores/Gerentes)
# - Projetistas alocados por sala (vagas)
# - Demandas, histórico e pontuação
# - Consolidação de avaliações de projetistas ao coordenador
# - Inativação / Reativação preservando pontuação
# - Buffer de logs e gravação por flush (Salvar alterações)
# - Backup (ZIP download) e Import (ZIP upload)
# - Undo (snapshot)
# - Uso de st.cache_data para leitura

import streamlit as st
import pandas as pd
import os, io, zipfile, hashlib, json
from datetime import datetime

st.set_page_config(page_title="Painel de Avaliação - OOP (Etapa 3)", layout="wide")

# ------------------ Config ------------------
DATA_DIR = "data"
USERS_CSV = os.path.join(DATA_DIR, "users.csv")
PROJ_CSV = os.path.join(DATA_DIR, "projetistas.csv")
HIST_CSV = os.path.join(DATA_DIR, "historico_demandas.csv")
ROOMS_CSV = os.path.join(DATA_DIR, "salas.csv")
LOG_CSV = os.path.join(DATA_DIR, "log_gestao.csv")
INATIVOS_CSV = os.path.join(DATA_DIR, "inativos.csv")

SALT = "painel_avaliacao_salt_v1"
VAGAS_POR_SALA_DEFAULT = 6
CLASSES = ["S","A","B","C","D"]
DISCIPLINAS = ["Hidrossanitário","Elétrica"]  # fixas

PREDEFINED_USERS = [
    {"usuario":"diretor1","nome":"Diretor 1","role":"Diretor","plain_pw":"diretor1!"},
    {"usuario":"diretor2","nome":"Diretor 2","role":"Diretor","plain_pw":"diretor2!"},
    {"usuario":"diretor3","nome":"Diretor 3","role":"Diretor","plain_pw":"diretor3!"},
    {"usuario":"gerente1","nome":"Gerente 1","role":"Gerente","plain_pw":"gerente1!"},
    {"usuario":"gerente2","nome":"Gerente 2","role":"Gerente","plain_pw":"gerente2!"},
]

# Critérios — mostrado na UI com label resumida (detalhes podem ser adicionados)
CRITERIOS = {
    "Qualidade Técnica":[(10,"Acurácia 100%"),(9,"Acurácia >90%"),(8,"Ajustes organização"),(7,"Ajustes técnicos")],
    "Proatividade":[(10,"Proativo extremo"),(9,"Muito proativo"),(8,"Proativo"),(7,"Alguma proatividade")],
    "Colaboração em equipe":[(10,"Sempre ajuda"),(9,"Ajuda frequente"),(8,"Disponível"),(6,"Ajuda limitada")],
    "Comunicação":[(10,"Perfeita"),(9,"Boa"),(7,"Com falhas"),(6,"Média")],
    "Organização / Planejamento":[(10,"Exemplar"),(9,"Organizado"),(7,"Básico"),(6,"Pouco organizado")],
    "Dedicação em estudos":[(10,"Constante"),(9,"Aplicado"),(7,"Parcial"),(6,"Pouca")],
    "Cumprimento de prazos":[(10,"Nenhum atraso"),(9,"1 atraso justificado"),(8,"2 atrasos")],
    "Engajamento com Odoo":[(10,"Total"),(9,"Alto"),(7,"Moderado"),(6,"Limitado")]
}

# ------------------ Utilidades ------------------
def ensure_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def hash_pw(pw: str):
    return hashlib.sha256((SALT + pw).encode("utf-8")).hexdigest()

def rerun_safe():
    try:
        st.rerun()
    except AttributeError:
        try:
            st.experimental_rerun()
        except Exception:
            pass

# ------------------ Storage (responsável por I/O) ------------------
class Storage:
    def _init_(self):
        ensure_dir()

    @st.cache_data
    def load_users(self):
        if not os.path.exists(USERS_CSV):
            rows=[]
            for u in PREDEFINED_USERS:
                rows.append({
                    "usuario":u["usuario"],
                    "nome":u["nome"],
                    "role":u["role"],
                    "senha_hash":hash_pw(u["plain_pw"]),
                    "cor_tema":"",
                    "ativo":True,
                    "criado_em":datetime.now().isoformat(),
                    "ultimo_login":"",
                    "sala_atribuida":""
                })
            pd.DataFrame(rows).to_csv(USERS_CSV,index=False)
        return pd.read_csv(USERS_CSV)

    @st.cache_data
    def load_rooms(self):
        if not os.path.exists(ROOMS_CSV):
            rows=[]
            for sala,equipe in [(1,"Hidrossanitário"),(2,"Hidrossanitário"),(3,"Elétrica"),(4,"Elétrica")]:
                rows.append({"Sala":int(sala),"Equipe":equipe,"Vagas":int(VAGAS_POR_SALA_DEFAULT)})
            pd.DataFrame(rows).to_csv(ROOMS_CSV,index=False)
        return pd.read_csv(ROOMS_CSV)

    @st.cache_data
    def load_projetistas(self):
        if not os.path.exists(PROJ_CSV):
            rooms = self.load_rooms()
            rows=[]
            for _,r in rooms.iterrows():
                for _ in range(int(r["Vagas"])):
                    rows.append({"Sala":int(r["Sala"]),"Equipe":r["Equipe"],"Classe":"-","Projetista":"-","Pontuação":0,"Status":"Ativo"})
            pd.DataFrame(rows).to_csv(PROJ_CSV,index=False)
        return pd.read_csv(PROJ_CSV)

    @st.cache_data
    def load_historico(self):
        if not os.path.exists(HIST_CSV):
            pd.DataFrame(columns=["Timestamp","Disciplina","Demanda","Projetista","Parâmetro","Nota","Resumo","PontosAtribuídos"]).to_csv(HIST_CSV,index=False)
        return pd.read_csv(HIST_CSV, parse_dates=["Timestamp"])

    @st.cache_data
    def load_log(self):
        if not os.path.exists(LOG_CSV):
            pd.DataFrame(columns=["timestamp","usuario","role","acao","detalhes"]).to_csv(LOG_CSV,index=False)
        return pd.read_csv(LOG_CSV, parse_dates=["timestamp"])

    @st.cache_data
    def load_inativos(self):
        if not os.path.exists(INATIVOS_CSV):
            pd.DataFrame(columns=["Projetista","Pontuacao","RemovidoEm"]).to_csv(INATIVOS_CSV,index=False)
        return pd.read_csv(INATIVOS_CSV)

    # save operations: clear cache after write to ensure future reads reflect changes
    def save_users(self, df):
        df.to_csv(USERS_CSV, index=False)
        st.cache_data.clear()

    def save_rooms(self, df):
        df.to_csv(ROOMS_CSV, index=False)
        st.cache_data.clear()

    def save_projetistas(self, df):
        df.to_csv(PROJ_CSV, index=False)
        st.cache_data.clear()

    def save_historico(self, df):
        df.to_csv(HIST_CSV, index=False)
        st.cache_data.clear()

    def append_log(self, rows):
        # rows: list of dicts
        if not rows:
            return
        if os.path.exists(LOG_CSV):
            base = pd.read_csv(LOG_CSV)
        else:
            base = pd.DataFrame(columns=["timestamp","usuario","role","acao","detalhes"])
        new = pd.DataFrame(rows)
        df = pd.concat([new, base], ignore_index=True)
        df.to_csv(LOG_CSV, index=False)
        st.cache_data.clear()

    def save_inativos(self, df):
        df.to_csv(INATIVOS_CSV, index=False)
        st.cache_data.clear()

    # Backup (gera bytes de zip)
    def make_backup_zip_bytes(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # write each file (if exists) or current dataframes
            if os.path.exists(USERS_CSV): zf.write(USERS_CSV, arcname="users.csv")
            if os.path.exists(PROJ_CSV): zf.write(PROJ_CSV, arcname="projetistas.csv")
            if os.path.exists(HIST_CSV): zf.write(HIST_CSV, arcname="historico_demandas.csv")
            if os.path.exists(ROOMS_CSV): zf.write(ROOMS_CSV, arcname="salas.csv")
            if os.path.exists(LOG_CSV): zf.write(LOG_CSV, arcname="log_gestao.csv")
            if os.path.exists(INATIVOS_CSV): zf.write(INATIVOS_CSV, arcname="inativos.csv")
        buffer.seek(0)
        return buffer.getvalue()

    # Importa backup ZIP (substitui CSVs com os contidos no zip)
    def import_backup_zip(self, zip_bytes):
        try:
            z = zipfile.ZipFile(io.BytesIO(zip_bytes))
            names = z.namelist()
            required = {"users.csv","projetistas.csv","historico_demandas.csv","salas.csv"}
            # Allow partial import, but require minimal set
            if not required.issubset(set(names)):
                raise ValueError("ZIP inválido. Arquivos obrigatórios faltando.")
            if "users.csv" in names:
                pd.read_csv(z.open("users.csv")).to_csv(USERS_CSV, index=False)
            if "projetistas.csv" in names:
                pd.read_csv(z.open("projetistas.csv")).to_csv(PROJ_CSV, index=False)
            if "historico_demandas.csv" in names:
                pd.read_csv(z.open("historico_demandas.csv")).to_csv(HIST_CSV, index=False)
            if "salas.csv" in names:
                pd.read_csv(z.open("salas.csv")).to_csv(ROOMS_CSV, index=False)
            if "log_gestao.csv" in names:
                pd.read_csv(z.open("log_gestao.csv")).to_csv(LOG_CSV, index=False)
            if "inativos.csv" in names:
                pd.read_csv(z.open("inativos.csv")).to_csv(INATIVOS_CSV, index=False)
            st.cache_data.clear()
            return True, "Backup importado com sucesso."
        except Exception as e:
            return False, f"Erro ao importar backup: {e}"

# ------------------ Logger (buffered) ------------------
class Logger:
    def _init_(self, storage: Storage):
        self.storage = storage
        if "log_buffer" not in st.session_state:
            st.session_state.log_buffer = []
    def log(self, usuario, role, acao, detalhes=""):
        entry = {"timestamp": datetime.now().isoformat(), "usuario": usuario, "role": role, "acao": acao, "detalhes": detalhes}
        st.session_state.log_buffer.insert(0, entry)  # newest first
    def flush(self):
        storage.append = self.storage.append_log
        self.storage.append_log(st.session_state.log_buffer)
        st.session_state.log_buffer = []

# ------------------ UserManager ------------------
class UserManager:
    def _init_(self, storage: Storage, logger: Logger):
        self.storage = storage
        self.logger = logger
        if "users" not in st.session_state:
            st.session_state.users = self.storage.load_users()
    def authenticate(self, usuario, senha):
        df = st.session_state.users
        row = df[df["usuario"]==usuario]
        if row.empty:
            return False, "Usuário não encontrado."
        row = row.iloc[0]
        if not bool(row["ativo"]):
            return False, "Conta inativa."
        if hash_pw(senha) == row["senha_hash"]:
            # update last login
            st.session_state.users.loc[st.session_state.users["usuario"]==usuario,"ultimo_login"] = datetime.now().isoformat()
            return True, {"usuario":row["usuario"], "nome":row["nome"], "role":row["role"], "cor_tema":row.get("cor_tema",""), "sala_atribuida": row.get("sala_atribuida","")}
        return False, "Senha incorreta."
    def create_projetista_account(self, usuario, nome, senha, cor=""):
        if usuario in st.session_state.users["usuario"].values:
            return False, "Usuário já existe."
        novo = {"usuario":usuario,"nome":nome,"role":"Projetista","senha_hash":hash_pw(senha),"cor_tema":cor,"ativo":True,"criado_em":datetime.now().isoformat(),"ultimo_login":"","sala_atribuida":""}
        st.session_state.users = pd.concat([st.session_state.users, pd.DataFrame([novo])], ignore_index=True)
        self.logger.log(usuario, "Projetista", "CRIAR_USUARIO", "Auto-registro")
        st.session_state.dirty = True
        return True, "Conta criada."
    def promote_to_coordinator(self, usuario, executor):
        if usuario not in st.session_state.users["usuario"].values:
            return False, "Usuário não encontrado."
        st.session_state.users.loc[st.session_state.users["usuario"]==usuario, "role"] = "Coordenador"
        self.logger.log(executor, "Admin", "PROMOVER", f"{usuario} promovido a Coordenador")
        st.session_state.dirty = True
        return True, "Promovido."
    def assign_room(self, usuario, sala, executor):
        if usuario not in st.session_state.users["usuario"].values:
            return False, "Usuário não encontrado."
        st.session_state.users.loc[st.session_state.users["usuario"]==usuario, "sala_atribuida"] = int(sala)
        self.logger.log(executor, "Admin", "ATRIBUIR_SALA", f"{usuario} -> sala {sala}")
        st.session_state.dirty = True
        return True, "Sala atribuída."
    def reset_password(self, usuario, nova_senha, executor):
        st.session_state.users.loc[st.session_state.users["usuario"]==usuario, "senha_hash"] = hash_pw(nova_senha)
        self.logger.log(executor, "Admin", "RESET_SENHA", f"senha reset de {usuario}")
        st.session_state.dirty = True
        return True, "Senha resetada."

# ------------------ RoomManager ------------------
class RoomManager:
    def _init_(self, storage: Storage, logger: Logger):
        self.storage = storage
        self.logger = logger
        if "rooms" not in st.session_state:
            st.session_state.rooms = self.storage.load_rooms()
    def create_room(self, numero, equipe, vagas, executor):
        if int(numero) in st.session_state.rooms["Sala"].values:
            return False, "Número de sala já existe."
        novo = {"Sala":int(numero),"Equipe":equipe,"Vagas":int(vagas)}
        st.session_state.rooms = pd.concat([st.session_state.rooms, pd.DataFrame([novo])], ignore_index=True)
        # add vagas in projetistas
        for _ in range(int(vagas)):
            st.session_state.projetistas = pd.concat([st.session_state.projetistas, pd.DataFrame([{"Sala":int(numero),"Equipe":equipe,"Classe":"-","Projetista":"-","Pontuação":0,"Status":"Ativo"}])], ignore_index=True)
        self.logger.log(executor, "Admin", "CRIAR_SALA", f"Sala {numero} ({equipe}) criada com {vagas} vagas")
        st.session_state.dirty = True
        return True, "Sala criada."

# ------------------ ProjetistaManager ------------------
class ProjetistaManager:
    def _init_(self, storage: Storage, logger: Logger):
        self.storage = storage
        self.logger = logger
        if "projetistas" not in st.session_state:
            st.session_state.projetistas = self.storage.load_projetistas()
    def add_projetista_to_room(self, nome, sala, classe, executor):
        vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==int(sala)) & (st.session_state.projetistas["Projetista"]=="-")]
        if vagas.empty:
            return False, "Sala cheia."
        idx = vagas.index[0]
        st.session_state.projetistas.loc[idx, ["Projetista","Classe","Pontuação","Status"]] = [nome, classe, 0, "Ativo"]
        self.logger.log(executor, "Admin", "ADICIONAR_PROJETISTA", f"{nome} -> sala {sala}")
        st.session_state.dirty = True
        return True, "Projetista adicionado."
    def inactivate_projetista(self, nome, executor):
        # save historico csv for user then mark inativos and free slot
        mask = st.session_state.projetistas["Projetista"]==nome
        if mask.sum()==0:
            return False, "Projetista não encontrado."
        idx = st.session_state.projetistas[mask].index[0]
        pontos = int(st.session_state.projetistas.at[idx,"Pontuação"])
        # append to inativos
        in_df = st.session_state.inativos
        in_df = pd.concat([in_df, pd.DataFrame([{"Projetista":nome,"Pontuacao":pontos,"RemovidoEm":datetime.now().isoformat()}])], ignore_index=True)
        st.session_state.inativos = in_df
        # mark historico entries as Inativo
        st.session_state.historico.loc[st.session_state.historico["Projetista"]==nome, "Projetista"] = st.session_state.historico.loc[st.session_state.historico["Projetista"]==nome, "Projetista"].apply(lambda x: f"{x} (Inativo)")
        # free slot
        st.session_state.projetistas.loc[idx, ["Projetista","Classe","Pontuação","Status"]] = ["-","-","0","Livre"]
        self.logger.log(executor, "Admin", "INATIVAR_PROJETISTA", f"{nome} inativado (pontos {pontos})")
        st.session_state.dirty = True
        return True, "Projetista inativado e pontos preservados."
    def reactivate_projetista(self, nome, sala, classe, executor):
        # check inativos
        found = st.session_state.inativos[st.session_state.inativos["Projetista"]==nome]
        if found.empty:
            return False, "Projetista não está em inativos."
        vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==int(sala)) & (st.session_state.projetistas["Projetista"]=="-")]
        if vagas.empty:
            return False, "Sala sem vaga livre."
        idx = vagas.index[0]
        pontos = int(found.iloc[0]["Pontuacao"]) if pd.notna(found.iloc[0]["Pontuacao"]) else 0
        st.session_state.projetistas.loc[idx, ["Projetista","Classe","Pontuação","Status"]] = [nome, classe, pontos, "Ativo"]
        # remove from inativos
        st.session_state.inativos = st.session_state.inativos[st.session_state.inativos["Projetista"]!=nome].reset_index(drop=True)
        # tidy historico: remove suffix
        st.session_state.historico["Projetista"] = st.session_state.historico["Projetista"].apply(lambda x: x.replace(f"{nome} (Inativo)", nome) if isinstance(x,str) else x)
        self.logger.log(executor, "Admin", "REATIVAR_PROJETISTA", f"{nome} reativado sala {sala} (restored {pontos} pts)")
        st.session_state.dirty = True
        return True, "Projetista reativado."

    def change_class(self, nome, nova_classe, executor):
        mask = st.session_state.projetistas["Projetista"]==nome
        if mask.sum()==0:
            return False, "Projetista não encontrado."
        st.session_state.projetistas.loc[mask,"Classe"]=nova_classe
        self.logger.log(executor, "Admin", "ALTERAR_CLASSE", f"{nome} -> {nova_classe}")
        st.session_state.dirty = True
        return True, "Classe alterada."

    def add_points(self, nome, pontos, motivo, executor):
        mask = st.session_state.projetistas["Projetista"]==nome
        if mask.sum()==0:
            return False, "Projetista não encontrado."
        st.session_state.projetistas.loc[mask, "Pontuação"] += pontos
        self.logger.log(executor, "Admin", "ADICIONAR_PONTOS", f"{nome} +{pontos} pts ({motivo})")
        st.session_state.dirty = True
        return True, "Pontos aplicados."

# ------------------ HistoricoManager ------------------
class HistoricoManager:
    def _init_(self, storage: Storage, logger: Logger):
        self.storage = storage
        self.logger = logger
        if "historico" not in st.session_state:
            st.session_state.historico = self.storage.load_historico()
    def add_entry(self, disciplina, demanda, projetista, parametro, nota, resumo, pontos):
        nova = {"Timestamp": pd.Timestamp.now(), "Disciplina":disciplina, "Demanda":demanda, "Projetista":projetista,
                "Parâmetro":parametro, "Nota":nota, "Resumo":resumo, "PontosAtribuídos":pontos}
        st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
        st.session_state.dirty = True
    def consolidate_coordinator(self, coordinator_user, sala_num):
        # consolida avaliações do historico com Demanda like AVALIACAO_COORDENADOR:<user>
        prefix = f"AVALIACAO_COORDENADOR:{coordinator_user}"
        entries = st.session_state.historico[st.session_state.historico["Demanda"].str.startswith(prefix, na=False)]
        if entries.empty:
            return False, "Nenhuma avaliação encontrada."
        # consider only evaluations from projetistas of that sala
        sala_projs = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==int(sala_num)) & (st.session_state.projetistas["Status"]=="Ativo")]["Projetista"].tolist()
        rel = entries[entries["Projetista"].isin(sala_projs)]
        if rel.empty:
            return False, "Nenhuma avaliação vinda da sua sala (nenhuma aplicável)."
        total_aplicado = 0.0
        applied_entries = []
        for param, g in rel.groupby("Parâmetro"):
            avg = g["Nota"].mean()
            pts = 0.0
            if avg >= 9: pts = 1.0
            elif avg >= 8: pts = 0.5
            else: pts = 0.0
            # criar um entry no historico que represente aplicação de ponto ao coordenador (projetista field = coordinator_user)
            nova = {"Timestamp": pd.Timestamp.now(), "Disciplina": st.session_state.rooms[st.session_state.rooms["Sala"]==int(sala_num)]["Equipe"].iat[0],
                    "Demanda": f"COORD_APLICACAO:{param}", "Projetista": coordinator_user, "Parâmetro": param, "Nota": round(avg,2), "Resumo": "Consolidação avaliações projetistas", "PontosAtribuídos": pts}
            st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
            total_aplicado += pts
            applied_entries.append(nova)
        st.session_state.dirty = True
        # registrar log através do logger
        self.logger.log(coordinator_user, "Coordenador", "CONSOLIDAR_AVALIACOES", f"Aplicados {total_aplicado} pts (sala {sala_num})")
        return True, f"Aplicados {total_aplicado} pontos (soma por parâmetro)."

# ------------------ Session Manager ------------------
class SessionManager:
    def _init_(self):
        if "current_user" not in st.session_state:
            st.session_state.current_user = None
        if "dirty" not in st.session_state:
            st.session_state.dirty = False
        if "_snapshot" not in st.session_state:
            st.session_state._snapshot = None
    def login(self, userdict):
        st.session_state.current_user = userdict
    def logout(self):
        st.session_state.current_user = None
    def snapshot(self):
        st.session_state._snapshot = {
            "users": st.session_state.users.copy(deep=True),
            "rooms": st.session_state.rooms.copy(deep=True),
            "projetistas": st.session_state.projetistas.copy(deep=True),
            "historico": st.session_state.historico.copy(deep=True),
            "inativos": st.session_state.inativos.copy(deep=True),
            "log_buffer": list(st.session_state.log_buffer)
        }
    def undo(self):
        s = st.session_state._snapshot
        if not s:
            return False, "Nada para desfazer."
        st.session_state.users = s["users"]
        st.session_state.rooms = s["rooms"]
        st.session_state.projetistas = s["projetistas"]
        st.session_state.historico = s["historico"]
        st.session_state.inativos = s["inativos"]
        st.session_state.log_buffer = s["log_buffer"]
        st.session_state.dirty = True
        st.session_state._snapshot = None
        return True, "Última ação desfeita em memória."

# ------------------ App UI (integra todos os managers) ------------------
class AppUI:
    def _init_(self):
        self.storage = Storage()
        self.logger = Logger(self.storage)
        self.users = UserManager(self.storage, self.logger)
        self.rooms = RoomManager(self.storage, self.logger)
        self.proj = ProjetistaManager(self.storage, self.logger)
        self.hist = HistoricoManager(self.storage, self.logger)
        self.session = SessionManager()
        # ensure dataframes are present in session state
        if "users" not in st.session_state:
            st.session_state.users = self.storage.load_users()
        if "rooms" not in st.session_state:
            st.session_state.rooms = self.storage.load_rooms()
        if "projetistas" not in st.session_state:
            st.session_state.projetistas = self.storage.load_projetistas()
        if "historico" not in st.session_state:
            st.session_state.historico = self.storage.load_historico()
        if "inativos" not in st.session_state:
            st.session_state.inativos = self.storage.load_inativos()
        if "log_df" not in st.session_state:
            st.session_state.log_df = self.storage.load_log()
        # defaults
        if "log_buffer" not in st.session_state:
            st.session_state.log_buffer = []
        if "dirty" not in st.session_state:
            st.session_state.dirty = False
        if "_snapshot" not in st.session_state:
            st.session_state._snapshot = None

    # flush all changes to disk
    def flush_all(self):
        # save all dataframes and append logs
        self.storage.save_users(st.session_state.users)
        self.storage.save_rooms(st.session_state.rooms)
        self.storage.save_projetistas(st.session_state.projetistas)
        self.storage.save_historico(st.session_state.historico)
        self.storage.save_inativos(st.session_state.inativos)
        # append logs buffer
        if st.session_state.log_buffer:
            self.storage.append_log(st.session_state.log_buffer)
            st.session_state.log_buffer = []
        st.session_state.dirty = False
        st.success("Alterações salvas no disco.")

    # top-level UI render
    def render(self):
        st.title("Painel de Avaliação — OOP (Etapa 3)")
        st.markdown("Autenticação, gestão de salas, projetistas, demandas, ranking e logs — otimizado.")
        # controls (undo, autosave, save)
        col1,col2,col3 = st.columns([1,1,1])
        with col1:
            if st.button("↩️ Desfazer (snapshot)"):
                ok,msg = self.session.undo()
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
        with col2:
            if "auto_save" not in st.session_state:
                st.session_state.auto_save = False
            st.checkbox("Auto-save", value=st.session_state.auto_save, key="auto_save_toggle", on_change=lambda: st.session_state.update({"auto_save": st.session_state.auto_save_toggle}))
        with col3:
            if st.button("💾 Salvar alterações"):
                self.flush_all()

        if st.session_state.dirty:
            st.warning("Existem alterações em memória não salvas.")
        else:
            st.info("Sem alterações pendentes.")

        st.markdown("---")
        # Sidebar: login/register
        self.render_sidebar()

        # after login show relevant UI
        if st.session_state.current_user:
            cu = st.session_state.current_user
            aplicar_tema(cu.get("cor_tema",""))
            st.header(f"Olá, {cu['nome']} — {cu['role']}")
            st.markdown(f"Usuário: {cu['usuario']} • Sala atribuída: {cu.get('sala_atribuida', '(nenhuma)')}")
            # Allow all roles to view summary rankings
            # Role-specific UIs
            if cu["role"] in ["Diretor","Gerente"]:
                self.render_admin(cu)
            if cu["role"] == "Coordenador":
                self.render_coordinator(cu)
            if cu["role"] == "Projetista":
                self.render_projetista(cu)
            # Everyone sees rankings summary
            st.markdown("---")
            self.render_rankings()
            # Managers/coordenadores see logs
            if cu["role"] in ["Diretor","Gerente","Coordenador"]:
                st.markdown("---")
                self.render_logs()
        else:
            st.info("Faça login na barra lateral para acessar as funcionalidades do painel.")

    def render_sidebar(self):
        st.sidebar.header("Acesso")
        if st.session_state.current_user:
            cu = st.session_state.current_user
            st.sidebar.success(f"Logado: {cu['nome']} ({cu['role']})")
            if st.sidebar.button("Logout"):
                self.logger.log(cu["usuario"], cu["role"], "LOGOUT", "Logout efetuado")
                st.session_state.current_user = None
                rerun_safe()
        else:
            st.sidebar.subheader("Entrar")
            user_in = st.sidebar.text_input("Usuário", key="login_user")
            pw_in = st.sidebar.text_input("Senha", type="password", key="login_pw")
            if st.sidebar.button("Entrar"):
                ok, resp = self.users.authenticate(user_in.strip(), pw_in.strip())
                if ok:
                    self.session.login(resp)
                    self.logger.log(resp["usuario"], resp["role"], "LOGIN", "Login bem-sucedido")
                    # update stored users DF last login
                    self.storage.save_users(st.session_state.users)
                    st.success("Login efetuado.")
                    rerun_safe()
                else:
                    st.sidebar.error(resp)
                    self.logger.log(user_in.strip(), "", "LOGIN_FALHOU", resp)
            st.sidebar.markdown("---")
            st.sidebar.subheader("Criar conta (Projetista)")
            ru = st.sidebar.text_input("Usuário (login)", key="reg_user")
            rn = st.sidebar.text_input("Nome completo", key="reg_name")
            rp = st.sidebar.text_input("Senha", type="password", key="reg_pw")
            rcor = st.sidebar.text_input("Cor tema (opcional)", key="reg_cor")
            if st.sidebar.button("Criar conta Projetista"):
                ok,msg = self.users.create_projetista_account(ru.strip(), rn.strip(), rp.strip(), rcor.strip())
                if ok:
                    st.sidebar.success(msg)
                    if st.session_state.auto_save:
                        self.flush_all()
                else:
                    st.sidebar.error(msg)

            st.sidebar.markdown("---")
            st.sidebar.subheader("Solicitar Conta (Coordenador)")
            cu_user = st.sidebar.text_input("Usuário (login) - Coordenador", key="req_coord_user")
            cu_name = st.sidebar.text_input("Nome completo - Coordenador", key="req_coord_name")
            cu_pw = st.sidebar.text_input("Senha - Coordenador", type="password", key="req_coord_pw")
            cu_cor = st.sidebar.text_input("Cor tema (opcional) - Coordenador", key="req_coord_cor")
            auth_pw = st.sidebar.text_input("Senha autorização Diretor (necessária)", type="password", key="req_coord_auth")
            if st.sidebar.button("Solicitar criação Coordenador"):
                if not cu_user.strip() or not cu_name.strip() or not cu_pw:
                    st.sidebar.warning("Preencha os campos.")
                else:
                    # authorize using any Diretor's password
                    authorized=False; executor=None
                    for _,r in st.session_state.users[st.session_state.users["role"]=="Diretor"].iterrows():
                        if hash_pw(auth_pw) == r["senha_hash"]:
                            authorized=True; executor=r["usuario"]; break
                    if not authorized:
                        st.sidebar.error("Autorização negada.")
                        self.logger.log(cu_user.strip(),"Solicitante","CRIAR_COORDENADOR_FALHOU","Autorização inválida")
                    else:
                        # create coordinator account (sala to be assigned by admin)
                        snapshot_savepoint = self.session.snapshot
                        snapshot_savepoint()
                        new = {"usuario":cu_user.strip(),"nome":cu_name.strip(),"role":"Coordenador","senha_hash":hash_pw(cu_pw),"cor_tema":cu_cor,"ativo":True,"criado_em":datetime.now().isoformat(),"ultimo_login":"","sala_atribuida":""}
                        st.session_state.users = pd.concat([st.session_state.users, pd.DataFrame([new])], ignore_index=True)
                        self.logger.log(executor,"Diretor","CRIAR_COORDENADOR",f"{cu_user.strip()} criado")
                        st.sidebar.success("Conta de Coordenador criada. Atribua sala via Perfis (Admin).")
                        st.session_state.dirty = True
                        if st.session_state.auto_save:
                            self.flush_all()

    def render_admin(self, cu):
        st.subheader("Administração (Diretor / Gerente)")
        # Rooms management
        with st.expander("🧱 Salas (Criar / Visualizar)", expanded=False):
            st.dataframe(st.session_state.rooms, use_container_width=True)
            new_equipe = st.selectbox("Equipe (nova sala)", options=DISCIPLINAS, key="admin_new_equipe")
            new_num = st.number_input("Número da sala (inteiro)", min_value=1, value=int(st.session_state.rooms["Sala"].max()+1), key="admin_new_num")
            new_vagas = st.number_input("Vagas na sala", min_value=1, max_value=20, value=VAGAS_POR_SALA_DEFAULT, key="admin_new_vagas")
            if st.button("Criar nova sala", key="admin_create_room"):
                ok,msg = self.rooms.create_room(new_num, new_equipe, new_vagas, cu["usuario"])
                if ok:
                    st.success(msg)
                    if st.session_state.auto_save:
                        self.flush_all()
                else:
                    st.error(msg)

        # Manage users
        st.markdown("---")
        st.subheader("Perfis e Ações")
        st.dataframe(st.session_state.users[["usuario","nome","role","ativo","criado_em","ultimo_login","sala_atribuida"]], use_container_width=True)
        dfu = st.session_state.users.copy()
        sel = st.selectbox("Selecionar usuário", options=dfu["usuario"].tolist(), key="admin_sel_user")
        action = st.selectbox("Ação", options=["Ativar","Desativar","Resetar senha","Promover para Coordenador","Atribuir Sala"], key="admin_action_sel")
        if action=="Resetar senha":
            newpw = st.text_input("Nova senha", key="admin_newpw_input")
        elif action=="Atribuir Sala":
            salas_opts = st.session_state.rooms["Sala"].tolist()
            atrib_sala = st.selectbox("Sala", options=salas_opts, key="admin_atrib_sala")
        else:
            newpw=None; atrib_sala=None
        if st.button("Executar ação (Admin)", key="admin_exec_action"):
            snapshot_savepoint = self.session.snapshot
            snapshot_savepoint()
            if action=="Ativar":
                st.session_state.users.loc[st.session_state.users["usuario"]==sel,"ativo"]=True
                self.logger.log(cu["usuario"], cu["role"], "ATIVAR_USUARIO", sel)
                st.success("Usuário ativado.")
            elif action=="Desativar":
                if sel==cu["usuario"] and cu["role"]=="Diretor":
                    st.error("Diretor não pode desativar a si mesmo.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"ativo"]=False
                    self.logger.log(cu["usuario"], cu["role"], "DESATIVAR_USUARIO", sel)
                    st.success("Usuário desativado.")
            elif action=="Resetar senha":
                if not newpw:
                    st.error("Informe nova senha.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"senha_hash"]=hash_pw(newpw)
                    self.logger.log(cu["usuario"], cu["role"], "RESET_SENHA", f"{sel} nova senha")
                    st.success("Senha redefinida.")
            elif action=="Promover para Coordenador":
                st.session_state.users.loc[st.session_state.users["usuario"]==sel,"role"]="Coordenador"
                self.logger.log(cu["usuario"], cu["role"], "PROMOVER", f"{sel} promovido a Coordenador")
                st.success("Usuário promovido a Coordenador.")
            elif action=="Atribuir Sala":
                if atrib_sala is None:
                    st.error("Selecione sala.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"sala_atribuida"]=int(atrib_sala)
                    self.logger.log(cu["usuario"], cu["role"], "ATRIBUIR_SALA", f"{sel} -> sala {atrib_sala}")
                    st.success("Sala atribuída.")
            st.session_state.dirty = True
            if st.session_state.auto_save:
                self.flush_all()

        # Projetistas global management
        st.markdown("---")
        st.subheader("Quadro de Projetistas (Global)")
        st.dataframe(st.session_state.projetistas[["Sala","Equipe","Projetista","Classe","Pontuação","Status"]], use_container_width=True)
        st.markdown("Ações rápidas sobre projetistas:")
        col1,col2 = st.columns(2)
        with col1:
            disc_add = st.selectbox("Equipe ao adicionar (global)", options=DISCIPLINAS, key="adm_add_disc")
            salas_disp = st.session_state.rooms[st.session_state.rooms["Equipe"]==disc_add]["Sala"].tolist()
            sala_add = st.selectbox("Sala", options=salas_disp, key="adm_add_sala")
            nome_add = st.text_input("Nome projetista (novo)", key="adm_add_name")
            classe_add = st.selectbox("Classe", options=CLASSES, key="adm_add_classe")
            if st.button("Adicionar projetista (global)", key="adm_add_btn"):
                snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                ok,msg = self.proj.add_projetista_to_room(nome_add.strip(), sala_add, classe_add, cu["usuario"])
                if ok:
                    st.success(msg)
                    if st.session_state.auto_save:
                        self.flush_all()
                else:
                    st.error(msg)
        with col2:
            sel_proj = st.selectbox("Selecionar projetista (inativar)", options=st.session_state.projetistas[st.session_state.projetistas["Projetista"]!="-"]["Projetista"].tolist(), key="adm_inat_sel")
            if st.button("Gerar relatório e Inativar", key="adm_inat_btn"):
                snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                # download historico
                hist_proj = st.session_state.historico[st.session_state.historico["Projetista"]==sel_proj]
                csvb = hist_proj.to_csv(index=False).encode("utf-8")
                fn = f"historico_{sel_proj}{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
                st.download_button("⬇️ Baixar histórico do projetista", data=csvb, file_name=fn, mime="text/csv")
                ok,msg = self.proj.inactivate_projetista(sel_proj, cu["usuario"])
                if ok:
                    st.success(msg)
                    if st.session_state.auto_save:
                        self.flush_all()
                else:
                    st.error(msg)
            in_candidates = st.session_state.inativos["Projetista"].tolist() if not st.session_state.inativos.empty else []
            sel_re = st.selectbox("Projetista inativo para reativar", options=in_candidates if in_candidates else ["(nenhum)"], key="adm_re_sel")
            sala_re = st.selectbox("Sala para reativar", options=st.session_state.rooms["Sala"].tolist(), key="adm_re_sala")
            classe_re = st.selectbox("Classe ao reativar", options=CLASSES, key="adm_re_classe")
            if st.button("Reativar projetista", key="adm_re_btn"):
                if sel_re == "(nenhum)":
                    st.info("Nenhum inativo disponível.")
                else:
                    snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                    ok,msg = self.proj.reactivate_projetista(sel_re, sala_re, classe_re, cu["usuario"])
                    if ok:
                        st.success(msg)
                        if st.session_state.auto_save:
                            self.flush_all()
                    else:
                        st.error(msg)

        # Backup / Import
        st.markdown("---")
        st.subheader("Backup / Import")
        if st.button("📦 Gerar Backup ZIP"):
            zip_bytes = self.storage.make_backup_zip_bytes()
            fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            st.download_button("⬇️ Baixar backup", zip_bytes, file_name=fname, mime="application/zip")
            self.logger.log(cu["usuario"], cu["role"], "BACKUP_MANUAL", f"Backup gerado {fname}")
        uploaded = st.file_uploader("📁 Importar backup (ZIP)", type=["zip"])
        if uploaded:
            ok,msg = self.storage.import_backup_zip(uploaded.read())
            if ok:
                st.success(msg)
                # reload session data
                st.session_state.users = self.storage.load_users()
                st.session_state.rooms = self.storage.load_rooms()
                st.session_state.projetistas = self.storage.load_projetistas()
                st.session_state.historico = self.storage.load_historico()
                st.session_state.inativos = self.storage.load_inativos()
                st.session_state.log_df = self.storage.load_log()
                st.session_state.dirty = False
                rerun_safe()
            else:
                st.error(msg)

    def render_coordinator(self, cu):
        st.subheader("Painel do Coordenador (sua sala)")
        # check assigned room
        userrow = st.session_state.users[st.session_state.users["usuario"]==cu["usuario"]]
        if userrow.empty:
            st.error("Usuário coordenador não encontrado no sistema.")
            return
        sala_atr = userrow["sala_atribuida"].values[0]
        if sala_atr=="" or pd.isna(sala_atr):
            st.warning("Nenhuma sala atribuída. Peça ao Diretor/Gerente atribuir sua sala.")
            return
        sala_num = int(sala_atr)
        st.info(f"Sala atribuída: {sala_num}")
        # show projetistas in this sala
        subset = st.session_state.projetistas[st.session_state.projetistas["Sala"]==sala_num]
        st.dataframe(subset[["Projetista","Classe","Pontuação","Status"]], use_container_width=True)
        # add projetista to your room
        with st.expander("➕ Adicionar Projetista à minha sala"):
            nome_new = st.text_input("Nome do projetista", key="coord_add_name")
            classe_new = st.selectbox("Classe", options=CLASSES, key="coord_add_classe")
            if st.button("Adicionar à minha sala", key="coord_add_btn"):
                snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==sala_num) & (st.session_state.projetistas["Projetista"]=="-")]
                if vagas.empty:
                    st.error("Sua sala está cheia.")
                else:
                    idx = vagas.index[0]
                    st.session_state.projetistas.loc[idx, ["Projetista","Classe","Pontuação","Status"]] = [nome_new.strip(), classe_new, 0, "Ativo"]
                    self.logger.log(cu["usuario"], cu["role"], "ADICIONAR_PROJETISTA_SALA", f"{nome_new} -> sala {sala_num}")
                    st.success("Projetista adicionado em memória.")
                    st.session_state.dirty = True
                    if st.session_state.auto_save:
                        self.flush_all()

        # Create/Validate Demand (Coordenador only on own sala) — but managers/dirs can use admin panel to create for any sala
        with st.expander("📋 Criar Demanda e Validar Pontos"):
            dem_name = st.text_input("Nome da demanda", key=f"coord_dem_{sala_num}")
            param = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key=f"coord_param_{sala_num}")
            crits = [f"{n} - {txt}" for n,txt in CRITERIOS[param]]
            crit = st.selectbox("Critério", options=crits, key=f"coord_crit_{sala_num}")
            projs = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==sala_num) & (st.session_state.projetistas["Projetista"]!="-")]["Projetista"].tolist()
            proj_sel = st.selectbox("Selecionar projetista", options=projs if projs else ["(nenhum)"], key=f"coord_proj_{sala_num}")
            if st.button("Validar e aplicar ponto (Coordenador)", key=f"coord_apply_{sala_num}"):
                if not dem_name.strip() or proj_sel=="(nenhum)":
                    st.error("Preencha nome da demanda e selecione projetista.")
                else:
                    snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                    try:
                        nota = int(crit.split(" - ")[0])
                    except:
                        nota=None
                    resumo = crit.split(" - ",1)[-1] if " - " in crit else ""
                    pts = 3 if nota==10 else 2 if nota==9 else 1 if nota==8 else 0
                    if pts>0:
                        st.session_state.projetistas.loc[st.session_state.projetistas["Projetista"]==proj_sel, "Pontuação"] += pts
                    # historico entry
                    disciplina = st.session_state.rooms[st.session_state.rooms["Sala"]==sala_num]["Equipe"].iat[0]
                    self.hist.add_entry(disciplina, dem_name.strip(), proj_sel, param, nota, resumo, pts)
                    self.logger.log(cu["usuario"], cu["role"], "VALIDAR_PONTO", f"{proj_sel} +{pts} ({param}) - {dem_name.strip()}")
                    st.success("Demanda validada em memória.")
                    if st.session_state.auto_save:
                        self.flush_all()

        # Consolidate evaluations
        with st.expander("⭐ Consolidação de Avaliações (Projetistas -> Coordenador)"):
            st.write("Projistas da sua sala podem avaliar você (anônimo). Aqui você consolida e aplica pontos.")
            prefix = f"AVALIACAO_COORDENADOR:{cu['usuario']}"
            coord_evals = st.session_state.historico[st.session_state.historico["Demanda"].str.startswith(prefix, na=False)]
            if coord_evals.empty:
                st.info("Nenhuma avaliação encontrada.")
            else:
                st.dataframe(coord_evals, use_container_width=True)
                if st.button("Consolidar e aplicar pontos (Coordenador)"):
                    ok,msg = self.hist.consolidate_coordinator(cu["usuario"], sala_num)
                    if ok:
                        st.success(msg)
                        if st.session_state.auto_save:
                            self.flush_all()
                    else:
                        st.warning(msg)

    def render_projetista(self, cu):
        st.subheader("Painel do Projetista")
        nome = cu["nome"]
        row = st.session_state.projetistas[st.session_state.projetistas["Projetista"]==nome]
        if row.empty:
            st.info("Você não está alocado em nenhuma sala. Peça ao coordenador para alocar.")
            return
        ent = row.iloc[0]
        st.markdown(f"*Sala:* {ent['Sala']} • *Equipe:* {ent['Equipe']} • *Classe:* {ent['Classe']} • *Pontuação:* {ent['Pontuação']}")
        myhist = st.session_state.historico[st.session_state.historico["Projetista"]==nome].sort_values("Timestamp", ascending=False)
        st.dataframe(myhist, use_container_width=True)
        with st.expander("➕ Criar Demanda (minha)"):
            dname = st.text_input("Nome da demanda (minha)", key="proj_dem_name")
            param = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key="proj_param")
            crits = [f"{n} - {txt}" for n,txt in CRITERIOS[param]]
            crit = st.selectbox("Critério", options=crits, key="proj_crit")
            if st.button("Registrar demanda (minha)"):
                if not dname.strip():
                    st.warning("Informe nome da demanda.")
                else:
                    snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                    try:
                        nota = int(crit.split(" - ")[0])
                    except:
                        nota=None
                    resumo = crit.split(" - ",1)[-1] if " - " in crit else ""
                    pts = 3 if nota==10 else 2 if nota==9 else 1 if nota==8 else 0
                    disciplina = ent["Equipe"]
                    self.hist.add_entry(disciplina, dname.strip(), nome, param, nota, resumo, pts)
                    if pts>0:
                        st.session_state.projetistas.loc[st.session_state.projetistas["Projetista"]==nome, "Pontuação"] += pts
                    self.logger.log(cu["usuario"], cu["role"], "CRIAR_DEMANDA_PROPRIA", f"{dname.strip()} criado por {nome}")
                    st.success("Demanda criada (em memória).")
                    if st.session_state.auto_save:
                        self.flush_all()
        with st.expander("⭐ Avaliar meu Coordenador (anônimo)"):
            sala_num = int(ent["Sala"])
            coord_row = st.session_state.users[st.session_state.users["sala_atribuida"]==sala_num]
            if coord_row.empty:
                st.info("Nenhum coordenador atribuído a esta sala.")
            else:
                coord_user = coord_row.iloc[0]["usuario"]
                coord_name = coord_row.iloc[0]["nome"]
                st.write(f"Avaliar Coordenador: *{coord_name}*")
                param_eval = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key="aval_param")
                crits_eval = [f"{n} - {txt}" for n,txt in CRITERIOS[param_eval]]
                crit_eval = st.selectbox("Critério", options=crits_eval, key="aval_crit")
                if st.button("Enviar avaliação (anônima)"):
                    snapshot_savepoint = self.session.snapshot; snapshot_savepoint()
                    try:
                        nota = int(crit_eval.split(" - ")[0])
                    except:
                        nota=None
                    resumo = crit_eval.split(" - ",1)[-1] if " - " in crit_eval else ""
                    # store as historico special Demanda AVALIACAO_COORDENADOR:<user>
                    dem = f"AVALIACAO_COORDENADOR:{coord_user}"
                    self.hist.add_entry(ent["Equipe"], dem, cu["nome"], param_eval, nota, resumo, None)
                    self.logger.log(cu["usuario"], cu["role"], "AVALIAR_COORDENADOR", f"{cu['nome']} avaliou {coord_user} ({param_eval}={nota})")
                    st.success("Avaliação enviada (anônima).")
                    if st.session_state.auto_save:
                        self.flush_all()

    def render_rankings(self):
        st.subheader("Rankings")
        # compute ranking by class and geral in memory
        df = st.session_state.projetistas.copy()
        df["RankingClasse"] = "-"
        for cls in CLASSES:
            subset = df[(df["Classe"]==cls) & (df["Projetista"]!="-") & (df["Status"]=="Ativo")].copy()
            if subset.empty: continue
            subset = subset.sort_values("Pontuação", ascending=False).reset_index()
            for rank, idx in enumerate(subset["index"], start=1):
                df.at[idx,"RankingClasse"] = rank if df.at[idx,"Pontuação"]>0 else "-"
        st.session_state.projetistas = df
        # show S first
        df_active = st.session_state.projetistas[st.session_state.projetistas["Projetista"]!="-"]
        for cls in ["S","A","B","C","D"]:
            sub = df_active[(df_active["Classe"]==cls) & (df_active["Status"]=="Ativo")].sort_values("Pontuação", ascending=False)
            if not sub.empty:
                st.write(f"### Classe {cls}")
                st.dataframe(sub[["Projetista","Equipe","Sala","Pontuação"]].reset_index(drop=True), use_container_width=True)
        # ranking geral
        geral = df_active[df_active["Status"]=="Ativo"].sort_values("Pontuação", ascending=False).reset_index(drop=True)
        if not geral.empty:
            geral["RankingGeral"] = geral.index + 1
            geral["RankingGeral"] = geral.apply(lambda x: x["RankingGeral"] if x["Pontuação"]>0 else "-", axis=1)
            st.write("### Ranking Geral")
            st.dataframe(geral[["RankingGeral","Projetista","Equipe","Classe","Sala","Pontuação"]], use_container_width=True)

    def render_logs(self):
        st.subheader("📜 Log de Gestão")
        saved = self.storage.load_log()
        buffer_df = pd.DataFrame(st.session_state.log_buffer) if st.session_state.log_buffer else pd.DataFrame(columns=saved.columns)
        combined = pd.concat([buffer_df, saved], ignore_index=True)
        st.dataframe(combined.head(300), use_container_width=True)
        if st.button("Salvar buffer de logs agora"):
            if st.session_state.log_buffer:
                self.storage.append_log(st.session_state.log_buffer)
                st.session_state.log_buffer = []
                st.success("Logs gravados no disco.")
            else:
                st.info("Buffer de logs vazio.")

# ------------------ Aux functions ------------------
def aplicar_tema(cor):
    if not cor: return
    try:
        css = f"<style>.stApp {{ --primary: {cor}; }} h1,h2,h3, .css-18e3th9 {{ color: {cor} !important; }}</style>"
        st.markdown(css, unsafe_allow_html=True)
    except Exception:
        pass

# ------------------ Inicializa e roda ------------------
def main():
    app = AppUI()
    app.render()

if _name_ == "_main_":
    main()

