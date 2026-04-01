import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Planejamento de Produção - NHS", page_icon="🏭", layout="wide")

# Link direto para a aba 'BASE' (gid=0)
ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid=0"

# --- CONFIGURAÇÃO DE HORÁRIOS REAIS ---
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

def pegar_clima():
    try:
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt&m"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            return response.text.strip().replace('+', '')
        return "Clima indisponível"
    except: return "Clima indisponível"

@st.cache_data(ttl=2)
def carregar_base():
    try:
        # Request com headers para evitar bloqueios
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(URL_BASE, headers=headers, timeout=10)
        if response.status_code != 200: return pd.DataFrame()
        
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        m_row, m_col = -1, -1
        # Busca o MODELO que tem dados abaixo (Coluna G na sua foto)
        for r in range(min(60, len(df_raw))):
            for c in range(len(df_raw.columns)):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    # Checa se há dados reais abaixo para não pegar a coluna errada
                    if str(df_raw.iloc[r+2, c]).lower() != 'nan':
                        m_row, m_col = r, c
                        break
            if m_row != -1: break
            
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, cel_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            # Cadência, Descrição e UPS
            try:
                unid = pd.to_numeric(dados.iloc[i, m_col+1].replace(',', '.'), errors='coerce')
                desc = str(dados.iloc[i, m_col+2]).strip()
                
                # Busca UPS nas colunas próximas
                for off in [3, 4, 5]:
                    c_val = str(dados.iloc[i, m_col+off]).strip().upper()
                    if any(x in c_val for x in ["UPS", "ACS", "ACE"]):
                        cel_atual = str(dados.iloc[i, m_col+off]).strip()
                        break

                if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unid):
                    lista_final.append({
                        'ID': modelo, 'UNIDADE_HORA': unid, 'DESCRICAO': desc,
                        'CEL_ORIGEM': cel_atual, 
                        'DISPLAY': f"[{cel_atual}] {modelo} - {desc} ({int(unid)} pç/h)"
                    })
            except: continue
        return pd.DataFrame(lista_final)
    except: return pd.DataFrame()

# LÓGICA DE GRADE E CÁLCULO MANTIDA IGUAL
def gerar_grade_fixa(h_ini_input, regras):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    m_ini = para_min(h_ini_input)
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_m, m_cafe_t = para_min(regras['cafe_m']), para_min(regras['cafe_t'])
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > m_ini]
    res = []
    for i in range(len(pontos)-1):
        p1, p2 = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p1 == m_alm_i and p2 == m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p1, p2):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        res.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 INTERVALO DE ALMOÇO" if is_alm else None})
    return pd.DataFrame(res)

def calcular(df_in, df_ba, h_ini, n_dia, regra):
    slots = gerar_grade_fixa(h_ini, regra)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = (df_in['UNIDADE_HORA'] / 5) * n_dia
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    total_d, res, acum, c_idx, tot, termino = df_in['FALTA'].sum(), [], 0.0, 0, 0, "Não finalizado"
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acumulada': int(tot)})
            continue
        acum += s['Minutos']
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            if acum >= (t_p - 0.001):
                q = min(math.floor(acum / t_p + 0.001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q; mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)} pçs)")
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

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.title("📋 Planejamento NHS")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", value="07:45")
    n_dia = st.sidebar.number_input(f"Pessoas na {sel_ups}", value=regra_at['n_nat'], min_value=1)

    col_tit, col_clim, col_btn = st.columns([0.45, 0.4, 0.15])
    col_tit.header(f"📋 {sel_ups}")
    col_clim.markdown(f"<div style='font-size: 20px; padding-top: 10px;'>📍 Curitiba: <b>{pegar_clima()}</b></div>", unsafe_allow_html=True)
    if col_btn.button("🗑️ Limpar"):
        st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
        st.rerun()

    df_ed = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
        column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist()), required=True), "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)}, 
        key=f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}")

    if st.button("🚀 Gerar Planejamento"):
        df_v = df_ed.dropna(subset=['Equipamento'])
        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, regra_at)
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
            c2.metric("Término Estimado", r['termino'])
            c3.metric("Lotação", f"{n_dia} pessoas")
            st.table(r['df'])
else:
    st.error("⚠️ Base de dados não carregada. Verifique se a aba 'BASE' é a primeira da planilha.")
