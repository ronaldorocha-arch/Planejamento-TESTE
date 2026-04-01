import streamlit as st
import pandas as pd
import math
import requests
from datetime import datetime, timedelta

# 1. Configuração da página
st.set_page_config(page_title="Planejamento de Produção - NHS", page_icon="🏭", layout="wide")

# URL da sua planilha (Garante que pegue a aba correta e formato CSV)
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

# --- FUNÇÃO DE CLIMA (CORRIGIDA PARA CELSIUS) ---
def pegar_clima():
    try:
        # O parâmetro 'm' força o sistema métrico (Celsius)
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt&m"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text.strip().replace('+', '')
        return "Clima indisponível"
    except:
        return "Clima indisponível"

# --- CARREGAMENTO DA BASE COM DIAGNÓSTICO ---
@st.cache_data(ttl=10)
def carregar_base():
    try:
        # Tenta ler a planilha
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        
        # Procura a palavra "MODELO" em qualquer lugar (Busca exaustiva)
        m_row, m_col = -1, -1
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1:
            # Se não achar, mostra o que leu para ajudar a identificar o erro
            st.error("❌ Não encontrei a coluna 'MODELO' na planilha.")
            with st.expander("Clique para ver o diagnóstico da planilha"):
                st.write("Dados brutos lidos (primeiras 15 linhas):")
                st.dataframe(df_raw.head(15))
            return pd.DataFrame()

        # Extração de dados
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final = []
        celula_atual = "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            # Cadência fica na coluna logo após o modelo
            unidade = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            descricao = str(dados.iloc[i, m_col+2]).strip()
            # Célula (UPS) fica 3 colunas após o modelo
            cel_na_linha = str(dados.iloc[i, m_col+3]).strip().upper()
            
            if any(x in cel_na_linha for x in ["UPS", "ACS", "ACE", "LINHA"]):
                celula_atual = str(dados.iloc[i, m_col+3]).strip()
                
            if modelo != 'nan' and len(modelo) > 2 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 
                    'UNIDADE_HORA': unidade, 
                    'DESCRICAO': descricao,
                    'CEL_ORIGEM': celula_atual, 
                    'DISPLAY': f"[{celula_atual}] {modelo} - {descricao} ({int(unidade)} pç/h)"
                })
        
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return pd.DataFrame()

# --- LÓGICA DE CÁLCULO ---
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
            if pd.isna(t_p) or t_p <= 0: 
                c_idx += 1
                continue
            
            if acum >= (t_p - 0.0001):
                q = min(math.floor(acum / t_p + 0.0001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p)
                    df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q
                    p_b += q
                    mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)} pçs)")
                
                if df_in.loc[c_idx, 'FALTA'] <= 0: 
                    c_idx += 1
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
    idx_ini = lista_ups.index("UPS - 1") if "UPS - 1" in lista_ups else 0
    
    sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups, index=idx_ini)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    
    liberar = st.sidebar.checkbox("🔓 Ver modelos de todas UPS?", value=False)
    h_ini = st.sidebar.text_input("Início da Produção", value="07:45")
    tem_gin = st.sidebar.checkbox("Haverá Ginástica?", value=False)
    n_dia = st.sidebar.number_input(f"Nº Pessoas na {sel_ups}", value=regra_at['n_nat'], min_value=1)

    opcoes = sorted(base['DISPLAY'].tolist()) if liberar else sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())

    # Cabeçalho com Clima
    c1, c2, c3 = st.columns([0.45, 0.4, 0.15])
    c1.header(f"📋 Célula: {sel_ups}")
    with c2:
        st.markdown(f"<div style='font-size: 20px; padding-top: 10px;'>📍 Curitiba: <b>{pegar_clima()}</b></div>", unsafe_allow_html=True)
    if c3.button("🗑️ Limpar"):
        st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
        st.rerun()

    # Tabela de Entrada
    df_ed = st.data_editor(
        pd.DataFrame(columns=["Equipamento", "Qtd"]), 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True),
            "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)
        },
        key=f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}"
    )

    if st.button("🚀 Gerar Planejamento"):
        df_v = df_ed.dropna(subset=['Equipamento'])
        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, tem_gin, regra_at)
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Planejado", f"{int(r['tot'])} pçs")
            m2.metric("Término Estimado", r['termino'])
            m3.metric("Lotação da Linha", f"{n_dia} pessoas")
            
            st.dataframe(
                r['df'].style.apply(lambda row: ['background-color: #fff3cd; font-weight: bold'] * len(row) if "🍱" in str(row.Modelos) else [''] * len(row), axis=1),
                use_container_width=True
            )
        else:
            st.warning("Selecione pelo menos um modelo.")
