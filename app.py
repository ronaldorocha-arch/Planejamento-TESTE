import streamlit as st
import pandas as pd
import math
import requests
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="Planejamento de Produção - NHS", page_icon="🏭", layout="wide")

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

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

# --- FUNÇÃO DE CLIMA (AGORA EM CELSIUS) ---
def pegar_clima():
    try:
        # O parâmetro &m força o sistema métrico (Celsius)
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt&m"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            return response.text.strip().replace('+', '')
        return "Clima indisponível"
    except:
        return "Clima indisponível"

@st.cache_data(ttl=5)
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        m_row, m_col = -1, -1
        # Busca onde está a palavra MODELO em qualquer lugar da planilha
        for r in range(min(100, len(df_raw))):
            for c in range(len(df_raw.columns)):
                if "MODELO" in str(df_raw.iloc[r, c]).upper():
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
            
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, celula_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            unidade = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            descricao = str(dados.iloc[i, m_col+2]).strip()
            # Tenta achar a UPS/Célula nas colunas próximas
            cel_na_linha = str(dados.iloc[i, m_col+3]).strip().upper()
            
            if any(x in cel_na_linha for x in ["UPS", "ACS", "ACE"]):
                celula_atual = str(dados.iloc[i, m_col+3]).strip()
            
            if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade, 'DESCRICAO': descricao,
                    'CEL_ORIGEM': celula_atual, 
                    'DISPLAY': f"[{celula_atual}] {modelo} - {descricao} ({int(unidade)} pç/h)"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        return pd.DataFrame()

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
    
    def aplicar_conversao(row):
        u_b = row['UNIDADE_HORA']
        orig = row['CEL_ORIGEM']
        n_orig = REGRAS_HORARIOS.get(orig, {"n_nat": regra_destino['n_nat']})['n_nat']
        return (u_b / n_orig) * n_dia

    df_in['CAD_R'] = df_in.apply(aplicar_conversao, axis=1)
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    
    total_d, res, acum, c_idx, tot = df_in['FALTA'].sum(), [], 0.0, 0, 0
    termino = "Não finalizado"
    
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
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("📋 Planejamento NHS")
        lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
        sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
        regra_atual = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
        h_ini = st.sidebar.text_input("Início da Produção", value="07:45")
        tem_gin = st.sidebar.checkbox("Haverá Ginástica Laboral?", value=False)
        n_dia = st.sidebar.number_input(f"Pessoas na {sel_ups}", value=regra_atual['n_nat'], min_value=1)
        liberar_modelos = st.sidebar.checkbox("🔓 Ver todos os modelos?", value=False)
        opcoes = sorted(base['DISPLAY'].tolist()) if liberar_modelos else sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())

        col_tit, col_clim, col_btn = st.columns([0.45, 0.4, 0.15])
        col_tit.header(f"📋 Célula: {sel_ups}")
        col_clim.markdown(f"<div style='font-size: 20px; padding-top: 10px;'>📍 Curitiba: <b>{pegar_clima()}</b></div>", unsafe_allow_html=True)
        
        if col_btn.button("🗑️ Limpar"):
            st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
            st.rerun()

        df_editor = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
            column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True), "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)}, 
            key=f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}")

        if st.button("🚀 Gerar Planejamento"):
            df_validos = df_editor.dropna(subset=['Equipamento'])
            if not df_validos.empty:
                r = calcular(df_validos, base, h_ini, n_dia, tem_gin, regra_atual)
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
                c2.metric("Término Estimado", r['termino'])
                c3.metric("Lotação", f"{n_dia} pessoas")
                st.dataframe(r['df'], use_container_width=True)
            else:
                st.warning("Adicione modelos e quantidades.")
    else:
        st.error("⚠️ Cabeçalho 'MODELO' não encontrado na planilha.")
except Exception as e:
    st.error(f"Erro Crítico: {e}")
