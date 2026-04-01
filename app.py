import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# 1. Ajuste a URL com o GID que você encontrou no navegador
# Exemplo: se o final da sua URL for gid=112233, coloque 112233 abaixo
GID_CORRETO = "0" 
URL_BASE = f"https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid={GID_CORRETO}"

st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

@st.cache_data(ttl=2)
def carregar_base():
    try:
        response = requests.get(URL_BASE)
        if response.status_code != 200:
            st.error("Erro ao acessar o Google Sheets. Verifique se a planilha está 'Publicada na Web'.")
            return pd.DataFrame()
            
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        m_row, m_col = -1, -1
        # Busca exaustiva: varre as primeiras 100 linhas e 20 colunas
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
            
        if m_row == -1:
            # Se não achar, mostra o que ele está lendo para ajudar no diagnóstico
            with st.expander("Clique para ver o diagnóstico da planilha"):
                st.write("O sistema não achou a palavra 'MODELO'. Abaixo está o que ele leu:")
                st.dataframe(df_raw.head(10))
            return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, cel_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            unid = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            desc = str(dados.iloc[i, m_col+2]).strip()
            
            # Procura a célula (UPS) nas colunas próximas (J na sua imagem é m_col+5)
            for offset in [3, 4, 5]:
                col_val = str(dados.iloc[i, m_col+offset]).strip().upper()
                if any(x in col_val for x in ["UPS", "ACS", "ACE"]):
                    cel_atual = str(dados.iloc[i, m_col+offset]).strip()
                    break

            if mod != 'nan' and len(mod) > 2 and not pd.isna(unid):
                lista_final.append({
                    'ID': mod, 'UNIDADE_HORA': unid, 'DESCRICAO': desc,
                    'CEL_ORIGEM': cel_atual, 
                    'DISPLAY': f"[{cel_atual}] {mod} - {desc} ({int(unid)} pç/h)"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro Crítico: {e}")
        return pd.DataFrame()

# --- REGRAS E CÁLCULOS (IGUAIS AO ANTERIOR) ---
REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco": "11:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco": "11:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco": "11:50", "cafe_t": "15:10", "n_nat": 3},
}

def gerar_grade_fixa(h_ini_input, regras):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    m_cafe_m, m_alm_i, m_alm_f, m_cafe_t = para_min(regras['cafe_m']), para_min("11:30"), para_min("12:30"), para_min(regras['cafe_t'])
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > para_min(h_ini_input)]
    grade = []
    for i in range(len(pontos)-1):
        p_i, p_f = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p_i == m_alm_i and p_f == m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p_i, p_f):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 ALMOÇO" if is_alm else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, n_dia, regra_at):
    slots = gerar_grade_fixa(h_ini, regra_at)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = (df_in['UNIDADE_HORA'] / REGRAS_HORARIOS.get(df_in['CEL_ORIGEM'].iloc[0], {"n_nat": n_dia})['n_nat']) * n_dia
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

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.title("📋 Planejamento NHS")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Célula", lista_ups)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", "07:45")
    n_dia = st.sidebar.number_input("Pessoas", value=regra_at['n_nat'], min_value=1)
    
    st.header(f"🏭 {sel_ups}")
    opcoes = sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())
    df_ed = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                           column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes), "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)})

    if st.button("🚀 Gerar"):
        df_v = df_ed.dropna(subset=['Equipamento'])
        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, regra_at)
            st.metric("Término Estimado", r['termino'], delta=f"Total: {int(r['tot'])} pçs")
            st.dataframe(r['df'], use_container_width=True)
else:
    st.error("⚠️ Planilha não carregada. Certifique-se de que a aba 'PYTHON/PROGRAMAÇÃO' é a primeira da planilha ou use o GID correto.")
