# app.py
# ETAPA 3 - Sistema Integrado: Auth/Perfis + Salas Dinâmicas + Projetistas + Demandas + Rankings + Logs + Inativos (preservar pontuação)
# Salve como app.py e rode: streamlit run app.py

import streamlit as st
import pandas as pd
import os, io, zipfile, hashlib
from datetime import datetime

st.set_page_config(page_title="Painel - Etapa 3 (Gestão)", layout="wide")

# ---------------- Config ----------------
DATA_DIR = "data"
USERS_CSV = os.path.join(DATA_DIR, "users.csv")
PROJ_CSV = os.path.join(DATA_DIR, "projetistas.csv")
HIST_CSV = os.path.join(DATA_DIR, "historico_demandas.csv")
ROOMS_CSV = os.path.join(DATA_DIR, "salas.csv")
LOG_CSV = os.path.join(DATA_DIR, "log_gestao.csv")
INATIVOS_CSV = os.path.join(DATA_DIR, "inativos.csv")
BACKUP_NAME_PREFIX = "backup_"

SALT = "painel_avaliacao_salt_v1"
VAGAS_POR_SALA_DEFAULT = 6
CLASSES = ["S","A","B","C","D"]
DISCIPLINAS = ["Hidrossanitário","Elétrica"]  # fixed as requested

# Predefined users (only created when users.csv missing)
PREDEFINED_USERS = [
    {"usuario":"diretor1","nome":"Diretor 1","role":"Diretor","plain_pw":"diretor1!"},
    {"usuario":"diretor2","nome":"Diretor 2","role":"Diretor","plain_pw":"diretor2!"},
    {"usuario":"diretor3","nome":"Diretor 3","role":"Diretor","plain_pw":"diretor3!"},
    {"usuario":"gerente1","nome":"Gerente 1","role":"Gerente","plain_pw":"gerente1!"},
    {"usuario":"gerente2","nome":"Gerente 2","role":"Gerente","plain_pw":"gerente2!"},
]

# Critérios (same mapping used in UI)
CRITERIOS = {
    "Qualidade Técnica":[(10,"Nenhum erro, projeto independente","Acurácia 100%"),
                         (9,"Quase sem falhas, ainda não independente","Acurácia >90%"),
                         (8,"Bom projeto, ajustes de organização","Ajustes leves de organização"),
                         (7,"Bom projeto, alguns ajustes técnicos","Ajustes técnicos solicitados"),
                         (6,"Projeto razoável, muitos comentários","Razoável, precisa de revisão"),
                         (5,"Uso errado de materiais ou modelagem","Erro de materiais/modelagem"),
                         (4,"Erro grave em 1 projeto","Erro grave único"),
                         (3,"Dois ou mais erros graves","Erros graves múltiplos")],
    "Proatividade":[(10,"4 ou mais ações além do básico","Proativo extremo"),
                    (9,"3 ações","Muito proativo"),
                    (8,"2 ações","Proativo"),
                    (7,"1 ação","Alguma proatividade"),
                    (6,"Faz o básico e pede novas demandas","Básico + iniciativa mínima"),
                    (5,"Fala que acabou, mas não quer novos projetos","Pouca disposição"),
                    (3,"Nenhuma ação","Inativo")],
    "Colaboração em equipe":[(10,"Sempre ajuda primeiro, acompanha até resolver","Sempre ajuda primeiro"),
                    (9,"Frequentemente ajuda primeiro e acompanha","Ajuda frequente"),
                    (8,"Boa disposição, ajuda, mas não é o primeiro","Disponível para ajudar"),
                    (6,"Oferece ajuda, mas pouco disposto","Ajuda limitada"),
                    (5,"Só escuta, não se envolve","Escuta passiva"),
                    (3,"Nunca ajuda, não se dispõe","Não colaborativo")],
    "Comunicação":[(10,"Clareza total, escuta ativa, escreve bem","Comunicação perfeita"),
                    (9,"Clareza, escuta ativa, e-mails/WhatsApp ok","Comunicação boa"),
                    (7,"Clareza, escuta ativa, mas escrita ruim","Comunicação com falhas"),
                    (6,"Clareza média, escuta/ escrita irregular","Comunicação média"),
                    (5,"Clareza limitada, escuta irregular","Comunicação fraca"),
                    (3,"Não comunica claramente, não escuta","Comunicação ruim")],
    "Organização / Planejamento":[(10,"Muito organizado, ajuda o coordenador","Organização exemplar"),
                    (9,"Organizado, segue procedimentos, sugere melhorias","Organizado e propositivo"),
                    (7,"Respeita procedimentos, sem sugestão","Organizado básico"),
                    (6,"Uma chamada de atenção","Pouco organizado"),
                    (5,"Duas chamadas de atenção","Desorganizado"),
                    (3,"Três ou mais chamadas","Muito desorganizado")],
    "Dedicação em estudos":[(10,"Anota sempre, faz cursos, aplica treinamentos, traz soluções","Estudo constante e aplicado"),
                    (9,"Anota, faz cursos, aproveita treinamentos, às vezes traz soluções","Estudo aplicado"),
                    (7,"Anota às vezes, raramente traz soluções","Dedicação parcial"),
                    (6,"Anota pouco, não faz cursos, não traz soluções","Pouca dedicação"),
                    (5,"Repete perguntas, não usa cursos","Dedicação mínima"),
                    (3,"Repete muitas vezes, não aproveita cursos","Sem dedicação")],
    "Cumprimento de prazos":[(10,"Nenhum atraso","Pontualidade total"),
                    (9,"1 atraso justificado","Quase pontual"),
                    (8,"2 atrasos justificados","Pontualidade razoável"),
                    (7,"3 atrasos justificados","Atrasos frequentes"),
                    (6,"4 atrasos justificados","Atrasos contínuos"),
                    (5,"1 atraso não justificado","Atraso sem justificativa"),
                    (4,"2 atrasos não justificados","Atrasos problemáticos"),
                    (3,"Mais de 2 atrasos não justificados","Muito atrasado")],
    "Engajamento com Odoo":[(10,"Usa todos apps, sugere melhorias, cobra colegas","Engajamento total"),
                    (9,"Usa boa parte dos apps, abre todo dia, cobra colegas","Engajamento alto"),
                    (7,"Usa parte dos apps, abre todo dia, não cobra colegas","Engajamento moderado"),
                    (6,"Usa parte dos apps, abre todo dia, mas não durante todo o dia","Uso limitado"),
                    (5,"Usa apenas parte dos apps, abre de forma irregular","Uso mínimo"),
                    (3,"Não usa corretamente, resiste à ferramenta","Resistência total")]
}

