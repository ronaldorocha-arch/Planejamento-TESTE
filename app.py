import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Planejamento NHS - Produção", page_icon="🏭", layout="wide")

# --- DADOS DA SUA URL ---
ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
GID_DA_ABA = "0" # Confirme se a aba 'PYTHON/PROGRAMAÇÃO' é a primeira da esquerda
# -----------------------

URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid={GID_DA_ABA}"

# --- REGRAS DE HORÁRIOS (MANUTENÇÃO DAS SUAS REGRAS) ---
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

@st.cache_data(ttl=2)
def carregar_base():
    try:
        # Download dos dados via Requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(URL_BASE, headers=headers, timeout=10)
        
        if response.status_code != 200:
            st.error(f"Erro de conexão: Status {response.status_code}")
            return pd.DataFrame()

        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        # BUSCA DINÂMICA: Localiza a palavra "MODELO" em qualquer lugar das primeiras 100 linhas
        m_row, m_col = -1, -1
        for r in range(min(100, len(df_raw))):
            for c in range(min(25, len(df_raw.columns))):
                if "MODELO" in str(df_raw.iloc[r, c]).upper():
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
            
        if m_row == -1:
            st.warning("⚠️ Cabeçalho 'MODELO' não encontrado. Verifique se a aba correta está em primeiro lugar.")
            with st.expander("Diagnóstico: O que o sistema leu da planilha?"):
                st.dataframe(df_raw.head(10))
            return pd.DataFrame()

        # Extração a partir do cabeçalho encontrado
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, celula_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            cadencia = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            desc = str(dados.iloc[i, m_col+2]).strip()
            
            # Localiza a UPS (costuma estar na coluna m_col+3 ou m_col+5)
            for offset in range(3, 8):
                if m_col+offset < len(dados.columns):
                    val = str(dados.iloc[i, m_col+offset]).strip().upper()
                    if any(x in val for x in ["UPS", "ACS", "ACE"]):
                        celula_atual = str(dados.iloc[i, m_col+offset]).strip()
                        break
            
            if modelo != 'nan' and len(modelo) > 2 and not pd.isna(cadencia):
                lista_final.append({
                    'ID': modelo, 'CADENCIA': cadencia, 'DESC': desc,
                    'UPS': celula_atual, 
                    'DISPLAY': f"[{celula_atual}] {modelo} - {desc} ({int(cadencia)} pç/h)"
                })
        
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Falha Crítica: {e}")
        return pd.DataFrame()

# --- LÓGICA DE GRADE E CÁLCULOS ---
def gerar_grade(h_ini, regras):
    def para_min(s):
        h, m = map(int, s.split(':'))
        return h * 60 + m
    m_ini = para_min(h_ini)
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_m, m_cafe_t = para_min(regras['cafe_m']), para_min(regras['cafe_t'])
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini] + [m for m in marcos if para_min(m) > m_ini]
    res = []
    for i in range(len(pontos)-1):
        p1, p2 = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p1 == m_alm_i and p2 == m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p1, p2):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        res.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 ALMOÇO" if is_alm else None})
    return pd.DataFrame(res)

def calcular(df_ed, df_ba, h_ini, n_dia, regra):
    slots = gerar_grade(h_ini, regra)
    df_ed = df_ed.merge(df_ba[['DISPLAY', 'ID', 'CADENCIA', 'UPS']], left_on='Modelo', right_on='DISPLAY', how='left')
    df_ed['CAD_REAL'] = (df_ed['CADENCIA'] / REGRAS_HORARIOS.get(df_ed['UPS'].iloc[0], {"n_nat": n_dia})['n_nat']) * n_dia
    df_ed['T_PC'] = 60 / df_ed['CAD_REAL']
    df_ed['FALTA'] = pd.to_numeric(df_ed['Qtd'], errors='coerce').fillna(0)
    total_ped = df_ed['FALTA'].sum()
    res, acum, idx, tot, termino = [], 0.0, 0, 0, "Não finalizado"
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acum': int(tot)})
            continue
        acum += s['Minutos']
        p_h, m_n = 0, []
        while idx < len(df_ed):
            t_pc = df_ed.loc[idx, 'T_PC']
            if acum >= (t_pc - 0.0001):
                q = min(math.floor(acum / t_pc + 0.0001), df_ed.loc[idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_pc); df_ed.loc[idx, 'FALTA'] -= q
                    tot += q; p_h += q; m_n.append(f"{df_ed.loc[idx, 'ID']} ({int(q)})")
                if df_ed.loc[idx, 'FALTA'] <= 0: idx += 1
                else: break
            else: break
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(m_n) if m_n else "-", 'Peças': int(p_h), 'Acum': int(tot)})
        if tot >= total_ped and termino == "Não finalizado" and total_ped > 0:
            m_s = s['Minutos'] - acum
            h_h, m_m = s['Horário'].split(' – ')[0].split(':')
            dt = datetime.strptime(f"{h_h}:{m_m}", "%H:%M") + timedelta(minutes=int(m_s))
            termino = dt.strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.title("⚙️ Painel de Controle")
    lista_ups = sorted(base['UPS'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Escolha a Célula", lista_ups)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", "07:45")
    n_dia = st.sidebar.number_input("Equipe (Pessoas)", value=regra_at['n_nat'], min_value=1)
    
    st.header(f"📋 Planejamento de Produção: {sel_ups}")
    opcoes = sorted(base[base['UPS'] == sel_ups]['DISPLAY'].tolist())
    df_input = st.data_editor(pd.DataFrame(columns=["Modelo", "Qtd"]), num_rows="dynamic", use_container_width=True,
                           column_config={"Modelo": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True),
                                         "Qtd": st.column_config.NumberColumn("Quantidade", min_value=1)})

    if st.button("🚀 Gerar Planejamento"):
        df_valid = df_input.dropna(subset=['Modelo'])
        if not df_valid.empty:
            r = calcular(df_valid, base, h_ini, n_dia, regra_at)
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
            c2.metric("Término Estimado", r['termino'])
            c3.metric("Lotação", f"{n_dia} pessoas")
            st.table(r['df'])
else:
    st.error("⚠️ Erro Crítico: Base de dados não carregada. Mova a aba correta para a primeira posição no Google Sheets.")
