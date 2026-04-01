import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÃO DE ACESSO ---
# Atualizado para a nova planilha finalizada em ...wuxnL8c
URL_BASE = "https://docs.google.com/spreadsheets/d/1wdWOqdle-VLb6sLpXm4NEa-mcBx0FdFi8KWDwuxnL8c/export?format=csv&gid=0"

st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

# --- 2. REGRAS DE CÉLULAS (N e HORÁRIOS) ---
REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco_i": "11:30", "almoco_f": "12:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco_i": "11:30", "almoco_f": "12:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco_i": "11:50", "almoco_f": "12:50", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 4": {"cafe_m": "09:20", "almoco_i": "11:45", "almoco_f": "12:45", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 6": {"cafe_m": "09:30", "almoco_i": "11:45", "almoco_f": "12:45", "cafe_t": "15:30", "n_nat": 4},
    "UPS - 7": {"cafe_m": "09:30", "almoco_i": "11:45", "almoco_f": "12:45", "cafe_t": "15:40", "n_nat": 4},
    "UPS - 8": {"cafe_m": "09:40", "almoco_i": "11:45", "almoco_f": "12:45", "cafe_t": "15:40", "n_nat": 4},
    "ACS - 01": {"cafe_m": "09:50", "almoco_i": "11:45", "almoco_f": "12:45", "cafe_t": "15:50", "n_nat": 3},
}

@st.cache_data(ttl=5)
def carregar_base():
    try:
        response = requests.get(URL_BASE, timeout=10)
        if response.status_code != 200: return pd.DataFrame()
        
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        m_row, m_col = -1, -1
        # Busca a palavra "MODELO" para encontrar o início dos dados
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                if "MODELO" in str(df_raw.iloc[r, c]).upper():
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1:
            st.sidebar.warning("⚠️ 'MODELO' não encontrado.")
            with st.expander("Ver diagnóstico da planilha"):
                st.dataframe(df_raw.head(20))
            return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final = []
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            unid = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            desc = str(dados.iloc[i, m_col+2]).strip()
            cel_origem = "Indefinida"
            
            # Procura a UPS nas colunas próximas
            for offset in range(3, 8):
                if (m_col + offset) < len(dados.columns):
                    val = str(dados.iloc[i, m_col+offset]).strip().upper()
                    if any(x in val for x in ["UPS", "ACS", "ACE"]):
                        cel_origem = str(dados.iloc[i, m_col+offset]).strip()
                        break
            
            if mod != 'nan' and len(mod) > 2 and not pd.isna(unid):
                lista_final.append({
                    'ID': mod, 
                    'UNIDADE_HORA': unid, 
                    'CEL_ORIGEM': cel_origem, 
                    'DISPLAY': f"[{cel_origem}] {mod} - {desc}"
                })
        return pd.DataFrame(lista_final)
    except: return pd.DataFrame()

def calcular_termino(df_pedidos, h_ini_str, n_pessoas, regras):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m

    # Calcula tempo total produtivo necessário
    tempo_total_minutos = 0
    for _, row in df_pedidos.iterrows():
        # Pega o N natural da célula de origem do modelo
        n_origem = REGRAS_HORARIOS.get(row['CEL_ORIGEM'], {"n_nat": n_pessoas})['n_nat']
        # Ajusta a cadência para a quantidade de pessoas atual
        cadencia_real = (row['UNIDADE_HORA'] / n_origem) * n_pessoas
        tempo_total_minutos += (row['Qtd'] / cadencia_real) * 60

    # Simulação do tempo passando
    minuto_atual = para_min(h_ini_str)
    minutos_contados = 0
    
    m_cafe_m = para_min(regras['cafe_m'])
    m_alm_i = para_min(regras['almoco_i'])
    m_alm_f = para_min(regras['almoco_f'])
    m_cafe_t = para_min(regras['cafe_t'])

    while minutos_contados < tempo_total_minutos:
        # Pula Café Manhã
        if m_cafe_m <= minuto_atual < m_cafe_m + 10:
            minuto_atual = m_cafe_m + 10
        # Pula Almoço
        elif m_alm_i <= minuto_atual < m_alm_f:
            minuto_atual = m_alm_f
        # Pula Café Tarde
        elif m_cafe_t <= minuto_atual < m_cafe_t + 10:
            minuto_atual = m_cafe_t + 10
        else:
            minuto_atual += 1
            minutos_contados += 1

    return datetime.strptime(f"{int(minuto_atual//60):02d}:{int(minuto_atual%60):02d}", "%H:%M").strftime("%H:%M")

# --- 3. INTERFACE ---
base = carregar_base()

if not base.empty:
    st.sidebar.title("📋 Planejamento NHS")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Célula", lista_ups)
    
    regra_at = REGRAS_HORARIOS.get(sel_ups, REGRAS_HORARIOS["UPS - 1"])
    h_ini = st.sidebar.text_input("Início da Produção", "07:45")
    n_dia = st.sidebar.number_input("Nº de Pessoas hoje", value=regra_at['n_nat'], min_value=1)
    
    st.header(f"🏭 Cálculo de Produção: {sel_ups}")
    opcoes = sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())
    
    df_ed = st.data_editor(
        pd.DataFrame(columns=["Equipamento", "Qtd"]), 
        num_rows="dynamic", use_container_width=True,
        column_config={
            "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True),
            "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)
        }
    )

    if st.button("🚀 Calcular Horário de Término"):
        df_limpo = df_ed.dropna(subset=['Equipamento'])
        if not df_limpo.empty:
            # Merge com a base para pegar os dados de Unidade/Hora e Célula de Origem
            df_final = df_limpo.merge(base[['DISPLAY', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY')
            
            horario_fim = calcular_termino(df_final, h_ini, n_dia, regra_at)
            total_pecas = df_final['Qtd'].sum()
            
            st.divider()
            col1, col2 = st.columns(2)
            col1.metric("⏰ Término Estimado", horario_fim)
            col2.metric("📦 Total de Peças", f"{int(total_pecas)} pçs")
            
            st.success(f"Cálculo concluído para {sel_ups}. Término previsto às {horario_fim}.")
        else:
            st.warning("Adicione modelos na tabela acima.")
else:
    st.error("⚠️ Não foi possível carregar a base. Verifique se a planilha está 'Publicada na Web'.")
