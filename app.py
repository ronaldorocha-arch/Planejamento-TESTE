import streamlit as st
import pandas as pd
import math
import requests
from datetime import datetime, timedelta

# 1. Configuração da página
st.set_page_config(page_title="Planejamento de Produção - NHS", page_icon="🏭", layout="wide")

# URL da sua planilha (Garante que pegue a aba correta e formato CSV)
# DICA: Verifique se o GID ainda é 0. Se mudaram a aba de lugar, o GID muda.
URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# --- CONFIGURAÇÃO DE HORÁRIOS ---
REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco": "11:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco": "11:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco": "11:50", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 4": {"cafe_m": "09:20", "almoco": "11:45", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 6": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:30", "n_nat": 4},
    "UPS - 7": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "UPS - 8": {"cafe_m": "09:40", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 3},
}

# --- FUNÇÃO DE CLIMA (FORÇANDO CELSIUS) ---
def pegar_clima():
    try:
        # 'm' força Celsius, 'format=1' traz só o essencial para evitar erros de texto
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt&m"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text.strip().replace('+', '')
        return "Clima indisponível"
    except:
        return "Clima indisponível"

# --- CARREGAMENTO DA BASE COM DIAGNÓSTICO ---
@st.cache_data(ttl=1) # TTL baixo para forçar atualização enquanto testamos
def carregar_base():
    try:
        # Adicionamos um cabeçalho de usuário para o Google não bloquear a requisição
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(URL_BASE, headers=headers)
        
        if response.status_code != 200:
            st.error(f"Erro ao acessar Google Sheets: Status {response.status_code}")
            return pd.DataFrame()

        from io import StringIO
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        # BUSCA DA PALAVRA "MODELO"
        m_row, m_col = -1, -1
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1:
            st.error("⚠️ Coluna 'MODELO' não encontrada. Alguém alterou o nome na planilha?")
            with st.expander("Ver o que o sistema está lendo agora"):
                st.dataframe(df_raw.head(20))
            return pd.DataFrame()

        # Extração
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final = []
        celula_atual = "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            unidade = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            descricao = str(dados.iloc[i, m_col+2]).strip()
            cel_na_linha = str(dados.iloc[i, m_col+3]).strip().upper()
            
            if any(x in cel_na_linha for x in ["UPS", "ACS", "ACE", "LINHA"]):
                celula_atual = str(dados.iloc[i, m_col+3]).strip()
                
            if modelo != 'nan' and len(modelo) > 2 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade, 'DESCRICAO': descricao,
                    'CEL_ORIGEM': celula_atual, 
                    'DISPLAY': f"[{celula_atual}] {modelo} - {descricao} ({int(unidade)} pç/h)"
                })
        
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro Crítico de Conexão: {e}")
        return pd.DataFrame()

# --- CÁLCULOS ---
def gerar_grade_fixa(h_ini_input, regras, tem_gin):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    
    m_cafe_m = para_min(regras['cafe_m'])
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_t = para_min(regras['cafe_t'])
    m_gin = para_min("09:30")
    
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > para_min(h_ini_input)]
    
    grade = []
    for i in range(len(pontos)-1):
        p_i, p_f = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p_i == m_alm_i and p_f == m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p_i, p_f):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (tem_gin and m_gin <= m < m_gin+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 INTERVALO DE ALMOÇO" if is_alm else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, n_dia, tem_gin, regra_destino):
    slots = gerar_grade_fixa(h_ini, regra_destino, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY', how='left')
    
    df_in['CAD_R'] = (df_in['UNIDADE_HORA'] / REGRAS_HORARIOS.get(df_in['CEL_ORIGEM'].iloc[0], {"n_nat": n_dia})['n_nat']) * n_dia
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    
    total_d = df_in['FALTA'].sum()
    res, acum, c_idx, tot = [], 0.0, 0, 0
    termino = "Não finalizado"
    
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acumulada': int(tot)})
            continue
        
        acum += s['Minutos']
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            if acum >= (t_p - 0.0001):
                q = min(math.floor(acum / t_p + 0.0001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)} pçs)")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(mods) if mods else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        
        if tot >= total_d and termino == "Não finalizado" and total_d > 0:
            m_u = s['Minutos'] - acum
            h_s, m_s = s['Horário'].split(' – ')[0].split(':')
            dt_b = datetime.strptime(f"{h_s}:{m_s}", "%H:%M") + timedelta(minutes=int(m_u))
            termino = dt_b.strftime("%H:%M")
            
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- UI ---
base = carregar_base()

if not base.empty:
    st.sidebar.title("📋 Planejamento NHS")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Célula", lista_ups)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    
    liberar = st.sidebar.checkbox("🔓 Ver todos os modelos", value=False)
    h_ini = st.sidebar.text_input("Início", value="07:45")
    n_dia = st.sidebar.number_input(f"Pessoas na {sel_ups}", value=regra_at['n_nat'], min_value=1)

    opcoes = sorted(base['DISPLAY'].tolist()) if liberar else sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())

    c1, c2 = st.columns([0.6, 0.4])
    c1.header(f"🏭 {sel_ups}")
    c2.subheader(f"🌡️ {pegar_clima()}")

    df_ed = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                           column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes),
                                         "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)})

    if st.button("🚀 Gerar"):
        df_v = df_ed.dropna(subset=['Equipamento'])
        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, False, regra_at)
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("Total", f"{int(r['tot'])} pçs")
            col2.metric("Término", r['termino'])
            col3.metric("Lotação", f"{n_dia} pessoas")
            st.dataframe(r['df'], use_container_width=True)
