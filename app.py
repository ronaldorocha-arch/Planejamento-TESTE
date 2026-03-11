import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="🧪 LAB MULTI-PRINT - Planejador NHS", page_icon="🧪", layout="wide")

# --- ESTILO PARA IMPRESSÃO ECONÔMICA ---
st.markdown("""
    <style>
    @media print {
        section[data-testid="stSidebar"], .stButton, footer, header {
            display: none !important;
        }
        .main .block-container {
            padding: 0 !important;
            margin: 0 !important;
        }
        h1, h2, h3 {
            font-size: 18px !important;
            margin-bottom: 5px !important;
            margin-top: 10px !important;
        }
        .stMetric {
            border: 1px solid #000;
            padding: 2px !important;
            font-size: 12px !important;
        }
        div[data-testid="stTable"] {
            font-size: 10px !important;
        }
        table {
            width: 100% !important;
        }
        .ups-header {
            border-top: 2px solid #000;
            margin-top: 20px;
        }
        /* Tenta evitar quebrar uma tabela no meio */
        div.stTable {
            page-break-inside: avoid !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco": "11:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco": "11:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco": "11:50", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 4": {"cafe_m": "09:20", "almoco": "11:45", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 6": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:30", "n_nat": 4},
    "UPS - 7": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "UPS - 8": {"cafe_m": "09:40", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 2},
}

@st.cache_data(ttl=5)
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        # Localiza a linha que contém "MODELO" na coluna G (índice 6)
        m_row = -1
        for r in range(len(df_raw)):
            if "MODELO" in str(df_raw.iloc[r, 6]).upper():
                m_row = r
                break
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final = []
        # Captura modelos de forma global para não travar a lista
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, 6]).strip()
            unidade = pd.to_numeric(dados.iloc[i, 7], errors='coerce')
            celula = str(dados.iloc[i, 9]).strip()
            if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade,
                    'CELULA': celula, 'DISPLAY': f"[{celula}] {modelo}"
                })
        return pd.DataFrame(lista_final)
    except: return pd.DataFrame()

def gerar_grade_fixa(h_ini_input, regras, tem_gin):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    m_cafe_m, m_alm_ini, m_alm_fim, m_cafe_t, m_gin = para_min(regras['cafe_m']), para_min("11:30"), para_min("12:30"), para_min(regras['cafe_t']), para_min("09:30")
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > para_min(h_ini_input)]
    grade = []
    for i in range(len(pontos)-1):
        p_ini, p_fim = para_min(pontos[i]), para_min(pontos[i+1])
        is_almoco = (p_ini == m_alm_ini and p_fim == m_alm_fim)
        m_uteis = 0
        if not is_almoco:
            for m in range(p_ini, p_fim):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_alm_ini <= m < m_alm_fim) or 
                        (m_cafe_t <= m < m_cafe_t+10) or (tem_gin and m_gin <= m < m_gin+10)):
                    m_uteis += 1
        grade.append({'Horário': f"{pontos[i]}–{pontos[i+1]}", 'Minutos': m_uteis, 'Label': "🍱 ALMOÇO" if is_almoco else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin, regras):
    slots = gerar_grade_fixa(h_ini, regras, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['T_PC'] = 60 / (df_in['UNIDADE_HORA'] * fat)
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    res, acum, c_idx, tot = [], 0.0, 0, 0
    total_desejado = df_in['FALTA'].sum()
    termino = "---"
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Total': tot})
            continue
        acum += s['Minutos']
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            if acum >= (t_p - 0.001):
                q = min(math.floor(acum/t_p + 0.001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q*t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    mods.append(f"{df_in.loc[c_idx, 'ID']}({int(q)})")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        res.append({'Horário': s['Horário'], 'Modelos': "+".join(mods) if mods else "-", 'Peças': int(p_b), 'Total': int(tot)})
        if tot >= total_desejado and termino == "---" and total_desejado > 0:
            m_usados = s['Minutos'] - acum
            h_s, m_s = s['Horário'].split('–')[0].split(':')
            termino = (datetime.strptime(f"{h_s}:{m_s}", "%H:%M") + timedelta(minutes=m_usados)).strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.title("⚙️ Configuração")
    lista_ups = sorted(REGRAS_HORARIOS.keys())
    selecionadas = st.sidebar.multiselect("UPS Ativas", lista_ups, default=["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", value="07:45")
    tem_gin = st.sidebar.checkbox("Ginástica?", value=False)
    
    dados_entrada = {}
    for ups in selecionadas:
        with st.expander(f"Entrada: {ups}", expanded=True):
            regra = REGRAS_HORARIOS[ups]
            # Busca todas as peças da base para garantir que apareçam
            opcoes = sorted(base['DISPLAY'].unique().tolist())
            c1, c2 = st.columns(2)
            n_nat = c1.number_input(f"N Nat", value=regra['n_nat'], key=f"n_{ups}")
            n_dia = c2.number_input(f"N Dia", value=regra['n_nat'], key=f"d_{ups}")
            editor = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes), "Qtd": st.column_config.NumberColumn("Qtd")}, key=f"e_{ups}")
            dados_entrada[ups] = {"df": editor, "fator": n_dia/n_nat, "regra": regra}

    if st.button("🚀 GERAR TUDO"):
        for ups, info in dados_entrada.items():
            if not info['df'].empty:
                r = calcular(info['df'], base, h_ini, info['fator'], tem_gin, info['regra'])
                st.markdown(f'<div class="ups-header"></div>', unsafe_allow_html=True)
                st.subheader(f"QUADRO: {ups}")
                m1, m2, m3 = st.columns(3)
                m1.write(f"**Total:** {int(r['tot'])}")
                m2.write(f"**Término:** {r['termino']}")
                m3.write(f"**Eficiência:** {info['fator']:.2%}")
                st.table(r['df'])
        
        st.markdown('<button onclick="window.print()" style="width:100%; padding:15px; background:#4CAF50; color:white; border:none; cursor:pointer;">🖨️ IMPRIMIR ECONOMIZANDO FOLHAS</button>', unsafe_allow_html=True)
else:
    st.error("Planilha não carregada. Verifique o link.")