# ---------------- Utilities ----------------
def rerun_safe():
    try:
        st.rerun()
    except AttributeError:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def hash_password(pw):
    return hashlib.sha256((SALT + pw).encode("utf-8")).hexdigest()

# ---------------- Persistence: ensure & load ----------------
def ensure_users():
    ensure_data_dir()
    if not os.path.exists(USERS_CSV):
        rows = []
        for u in PREDEFINED_USERS:
            rows.append({
                "usuario":u["usuario"],
                "nome":u["nome"],
                "role":u["role"],
                "senha_hash":hash_password(u["plain_pw"]),
                "cor_tema":"",
                "ativo":True,
                "criado_em":datetime.now().isoformat(),
                "ultimo_login":"",
                "sala_atribuida":""  # only for coordenadores
            })
        pd.DataFrame(rows).to_csv(USERS_CSV,index=False)
    return pd.read_csv(USERS_CSV)

def save_users(df):
    df.to_csv(USERS_CSV,index=False)

def ensure_rooms():
    ensure_data_dir()
    if not os.path.exists(ROOMS_CSV):
        rows=[]
        for sala,equipe in [(1,"Hidrossanitário"),(2,"Hidrossanitário"),(3,"Elétrica"),(4,"Elétrica")]:
            rows.append({"Sala":int(sala),"Equipe":equipe,"Vagas":int(VAGAS_POR_SALA_DEFAULT)})
        pd.DataFrame(rows).to_csv(ROOMS_CSV,index=False)
    return pd.read_csv(ROOMS_CSV)

def save_rooms(df):
    df.to_csv(ROOMS_CSV,index=False)

def ensure_projetistas():
    ensure_data_dir()
    if not os.path.exists(PROJ_CSV):
        rooms = ensure_rooms()
        rows=[]
        for _,r in rooms.iterrows():
            for _ in range(int(r["Vagas"])):
                rows.append({"Sala":int(r["Sala"]),"Equipe":r["Equipe"],"Classe":"-","Projetista":"-","Pontuação":0,"Status":"Ativo"})
        pd.DataFrame(rows).to_csv(PROJ_CSV,index=False)
    return pd.read_csv(PROJ_CSV)

def save_projetistas(df):
    df.to_csv(PROJ_CSV,index=False)

def ensure_historico():
    ensure_data_dir()
    if not os.path.exists(HIST_CSV):
        pd.DataFrame(columns=["Timestamp","Disciplina","Demanda","Projetista","Parâmetro","Nota","Resumo","PontosAtribuídos"]).to_csv(HIST_CSV,index=False)
    return pd.read_csv(HIST_CSV, parse_dates=["Timestamp"])

def save_historico(df):
    df.to_csv(HIST_CSV,index=False)

def ensure_log():
    ensure_data_dir()
    if not os.path.exists(LOG_CSV):
        pd.DataFrame(columns=["timestamp","usuario","role","acao","detalhes"]).to_csv(LOG_CSV,index=False)

def registrar_log(usuario, role, acao, detalhes=""):
    ensure_log()
    df = pd.read_csv(LOG_CSV)
    nova = {"timestamp":datetime.now().isoformat(), "usuario":usuario, "role":role, "acao":acao, "detalhes":detalhes}
    df = pd.concat([pd.DataFrame([nova]), df], ignore_index=True)
    df.to_csv(LOG_CSV,index=False)

def ensure_inativos():
    ensure_data_dir()
    if not os.path.exists(INATIVOS_CSV):
        pd.DataFrame(columns=["Projetista","Pontuacao","RemovidoEm"]).to_csv(INATIVOS_CSV,index=False)
    return pd.read_csv(INATIVOS_CSV)

def save_inativos(df):
    df.to_csv(INATIVOS_CSV,index=False)

# ---------------- Helpers de regras ----------------
def pontos_por_nota(n):
    if n==10: return 3
    if n==9: return 2
    if n==8: return 1
    return 0

def calcular_rankings():
    df = st.session_state.projetistas.copy()
    df["RankingClasse"] = "-"
    for classe in CLASSES:
        subset = df[(df["Classe"]==classe) & (df["Projetista"]!="-") & (df["Status"]=="Ativo")].copy()
        if subset.empty: continue
        subset = subset.sort_values("Pontuação", ascending=False).reset_index()
        for rank, idx in enumerate(subset["index"], start=1):
            if df.at[idx,"Pontuação"]>0:
                df.at[idx,"RankingClasse"] = rank
            else:
                df.at[idx,"RankingClasse"] = "-"
    st.session_state.projetistas = df

