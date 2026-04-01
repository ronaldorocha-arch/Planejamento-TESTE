import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO ---
GID_CORRETO = "0" 
URL_BASE = f"https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid={GID_CORRETO}"

st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

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

@st.cache_data(ttl=5)
def carregar_base():
    try:
        response = requests.get(URL_BASE)
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        m_row, m_col = -1, -1
        for r in range(min(100, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                if str(df_raw.iloc[r, c]).strip().upper() == "MODELO":
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, cel_atual = [], "Indefinida"
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            unid = pd.to_numeric(dados.iloc[i, m_col+1], errors='coerce')
            desc = str(dados.iloc[i, m_col+2]).strip()
            
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
    except: return pd.DataFrame()

def gerar_grade_fixa(h_ini_input, regras):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    
    m_ini = para_min(h_ini_input)
    m_cafe_m = para_min(regras['cafe_m'])
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_t = para_min(regras['cafe_t'])
    
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > m_ini]
    
    grade = []
    for i in range(len(pontos)-1):
        p_i, p_f = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p_i >= m_alm_i and p_f <= m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p_i, p_f):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 ALMOÇO" if is_alm else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, n_dia, regra_at):
    slots = gerar_grade_fixa(h_ini, regra_at)
    # Merge para trazer os dados técnicos da base
    df_calc = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY', how='left')
    
    # Cálculo da Cadência Real considerando a origem de cada modelo
    def calc_cadencia(row):
        n_origem = REGRAS_HORARIOS.get(row['CEL_ORIGEM'], {"n_nat": n_dia})['n_nat']
        return (row['UNIDADE_HORA'] / n_origem) * n_dia

    df_calc['CAD_R'] = df_calc.apply(calc_cadencia, axis=1)
    df_calc['T_PC'] = 60 / df_calc['CAD_R']
    df_calc['FALTA'] = pd.to_numeric(df_calc['Qtd'], errors='coerce').fillna(0).astype(float)
    
    total_d, res, acum, c_idx, tot, termino = df_calc['FALTA'].sum(), [], 0.0, 0, 0, "Não finalizado"
    
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acumulada': int(tot)})
            continue
        
        min_disponiveis = s['Minutos']
        acum += min_disponiveis
        p_no_slot, mods_no_slot = 0, []
        
        while c_idx < len(df_calc) and acum > 0:
            t_pc = df_calc.loc[c_idx, 'T_PC']
            falta = df_calc.loc[c_idx, 'FALTA']
            
            if falta <= 0:
                c_idx += 1
                continue
            
            # Quantas peças cabem no tempo acumulado?
            possivel = math.floor(acum / t_pc + 0.000001)
            produzido = min(possivel, falta)
            
            if produzido > 0:
                acum -= (produzido * t_pc)
                df_calc.loc[c_idx, 'FALTA'] -= produzido
                tot += produzido
                p_no_slot += produzido
                mods_no_slot.append(f"{df_calc.loc[c_idx, 'ID']} ({int(produzido)})")
            
            if df_calc.loc[c_idx, 'FALTA'] <= 0:
                c_idx += 1
            else:
                break
        
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(mods_no_slot) if mods_no_slot else "-", 'Peças': int(p_no_slot), 'Acumulada': int(tot)})
        
        if tot >= total_d and termino == "Não finalizado" and total_d > 0:
            min_gastos = s['Minutos'] - acum
            h_s, m_s = s['Horário'].split(' – ')[0].split(':')
            dt_fim = datetime.strptime(f"{h_s}:{m_s}", "%H:%M") + timedelta(minutes=int(min_gastos))
            termino = dt_fim.strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
base = carregar_base()
if not base.empty:
    st.sidebar.title("📋 Planejamento NHS")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Célula de Trabalho", lista_ups)
    
    regra_at = REGRAS_HORARIOS.get(sel_ups, REGRAS_HORARIOS["UPS - 1"])
    h_ini = st.sidebar.text_input("Início", "07:45")
    n_dia = st.sidebar.number_input("Nº de Pessoas", value=regra_at['n_nat'], min_value=1)
    
    st.header(f"🏭 Planejamento: {sel_ups}")
    
    # Filtra modelos apenas da célula selecionada
    opcoes = sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())
    
    df_ed = st.data_editor(
        pd.DataFrame(columns=["Equipamento", "Qtd"]), 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True),
            "Qtd": st.column_config.NumberColumn("Quantidade", min_value=1, step=1)
        }
    )

    if st.button("🚀 Gerar Planejamento"):
        df_limpo = df_ed.dropna(subset=['Equipamento'])
        if not df_limpo.empty:
            r = calcular(df_limpo, base, h_ini, n_dia, regra_at)
            st.divider()
            c1, c2 = st.columns(2)
            c1.metric("Término Estimado", r['termino'])
            c2.metric("Total Peças", f"{int(r['tot'])} pçs")
            
            st.dataframe(
                r['df'].style.apply(lambda x: ['background-color: #f0f2f6'] * len(x) if "ALMOÇO" in str(x.Modelos) else [''] * len(x), axis=1),
                use_container_width=True
            )
        else:
            st.warning("Adicione pelo menos um modelo na tabela acima.")
else:
    st.error("⚠️ Não foi possível carregar a base de dados.")
