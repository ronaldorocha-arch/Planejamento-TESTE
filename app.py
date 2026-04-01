import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO INICIAL
st.set_page_config(page_title="Planejamento NHS - Produção", page_icon="🏭", layout="wide")

# --- AJUSTE ESTES DOIS CAMPOS ---
ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
GID_DA_ABA = "0"  # Clique na aba e veja o número no final da URL (gid=...)
# -------------------------------

URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid={GID_DA_ABA}"

# --- REGRAS DE HORÁRIOS ---
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
        # Download robusto com headers para evitar bloqueio do Google
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(URL_BASE, headers=headers, timeout=10)
        
        if response.status_code != 200:
            st.error(f"Erro de conexão com Google: Status {response.status_code}")
            return pd.DataFrame()

        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        # BUSCA DINÂMICA: Localiza a palavra "MODELO" em qualquer lugar
        m_row, m_col = -1, -1
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                if "MODELO" in str(df_raw.iloc[r, c]).upper():
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
            
        if m_row == -1:
            st.warning("⚠️ Cabeçalho 'MODELO' não encontrado. Verifique a aba correta.")
            with st.expander("Ver dados lidos (Diagnóstico)"):
                st.dataframe(df_raw.head(10))
            return pd.DataFrame()

        # Extração de dados baseada na posição do cabeçalho encontrado
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, celula_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, m_col]).strip()
            cadencia = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            desc = str(dados.iloc[i, m_col+2]).strip()
            
            # Tenta localizar a UPS (pode estar na coluna +3 ou +5 dependendo da planilha)
            for offset in range(3, 7):
                if m_col+offset < len(dados.columns):
                    val_col = str(dados.iloc[i, m_col+offset]).strip().upper()
                    if any(x in val_col for x in ["UPS", "ACS", "ACE"]):
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
        st.error(f"Falha ao carregar base: {e}")
        return pd.DataFrame()

def gerar_grade(h_ini, regras):
    def para_min(s):
        h, m = map(int, s.split(':'))
        return h * 60 + m
    
    m_ini = para_min(h_ini)
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_m, m_cafe_t = para_min(regras['cafe_m']), para_min(regras['cafe_t'])
    
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini] + [m for m in marcos if para_min(m) > m_ini]
    
    grade = []
    for i in range(len(pontos)-1):
        p1, p2 = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p1 == m_alm_i and p2 == m_alm_f)
        min_uteis = 0
        if not is_alm:
            for m in range(p1, p2):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (m_alm_i <= m < m_alm_f)):
                    min_uteis += 1
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_uteis, 'Label': "🍱 ALMOÇO" if is_alm else None})
    return pd.DataFrame(grade)

def calcular_plano(df_ed, df_ba, h_ini, n_dia, regra):
    slots = gerar_grade(h_ini, regra)
    df_ed = df_ed.merge(df_ba[['DISPLAY', 'ID', 'CADENCIA', 'UPS']], left_on='Modelo', right_on='DISPLAY', how='left')
    
    # Cadência ajustada pela lotação
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
        p_hora, m_nomes = 0, []
        
        while idx < len(df_ed):
            t_pc = df_ed.loc[idx, 'T_PC']
            if acum >= (t_pc - 0.0001):
                q = min(math.floor(acum / t_pc + 0.0001), df_ed.loc[idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_pc)
                    df_ed.loc[idx, 'FALTA'] -= q
                    tot += q
                    p_hora += q
                    m_nomes.append(f"{df_ed.loc[idx, 'ID']} ({int(q)})")
                if df_ed.loc[idx, 'FALTA'] <= 0: idx += 1
                else: break
            else: break
            
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(m_nomes) if m_nomes else "-", 'Peças': int(p_hora), 'Acum': int(tot)})
        
        if tot >= total_ped and termino == "Não finalizado" and total_ped > 0:
            m_sobra = s['Minutos'] - acum
            h_h, m_m = s['Horário'].split(' – ')[0].split(':')
            dt = datetime.strptime(f"{h_h}:{m_m}", "%H:%M") + timedelta(minutes=int(m_sobra))
            termino = dt.strftime("%H:%M")
            
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
base = carregar_base()

if not base.empty:
    st.sidebar.title("⚙️ Configurações")
    lista_ups = sorted(base['UPS'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
    regra_at = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
    
    h_ini = st.sidebar.text_input("Hora de Início", "07:45")
    n_dia = st.sidebar.number_input("Pessoas na Linha", value=regra_at['n_nat'], min_value=1)
    
    st.header(f"🏭 Planejamento de Produção: {sel_ups}")
    
    opcoes = sorted(base[base['UPS'] == sel_ups]['DISPLAY'].tolist())
    
    df_input = st.data_editor(
        pd.DataFrame(columns=["Modelo", "Qtd"]), 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "Modelo": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True),
            "Qtd": st.column_config.NumberColumn("Quantidade", min_value=1)
        },
        key=f"editor_{sel_ups}"
    )

    if st.button("🚀 Gerar Cronograma"):
        df_valid = df_input.dropna(subset=['Modelo'])
        if not df_valid.empty:
            r = calcular_plano(df_valid, base, h_ini, n_dia, regra_at)
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
            c2.metric("Término Estimado", r['termino'])
            c3.metric("Lotação", f"{n_dia} pessoas")
            
            st.table(r['df'])
        else:
            st.warning("Adicione modelos na tabela acima.")
else:
    st.error("⚠️ Erro Crítico: A base de dados não pôde ser carregada.")