# ---------------- Init session state ----------------
if "initialized" not in st.session_state:
    st.session_state.users = ensure_users()
    st.session_state.rooms = ensure_rooms()
    st.session_state.projetistas = ensure_projetistas()
    st.session_state.historico = ensure_historico()
    ensure_log()
    st.session_state.inativos = ensure_inativos()
    st.session_state.current_user = None
    st.session_state._last = None
    st.session_state.initialized = True

# snapshot for undo
def salvar_snapshot():
    st.session_state._last = {
        "users": st.session_state.users.copy(deep=True),
        "rooms": st.session_state.rooms.copy(deep=True),
        "projetistas": st.session_state.projetistas.copy(deep=True),
        "historico": st.session_state.historico.copy(deep=True),
        "inativos": st.session_state.inativos.copy(deep=True)
    }

def desfazer_snapshot():
    if not st.session_state._last:
        st.warning("Nada para desfazer.")
        return
    s = st.session_state._last
    st.session_state.users = s["users"]
    st.session_state.rooms = s["rooms"]
    st.session_state.projetistas = s["projetistas"]
    st.session_state.historico = s["historico"]
    st.session_state.inativos = s["inativos"]
    save_users(st.session_state.users)
    save_rooms(st.session_state.rooms)
    save_projetistas(st.session_state.projetistas)
    save_historico(st.session_state.historico)
    save_inativos(st.session_state.inativos)
    st.success("Última ação desfeita.")
    st.session_state._last = None

# ---------------- UI Top ----------------
st.title("Painel de Avaliação - Etapa 3 (Gestão Integrada)")
st.markdown("Sistema com autenticação, perfis, salas dinâmicas, demandas, ranking, logs e reativação preservando pontuação.")

colL, colR = st.columns([3,1])
with colR:
    if st.button("Recarregar dados"):
        st.session_state.users = ensure_users()
        st.session_state.rooms = ensure_rooms()
        st.session_state.projetistas = ensure_projetistas()
        st.session_state.historico = ensure_historico()
        st.session_state.inativos = ensure_inativos()
        st.success("Dados recarregados. Refaça login se necessário.")
with colL:
    st.info("Diretor/Gerente podem criar salas; Coordenadores são atribuídos a UMA sala; Projetistas podem avaliar o coordenador da sua sala.")

# ---------------- Sidebar: Login & Registration ----------------
st.sidebar.header("Acesso")

if st.session_state.current_user:
    cu = st.session_state.current_user
    st.sidebar.success(f"Logado: {cu['nome']} — {cu['role']}")
    if st.sidebar.button("Logout"):
        registrar_log(cu["usuario"], cu["role"], "LOGOUT", "Logout efetuado")
        st.session_state.current_user = None
        rerun_safe()
else:
    st.sidebar.subheader("Entrar")
    user_in = st.sidebar.text_input("Usuário", key="login_user")
    pw_in = st.sidebar.text_input("Senha", type="password", key="login_pw")
    if st.sidebar.button("Entrar"):
        dfu = st.session_state.users
        row = dfu[dfu["usuario"]==user_in.strip()]
        if row.empty:
            st.sidebar.error("Usuário não encontrado.")
        else:
            row = row.iloc[0]
            if not bool(row["ativo"]):
                st.sidebar.error("Conta inativa.")
            elif hash_password(pw_in) == row["senha_hash"]:
                st.session_state.current_user = {"usuario":row["usuario"], "nome":row["nome"], "role":row["role"], "cor_tema":row.get("cor_tema",""), "sala_atribuida": row.get("sala_atribuida","")}
                st.session_state.users.loc[st.session_state.users["usuario"]==row["usuario"], "ultimo_login"] = datetime.now().isoformat()
                save_users(st.session_state.users)
                registrar_log(row["usuario"], row["role"], "LOGIN", "Login bem-sucedido")
                rerun_safe()
            else:
                st.sidebar.error("Senha incorreta.")
                registrar_log(user_in.strip(), "", "LOGIN_FALHOU", "Senha incorreta")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Registrar conta (Projetista)")
    ru = st.sidebar.text_input("Usuário (login)", key="reg_user")
    rn = st.sidebar.text_input("Nome completo", key="reg_name")
    rp = st.sidebar.text_input("Senha", type="password", key="reg_pw")
    rcor = st.sidebar.text_input("Cor tema (opcional)", key="reg_cor")
    if st.sidebar.button("Criar conta Projetista"):
        if not ru.strip() or not rn.strip() or not rp:
            st.sidebar.warning("Preencha usuário, nome e senha.")
        else:
            if ru.strip() in st.session_state.users["usuario"].values:
                st.sidebar.error("Usuário já existe.")
            else:
                salvar_snapshot()
                new = {"usuario":ru.strip(),"nome":rn.strip(),"role":"Projetista","senha_hash":hash_password(rp),"cor_tema":rcor,"ativo":True,"criado_em":datetime.now().isoformat(),"ultimo_login":"","sala_atribuida":""}
                st.session_state.users = pd.concat([st.session_state.users, pd.DataFrame([new])], ignore_index=True)
                save_users(st.session_state.users)
                registrar_log(ru.strip(),"Projetista","CRIAR_USUARIO","Conta Projetista criada por auto-registro")
                st.sidebar.success("Conta criada. Faça login.")

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
            authorized = False; executor=None
            for _,r in st.session_state.users[st.session_state.users["role"]=="Diretor"].iterrows():
                if hash_password(auth_pw) == r["senha_hash"]:
                    authorized = True; executor = r["usuario"]; break
            if not authorized:
                st.sidebar.error("Autorização negada.")
                registrar_log(cu_user.strip(),"Solicitante","CRIAR_COORDENADOR_FALHOU","Autorização inválida")
            else:
                if cu_user.strip() in st.session_state.users["usuario"].values:
                    st.sidebar.error("Usuário já existe.")
                else:
                    salvar_snapshot()
                    new = {"usuario":cu_user.strip(),"nome":cu_name.strip(),"role":"Coordenador","senha_hash":hash_password(cu_pw),"cor_tema":cu_cor,"ativo":True,"criado_em":datetime.now().isoformat(),"ultimo_login":"","sala_atribuida":""}
                    st.session_state.users = pd.concat([st.session_state.users, pd.DataFrame([new])], ignore_index=True)
                    save_users(st.session_state.users)
                    registrar_log(executor,"Diretor","CRIAR_COORDENADOR",f"{cu_user.strip()} criado")
                    st.sidebar.success("Conta de Coordenador criada (atribuir sala via Painel de Perfis).")

