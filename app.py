import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="Tecnologia de Processos - NHS", page_icon="🏭", layout="wide")

# --- ESTILO PARA IMPRESSÃO E LAYOUT COMPACTO ---
st.markdown("""
    <style>
    /* Estilo para telas */
    .stDataEditor { width: 100% !important; }
    
    /* Estilo para Impressão */
    @media print {
        section[data-testid="stSidebar"], .stButton, footer, header, .stExpander, .stCheckbox {
            display: none !important;
        }
        .main .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
        [data-testid="column"] {
            width: 49% !important;
            flex: 0 0 49% !important;
            float: left !important;
            padding: 5px !important;
        }
        .stTable { font-size: 10px !important; }
        h3 { font-size: 14px !important; margin: 5px 0 !important; }
        p { font-size: 10px !important; margin: 0 !important; }
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
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 3},
}

@st.cache_data(ttl=5)
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        m_row = -1
        for r in range(len(df_raw)):
            if "MODELO" in str(df_raw.iloc[r, 6]).upper():
                m_row = r
                break
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final = []
        for i in range(len(dados)):
            mod = str(dados.iloc[i, 6]).strip()
            uni = pd.to_numeric(dados.iloc[i, 7], errors='coerce')
            cel = str(dados.iloc[i, 9]).strip()
            
            # Limpeza rigorosa: remove NaNs e lixo
            if mod.lower() not in ['nan', 'none', '', '0'] and len(mod) > 2 and not pd.isna(uni):
                lista_final.append({'ID': mod, 'UNIDADE_HORA': uni, 'CELULA': cel, 'DISPLAY': f"[{cel}] {mod}"})
        return pd.DataFrame(lista_final)
    except: return pd.DataFrame()

def gerar_grade(h_ini, regras, tem_gin):
    def p_m(h_s):
        h, m = map(int, h_s.split(':')); return h * 60 + m
    m_c_m, m_a_i, m_a_f, m_c_t, m_g = p_m(regras['cafe_m']), p_m("11:30"), p_m("12:30"), p_m(regras['cafe_t']), p_m("09:30")
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini] + [m for m in marcos if p_m(m) > p_m(h_ini)]
    grade = []
    for i in range(len(pontos)-1):
        pi, pf = p_m(pontos[i]), p_m(pontos[i+1])
        is_a = (pi == m_a_i and pf == m_a_f)
        mu = 0
        if not is_a:
            for m in range(pi, pf):
                if not ((m_c_m <= m < m_c_m+10) or (m_a_i <= m < m_a_f) or (m_c_t <= m < m_c_t+10) or (tem_gin and m_g <= m < m_g+10)):
                    mu += 1
        grade.append({'Horário': f"{pontos[i]}–{pontos[i+1]}", 'Minutos': mu, 'Label': "🍱 ALMOÇO" if is_a else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin, regras):
    slots = gerar_grade(h_ini, regras, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['T_PC'] = 60 / (df_in['UNIDADE_HORA'] * fat)
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    res, ac, ci, tot = [], 0.0, 0, 0
    t_des = df_in['FALTA'].sum()
    term = "---"
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Total': tot})
            continue
        ac += s['Minutos']
        pb, mods = 0, []
        while ci < len(df_in):
            tp = df_in.loc[ci, 'T_PC']
            if ac >= (tp - 0.001):
                q = min(math.floor(ac/tp + 0.001), df_in.loc[ci, 'FALTA'])
                if q > 0: ac -= (q*tp); df_in.loc[ci, 'FALTA'] -= q; tot += q; pb += q; mods.append(f"{df_in.loc[ci, 'ID']}({int(q)})")
                if df_in.loc[ci, 'FALTA'] <= 0: ci += 1
                else: break
            else: break
        res.append({'Horário': s['Horário'], 'Modelos': "+".join(mods) if mods else "-", 'Peças': int(pb), 'Total': int(tot)})
        if tot >= t_des and term == "---" and t_des > 0:
            mus = s['Minutos'] - ac
            hs, ms = s['Horário'].split('–')[0].split(':')
            term = (datetime.strptime(f"{hs}:{ms}", "%H:%M") + timedelta(minutes=mus)).strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'term': term}

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.subheader("🚀 Tecnologia de Processos")
    l_ups = sorted(REGRAS_HORARIOS.keys())
    selecionadas = st.sidebar.multiselect("Selecione as UPS", l_ups, default=["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", value="07:45")
    tem_gin = st.sidebar.checkbox("Ginástica?", value=False)
    
    # BOTÃO PARA LIBERAR PEÇAS DE OUTRAS UPS
    liberar_todas = st.sidebar.checkbox("🔓 Liberar modelos de todas as UPS?", value=False)

    if st.sidebar.button("🗑️ Limpar Tudo"):
        st.session_state["rk"] = st.session_state.get("rk", 0) + 1
        st.rerun()

    dados_e = {}
    for ups in selecionadas:
        st.write(f"### Configuração: {ups}")
        reg = REGRAS_HORARIOS[ups]
        
        # Filtro de opções para evitar NAN e peças erradas
        if liberar_todas:
            opc = sorted(base['DISPLAY'].unique().tolist())
        else:
            opc = sorted(base[base['CELULA'] == ups]['DISPLAY'].unique().tolist())

        # ENTRADAS LADO A LADO
        col_par, col_tab = st.columns([0.3, 0.7])
        with col_par:
            nn = st.number_input(f"N Nat ({ups})", value=reg['n_nat'], key=f"n_{ups}")
            nd = st.number_input(f"N Dia ({ups})", value=reg['n_nat'], key=f"d_{ups}")
        with col_tab:
            ed = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                column_config={
                    "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opc, required=True), 
                    "Qtd": st.column_config.NumberColumn("Qtd", min_value=0)
                }, key=f"e_{ups}_{st.session_state.get('rk', 0)}")
        
        dados_e[ups] = {"df": ed, "fat": nd/nn, "reg": reg}
        st.divider()

    if st.button("🚀 GERAR QUADROS"):
        # Relatório Final em Colunas Lado a Lado
        col_rel = st.columns(2)
        idx = 0
        for ups, info in dados_e.items():
            if not info['df'].empty:
                r = calcular(info['df'], base, h_ini, info['fat'], tem_gin, info['reg'])
                with col_rel[idx % 2]:
                    st.markdown(f"### QUADRO: {ups}")
                    st.write(f"**Total:** {int(r['tot'])} pçs | **Fim:** {r['term']} | **Ef:** {info['fat']:.1%}")
                    st.table(r['df'])
                idx += 1
        
        # Botão de Impressão via Script
        st.components.v1.html("""
            <script>function imprimir(){ window.print(); }</script>
            <button onclick="imprimir()" style="width:100%; height:50px; background:#4CAF50; color:white; border:none; border-radius:10px; font-weight:bold; cursor:pointer;">
                🖨️ ABRIR JANELA DE IMPRESSÃO (ECONÔMICA)
            </button>
        """, height=70)
else:
    st.error("Erro ao carregar base. Verifique a planilha.")