# ---------------- Main area after login ----------------
def aplicar_tema_usuario():
    cu = st.session_state.current_user
    if not cu: return
    cor = cu.get("cor_tema","")
    if isinstance(cor,str) and cor.strip():
        c = cor.strip()
        css = f"<style>.stApp {{ --primary: {c}; }} h1,h2,h3, .css-18e3th9 {{ color: {c} !important; }}</style>"
        st.markdown(css, unsafe_allow_html=True)

if st.session_state.current_user:
    aplicar_tema_usuario()
    cu = st.session_state.current_user
    st.header(f"Olá, {cu['nome']} — {cu['role']}")
    st.markdown(f"**Usuário:** `{cu['usuario']}`  •  **Sala atribuída:** `{cu.get('sala_atribuida','(nenhuma)')}`")

    role = cu["role"]

    # common actions: undo, backup, import
    st.markdown("---")
    c1,c2,c3 = st.columns([1,1,2])
    with c1:
        if st.button("↩️ Desfazer última ação"):
            desfazer_snapshot()
    with c2:
        if st.button("📦 Criar Backup (ZIP)"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("users.csv", st.session_state.users.to_csv(index=False))
                zf.writestr("projetistas.csv", st.session_state.projetistas.to_csv(index=False))
                zf.writestr("historico_demandas.csv", st.session_state.historico.to_csv(index=False))
                zf.writestr("salas.csv", st.session_state.rooms.to_csv(index=False))
                zf.writestr("log_gestao.csv", pd.read_csv(LOG_CSV).to_csv(index=False))
                zf.writestr("inativos.csv", st.session_state.inativos.to_csv(index=False))
            buffer.seek(0)
            fname = f"{BACKUP_NAME_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            st.download_button("⬇️ Baixar Backup", buffer.getvalue(), file_name=fname, mime="application/zip")
            registrar_log(cu["usuario"], role, "BACKUP_MANUAL", f"Backup gerado {fname}")
    with c3:
        uploaded = st.file_uploader("📂 Importar Backup (ZIP)", type=["zip"])
        if uploaded:
            try:
                z = zipfile.ZipFile(io.BytesIO(uploaded.read()))
                names = z.namelist()
                required = {"users.csv","projetistas.csv","historico_demandas.csv","salas.csv"}
                if required.issubset(set(names)):
                    salvar_snapshot()
                    st.session_state.users = pd.read_csv(z.open("users.csv"))
                    st.session_state.projetistas = pd.read_csv(z.open("projetistas.csv"))
                    st.session_state.historico = pd.read_csv(z.open("historico_demandas.csv"), parse_dates=["Timestamp"])
                    st.session_state.rooms = pd.read_csv(z.open("salas.csv"))
                    if "inativos.csv" in names:
                        st.session_state.inativos = pd.read_csv(z.open("inativos.csv"))
                    save_users(st.session_state.users); save_projetistas(st.session_state.projetistas)
                    save_historico(st.session_state.historico); save_rooms(st.session_state.rooms)
                    save_inativos(st.session_state.inativos)
                    registrar_log(cu["usuario"], role, "IMPORT_BACKUP", "Backup importado")
                    st.success("Backup importado e dados atualizados.")
                    rerun_safe()
                else:
                    st.error("ZIP inválido (faltam CSVs obrigatórios).")
            except Exception as e:
                st.error(f"Erro ao ler ZIP: {e}")

    st.markdown("---")

    # ========= DIRETOR / GERENTE VIEW =========
    if role in ["Diretor","Gerente"]:
        st.subheader("Administração Geral")
        # Rooms
        with st.expander("🧱 Salas (Criar / Editar)", expanded=True):
            st.write("Salas:")
            st.dataframe(st.session_state.rooms, use_container_width=True)
            new_equipe = st.selectbox("Equipe (nova sala)", options=DISCIPLINAS, key="new_room_equipe")
            new_num = st.number_input("Número da sala", min_value=1, value=int(st.session_state.rooms["Sala"].max()+1), key="new_room_num")
            new_vagas = st.number_input("Vagas", min_value=1, max_value=20, value=VAGAS_POR_SALA_DEFAULT, key="new_room_vagas")
            if st.button("Criar sala"):
                if int(new_num) in st.session_state.rooms["Sala"].values:
                    st.warning("Número de sala já existe.")
                else:
                    salvar_snapshot()
                    st.session_state.rooms = pd.concat([st.session_state.rooms, pd.DataFrame([{"Sala":int(new_num),"Equipe":new_equipe,"Vagas":int(new_vagas)}])], ignore_index=True)
                    # add vagas to projetistas DF
                    for _ in range(int(new_vagas)):
                        st.session_state.projetistas = pd.concat([st.session_state.projetistas, pd.DataFrame([{"Sala":int(new_num),"Equipe":new_equipe,"Classe":"-","Projetista":"-","Pontuação":0,"Status":"Ativo"}])], ignore_index=True)
                    save_rooms(st.session_state.rooms); save_projetistas(st.session_state.projetistas)
                    registrar_log(cu["usuario"], role, "CRIAR_SALA", f"Sala {new_num} ({new_equipe}) com {new_vagas} vagas")
                    st.success("Sala criada com sucesso.")

        # Profiles management
        st.subheader("Perfis (Gerenciar usuários)")
        dfu = st.session_state.users.copy()
        st.dataframe(dfu[["usuario","nome","role","ativo","criado_em","ultimo_login","sala_atribuida"]], use_container_width=True)
        st.markdown("Ações sobre contas:")
        col1,col2,col3 = st.columns(3)
        with col1:
            sel = st.selectbox("Selecionar usuário", options=dfu["usuario"].tolist(), key="admin_sel")
        with col2:
            action = st.selectbox("Ação", options=["Ativar","Desativar","Resetar senha","Promover para Coordenador","Atribuir Sala"], key="admin_action")
        with col3:
            if action=="Resetar senha":
                newpw = st.text_input("Nova senha", key="admin_newpw")
            elif action=="Atribuir Sala":
                salas_opts = st.session_state.rooms["Sala"].tolist()
                atrib_sala = st.selectbox("Sala", options=salas_opts, key="admin_atrib_sala")
            else:
                newpw=None; atrib_sala=None
        if st.button("Executar ação"):
            salvar_snapshot()
            executor = cu["usuario"]
            if action=="Ativar":
                st.session_state.users.loc[st.session_state.users["usuario"]==sel,"ativo"]=True
                save_users(st.session_state.users)
                registrar_log(executor, role, "ATIVAR_USUARIO", sel)
                st.success("Usuário ativado.")
            elif action=="Desativar":
                if sel==executor and role=="Diretor":
                    st.error("Diretor não pode desativar a si mesmo.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"ativo"]=False
                    save_users(st.session_state.users)
                    registrar_log(executor, role, "DESATIVAR_USUARIO", sel)
                    st.success("Usuário desativado.")
            elif action=="Resetar senha":
                if not newpw:
                    st.error("Informe nova senha.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"senha_hash"]=hash_password(newpw)
                    save_users(st.session_state.users)
                    registrar_log(executor, role, "RESET_SENHA", f"{sel} nova senha")
                    st.success("Senha redefinida.")
            elif action=="Promover para Coordenador":
                st.session_state.users.loc[st.session_state.users["usuario"]==sel,"role"]="Coordenador"
                save_users(st.session_state.users)
                registrar_log(executor, role, "PROMOVER", f"{sel} promovido a Coordenador")
                st.success("Usuário promovido a Coordenador.")
            elif action=="Atribuir Sala":
                if atrib_sala is None:
                    st.error("Selecione sala.")
                else:
                    st.session_state.users.loc[st.session_state.users["usuario"]==sel,"sala_atribuida"]=int(atrib_sala)
                    save_users(st.session_state.users)
                    registrar_log(executor, role, "ATRIBUIR_SALA", f"{sel} -> sala {atrib_sala}")
                    st.success("Sala atribuída.")

        # Projetistas global
        st.markdown("---")
        st.subheader("Quadro de Projetistas (Global)")
        calcular_rankings()
        st.dataframe(st.session_state.projetistas[["Sala","Equipe","Projetista","Classe","Pontuação","Status"]], use_container_width=True)

        st.markdown("Ações rápidas sobre projetista:")
        cA,cB,cC = st.columns(3)
        with cA:
            disc_add = st.selectbox("Equipe ao adicionar", options=DISCIPLINAS, key="addproj_disc")
            salas_disp = st.session_state.rooms[st.session_state.rooms["Equipe"]==disc_add]["Sala"].tolist()
            sala_add = st.selectbox("Sala", options=salas_disp, key="addproj_sala")
            nome_add = st.text_input("Nome projetista (novo)", key="addproj_name")
            classe_add = st.selectbox("Classe", options=CLASSES, key="addproj_classe")
            if st.button("Adicionar projetista (global)"):
                vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==int(sala_add)) & (st.session_state.projetistas["Projetista"]=="-")]
                if vagas.empty:
                    st.error("Sala cheia.")
                else:
                    salvar_snapshot()
                    idx = vagas.index[0]
                    st.session_state.projetistas.loc[idx,["Projetista","Equipe","Classe","Pontuação","Status"]] = [nome_add.strip(), disc_add, classe_add, 0, "Ativo"]
                    save_projetistas(st.session_state.projetistas)
                    registrar_log(cu["usuario"], role, "ADICIONAR_PROJETISTA", f"{nome_add} -> sala {sala_add}")
                    st.success("Projetista adicionado.")
        with cB:
            sel_proj = st.selectbox("Selecionar projetista (inativar)", options=st.session_state.projetistas[st.session_state.projetistas["Projetista"]!="-"]["Projetista"].tolist(), key="inativar_sel")
            if st.button("Gerar relatório e Inativar"):
                salvar_snapshot()
                name = sel_proj
                hist_proj = st.session_state.historico[st.session_state.historico["Projetista"]==name]
                csvb = hist_proj.to_csv(index=False).encode("utf-8")
                fn = f"historico_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                st.download_button("⬇️ Baixar relatório do projetista", data=csvb, file_name=fn, mime="text/csv")
                # save pontos to inativos
                proj_idx = st.session_state.projetistas[st.session_state.projetistas["Projetista"]==name].index[0]
                pontos = int(st.session_state.projetistas.at[proj_idx,"Pontuação"])
                in_df = st.session_state.inativos
                in_df = pd.concat([in_df, pd.DataFrame([{"Projetista":name,"Pontuacao":pontos,"RemovidoEm":datetime.now().isoformat()}])], ignore_index=True)
                st.session_state.inativos = in_df
                save_inativos(in_df)
                # mark history entries as Inativo
                mask = st.session_state.historico["Projetista"]==name
                st.session_state.historico.loc[mask,"Projetista"] = st.session_state.historico.loc[mask,"Projetista"].apply(lambda x: f"{x} (Inativo)")
                # remove from quadro (libera vaga) but keep status as '-' in that row
                st.session_state.projetistas.loc[proj_idx,["Projetista","Classe","Pontuação","Status"]] = ["-","-",0,"Livre"]
                save_projetistas(st.session_state.projetistas)
                save_historico(st.session_state.historico)
                registrar_log(cu["usuario"], role, "INATIVAR_PROJETISTA", f"{name} inativado (pontos salvos: {pontos})")
                st.success("Projetista inativado e relatório gerado.")
        with cC:
            in_candidates = st.session_state.inativos["Projetista"].tolist() if not st.session_state.inativos.empty else []
            sel_re = st.selectbox("Projetista inativo", options=in_candidates if in_candidates else ["(nenhum)"], key="react_sel")
            sala_re = st.selectbox("Sala para reativar", options=st.session_state.rooms["Sala"].tolist(), key="react_sala")
            classe_re = st.selectbox("Classe ao reativar", options=CLASSES, key="react_classe")
            if st.button("Reativar projetista"):
                if sel_re == "(nenhum)":
                    st.info("Nenhum inativo disponível.")
                else:
                    vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==int(sala_re)) & (st.session_state.projetistas["Projetista"]=="-")]
                    if vagas.empty:
                        st.error("Sala sem vaga livre.")
                    else:
                        salvar_snapshot()
                        idx = vagas.index[0]
                        # restore pontos from inativos
                        row = st.session_state.inativos[st.session_state.inativos["Projetista"]==sel_re].iloc[0]
                        pontos_restore = int(row["Pontuacao"]) if pd.notna(row["Pontuacao"]) else 0
                        st.session_state.projetistas.loc[idx, ["Projetista","Classe","Pontuação","Status"]] = [sel_re, classe_re, pontos_restore, "Ativo"]
                        # remove from inativos
                        st.session_state.inativos = st.session_state.inativos[st.session_state.inativos["Projetista"]!=sel_re].reset_index(drop=True)
                        # remove (Inativo) suffix from historico
                        st.session_state.historico["Projetista"] = st.session_state.historico["Projetista"].apply(lambda x: x.replace(f"{sel_re} (Inativo)", sel_re) if isinstance(x,str) else x)
                        save_projetistas(st.session_state.projetistas); save_inativos(st.session_state.inativos); save_historico(st.session_state.historico)
                        registrar_log(cu["usuario"], role, "REATIVAR_PROJETISTA", f"{sel_re} reativado na sala {sala_re} com {pontos_restore} pontos")
                        st.success(f"Projetista {sel_re} reativado e pontuação restaurada ({pontos_restore}).")

        # Rankings for admin
        st.markdown("---")
        st.subheader("Rankings")
        calcular_rankings()
        df_act = st.session_state.projetistas[st.session_state.projetistas["Projetista"]!="-"]
        # Show class S first (as requested)
        for cls in ["S","A","B","C","D"]:
            sub = df_act[(df_act["Classe"]==cls) & (df_act["Status"]=="Ativo")].sort_values("Pontuação", ascending=False)
            if not sub.empty:
                st.write(f"### Classe {cls}")
                st.dataframe(sub[["Projetista","Equipe","Sala","Pontuação"]].reset_index(drop=True), use_container_width=True)
        st.write("### Ranking Geral")
        geral = df_act[df_act["Status"]=="Ativo"].sort_values("Pontuação", ascending=False).reset_index(drop=True)
        if not geral.empty:
            geral["RankingGeral"] = geral.index+1
            geral["RankingGeral"] = geral.apply(lambda x: x["RankingGeral"] if x["Pontuação"]>0 else "-", axis=1)
            st.dataframe(geral[["RankingGeral","Projetista","Equipe","Classe","Sala","Pontuação"]], use_container_width=True)

    # ========= COORDENADOR VIEW =========
    elif role == "Coordenador":
        st.subheader("Painel do Coordenador (sua sala)")
        # get assigned sala for this user
        urow = st.session_state.users[st.session_state.users["usuario"]==cu["usuario"]]
        sala_atr = urow["sala_atribuida"].values[0] if not urow.empty else ""
        if sala_atr=="" or (pd.isna(sala_atr) if isinstance(sala_atr,float) else False):
            st.warning("Nenhuma sala atribuída. Peça a um Diretor/Gerente para atribuir sua sala.")
        else:
            sala_num = int(sala_atr)
            st.info(f"Sala atribuída: {sala_num}")
            subset = st.session_state.projetistas[st.session_state.projetistas["Sala"]==sala_num]
            st.dataframe(subset[["Projetista","Classe","Pontuação","Status"]], use_container_width=True)
            # add projectistas in your room
            with st.expander("➕ Adicionar Projetista à minha sala"):
                nome_new = st.text_input("Nome do projetista", key="coord_add_name")
                classe_new = st.selectbox("Classe", options=CLASSES, key="coord_add_classe")
                if st.button("Adicionar à minha sala"):
                    vagas = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==sala_num) & (st.session_state.projetistas["Projetista"]=="-")]
                    if vagas.empty:
                        st.error("Sala cheia.")
                    else:
                        salvar_snapshot()
                        idx = vagas.index[0]
                        st.session_state.projetistas.loc[idx,["Projetista","Classe","Pontuação","Status"]] = [nome_new.strip(), classe_new, 0, "Ativo"]
                        save_projetistas(st.session_state.projetistas)
                        registrar_log(cu["usuario"], role, "ADICIONAR_PROJETISTA_SALA", f"{nome_new} -> sala {sala_num}")
                        st.success("Projetista adicionado à sua sala.")
            # create/validate demand
            with st.expander("📋 Criar Demanda e Validar Pontos"):
                dem_name = st.text_input("Nome da demanda", key="coord_dem_name")
                param = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key="coord_param")
                crit_ops = [f"{n} - {f} -> {r}" for (n,f,r) in CRITERIOS[param]]
                crit = st.selectbox("Critério", options=crit_ops, key="coord_crit")
                proj_options = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==sala_num) & (st.session_state.projetistas["Projetista"]!="-")]["Projetista"].tolist()
                proj_sel = st.selectbox("Selecionar projetista", options=proj_options if proj_options else ["(nenhum)"], key="coord_proj")
                if st.button("Validar e aplicar ponto"):
                    if not dem_name.strip() or proj_sel=="(nenhum)":
                        st.error("Preencha a demanda e selecione projetista.")
                    else:
                        try:
                            nota = int(crit.split(" - ")[0])
                            resumo = crit.split("->")[-1].strip()
                        except:
                            nota=None; resumo=""
                        salvar_snapshot()
                        pts = pontos_por_nota(nota)
                        if pts>0:
                            st.session_state.projetistas.loc[st.session_state.projetistas["Projetista"]==proj_sel,"Pontuação"] += pts
                        nova = {"Timestamp":pd.Timestamp.now(),"Disciplina":st.session_state.rooms[st.session_state.rooms["Sala"]==sala_num]["Equipe"].iat[0],"Demanda":dem_name.strip(),"Projetista":proj_sel,"Parâmetro":param,"Nota":nota,"Resumo":resumo,"PontosAtribuídos":pts}
                        st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
                        save_projetistas(st.session_state.projetistas); save_historico(st.session_state.historico)
                        registrar_log(cu["usuario"], role, "VALIDAR_PONTO", f"{proj_sel} +{pts} ({param}) - {dem_name.strip()}")
                        st.success("Demanda validada e histórico atualizado.")
            # Consolidate evaluations for coordinator
            with st.expander("⭐ Consolidação: Avaliações dos Projetistas ao Coordenador"):
                st.write("Projetistas avaliam o coordenador (anônimo). Aqui você consolida e aplica pontos ao seu usuário (coordenador).")
                # find evaluations for this coordinator in historico (Demanda starting with 'AVALIACAO_COORDENADOR:<coord_user>')
                coord_evals = st.session_state.historico[st.session_state.historico["Demanda"].str.startswith(f"AVALIACAO_COORDENADOR:{cu['usuario']}", na=False)]
                if coord_evals.empty:
                    st.info("Nenhuma avaliação registrada para você.")
                else:
                    st.dataframe(coord_evals, use_container_width=True)
                    if st.button("Consolidar e aplicar pontos"):
                        salvar_snapshot()
                        # compute mean per parameter across projetistas from this sala
                        sala_proj = st.session_state.projetistas[(st.session_state.projetistas["Sala"]==sala_num) & (st.session_state.projetistas["Status"]=="Ativo")]["Projetista"].tolist()
                        # filter evaluations where Projetista in sala_proj
                        rel = coord_evals[coord_evals["Projetista"].isin(sala_proj)]
                        if rel.empty:
                            st.warning("Avaliações recebidas não provêm de projetistas desta sala (nenhuma aplicável).")
                        else:
                            total_aplicado = 0.0
                            for param, g in rel.groupby("Parâmetro"):
                                avg = g["Nota"].mean()
                                pts = 0.0
                                if avg >= 9: pts = 1.0
                                elif avg >= 8: pts = 0.5
                                else: pts = 0.0
                                # record in historico as application to coordinator (Demanda/entry)
                                nova = {"Timestamp":pd.Timestamp.now(),"Disciplina":st.session_state.rooms[st.session_state.rooms["Sala"]==sala_num]["Equipe"].iat[0],"Demanda":f"COORD_APLICACAO:{param}","Projetista":cu["usuario"],"Parâmetro":param,"Nota":round(avg,2),"Resumo":"Consolidação avaliações projetistas","PontosAtribuídos":pts}
                                st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
                                total_aplicado += pts
                            save_historico(st.session_state.historico)
                            registrar_log(cu["usuario"], role, "CONSOLIDAR_AVALS_COORD", f"Aplicado {total_aplicado} pontos (sala {sala_num})")
                            st.success(f"Avaliações consolidadas — total de pontos aplicados: {total_aplicado}")

    # ========= PROJETISTA VIEW =========
    elif role == "Projetista":
        st.subheader("Painel do Projetista")
        nome = cu["nome"]
        # find row in projetistas DF where Projetista == nome
        quadro = st.session_state.projetistas[st.session_state.projetistas["Projetista"]==nome]
        if quadro.empty:
            st.info("Você não está alocado em nenhuma sala. Peça ao coordenador para alocar seu nome no quadro.")
        else:
            ent = quadro.iloc[0]
            st.markdown(f"**Sala:** {ent['Sala']} • **Equipe:** {ent['Equipe']} • **Classe:** {ent['Classe']} • **Pontos:** {ent['Pontuação']}")
            myhist = st.session_state.historico[st.session_state.historico["Projetista"]==nome].sort_values("Timestamp", ascending=False).reset_index(drop=True)
            st.dataframe(myhist, use_container_width=True)
            # create own demand
            with st.expander("➕ Criar Demanda (minha)"):
                dname = st.text_input("Nome da demanda", key="proj_dem_name")
                param = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key="proj_param")
                crits = [f"{n} - {f} -> {r}" for (n,f,r) in CRITERIOS[param]]
                crit_choice = st.selectbox("Critério", options=crits, key="proj_crit")
                if st.button("Registrar demanda (minha)"):
                    if not dname.strip():
                        st.warning("Informe nome da demanda.")
                    else:
                        try:
                            nota = int(crit_choice.split(" - ")[0])
                            resumo = crit_choice.split("->")[-1].strip()
                        except:
                            nota=None; resumo=""
                        salvar_snapshot()
                        pts = pontos_por_nota(nota)
                        sala_num = int(ent["Sala"])
                        disciplina = st.session_state.rooms[st.session_state.rooms["Sala"]==sala_num]["Equipe"].iat[0]
                        nova = {"Timestamp":pd.Timestamp.now(),"Disciplina":disciplina,"Demanda":dname.strip(),"Projetista":nome,"Parâmetro":param,"Nota":nota,"Resumo":resumo,"PontosAtribuídos":pts}
                        st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
                        if pts>0:
                            st.session_state.projetistas.loc[st.session_state.projetistas["Projetista"]==nome,"Pontuação"] += pts
                            save_projetistas(st.session_state.projetistas)
                        save_historico(st.session_state.historico)
                        registrar_log(cu["usuario"], role, "CRIAR_DEMANDA_PROPRIA", f"{dname.strip()} criado por {nome}")
                        st.success("Demanda criada e ponto aplicado (se aplicável).")
            # evaluate coordinator
            with st.expander("⭐ Avaliar meu Coordenador (anônimo)"):
                sala_num = int(ent["Sala"])
                coord_row = st.session_state.users[st.session_state.users["sala_atribuida"]==sala_num]
                if coord_row.empty:
                    st.info("Nenhum coordenador atribuído a esta sala.")
                else:
                    coord_user = coord_row.iloc[0]["usuario"]
                    coord_name = coord_row.iloc[0]["nome"]
                    st.write(f"Avaliar Coordenador: **{coord_name}** (sala {sala_num})")
                    param_eval = st.selectbox("Parâmetro", options=list(CRITERIOS.keys()), key="aval_param")
                    crits_eval = [f"{n} - {f} -> {r}" for (n,f,r) in CRITERIOS[param_eval]]
                    crit_eval = st.selectbox("Critério", options=crits_eval, key="aval_crit")
                    if st.button("Enviar avaliação"):
                        try:
                            nota = int(crit_eval.split(" - ")[0])
                            resumo = crit_eval.split("->")[-1].strip()
                        except:
                            nota=None; resumo=""
                        salvar_snapshot()
                        nova = {"Timestamp":pd.Timestamp.now(),"Disciplina":ent["Equipe"],"Demanda":f"AVALIACAO_COORDENADOR:{coord_user}","Projetista":nome,"Parâmetro":param_eval,"Nota":nota,"Resumo":resumo,"PontosAtribuídos":None}
                        st.session_state.historico = pd.concat([pd.DataFrame([nova]), st.session_state.historico], ignore_index=True)
                        save_historico(st.session_state.historico)
                        registrar_log(cu["usuario"], role, "AVALIAR_COORDENADOR", f"{nome} avaliou {coord_user} ({param_eval}={nota})")
                        st.success("Avaliação enviada (anônima).")

    # else other roles (rare)
    else:
        st.info("Painel ainda em desenvolvimento para seu papel.")

    # footer: show logs for authorized roles
    st.markdown("---")
    if role in ["Diretor","Gerente","Coordenador"]:
        st.subheader("📜 Log de Gestão")
        ensure_log()
        log_df = pd.read_csv(LOG_CSV, parse_dates=["timestamp"])
        st.dataframe(log_df.head(300), use_container_width=True)
else:
    st.info("Faça login para usar o painel (barra lateral).")

# Persist todas alterações antes de finalizar
save_users(st.session_state.users)
save_rooms(st.session_state.rooms)
save_projetistas(st.session_state.projetistas)
save_historico(st.session_state.historico)
save_inativos(st.session_state.inativos)
ensure_log()
