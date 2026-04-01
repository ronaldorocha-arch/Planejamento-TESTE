import streamlit as st
import pandas as pd
import math
import requests
from io import StringIO
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO
st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid=0"

# --- FUNÇÃO DE CLIMA ---
def pegar_clima():
    try:
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt&m"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            return response.text.strip().replace('+', '')
        return "Clima indisponível"
    except:
        return "Clima indisponível"

@st.cache_data(ttl=2)
def carregar_base():
    try:
        response = requests.get(URL_BASE, timeout=10)
        if response.status_code != 200: return pd.DataFrame()
        
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        
        m_row, m_col = -1, -1
        for r in range(min(50, len(df_raw))):
            for c in range(len(df_raw.columns)):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    if str(df_raw.iloc[r+2, c]).lower() != 'nan':
                        m_row, m_col = r, c
                        break
            if m_row != -1: break
            
        if m_row == -1: return pd.DataFrame()
        
        dados = df_raw.iloc[m_row+1:].copy()
        lista_final, cel_atual = [], "Indefinida"
        
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            try:
                unid = pd.to_numeric(dados.iloc[i, m_col+1].replace(',', '.'), errors='coerce')
                desc = str(dados.iloc[i, m_col+2]).strip()
                ups_linha = str(dados.iloc[i, m_col+3]).strip().upper()
                
                if any(x in ups_linha for x in ["UPS", "ACS", "ACE"]):
                    cel_atual = str(dados.iloc[i, m_col+3]).strip()

                if mod != 'nan' and len(mod) > 5 and not pd.isna(unid):
                    lista_final.append({
                        'ID': mod, 'UNIDADE_HORA': unid, 'DESCRICAO': desc,
                        'CEL_ORIGEM': cel_atual, 
                        'DISPLAY': f"[{cel_atual}] {mod} - {desc} ({unid} pç/h)"
                    })
            except: continue
        return pd.DataFrame(lista_final)
    except: return pd.DataFrame()

# --- REGRAS DE CÁLCULO ---
def calcular(df_in, df_ba, h_ini, n_dia, tem_gin):
    def para_min(s):
        h, m = map(int, s.split(':'))
        return h * 60 + m
    
    m_ini = para_min(h_ini)
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_m, m_cafe_t = para_min("09:20"), para_min("15:20")
    m_gin_i, m_gin_f = para_min("09:30"), para_min("09:40")
    
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini] + [m for m in marcos if para_min(m) > m_ini]
    
    df_in = df_in.merge(df_ba, left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = (df_in['UNIDADE_HORA'] / 5) * n_dia
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'])
    
    res, total_ped = [], df_in['FALTA'].sum()
    acum, idx, tot, termino = 0.0, 0, 0, "Não finalizado"

    for p in range(len(pontos)-1):
        p1, p2 = para_min(pontos[p]), para_min(pontos[p+1])
        is_alm = (p1 == m_alm_i and p2 == m_alm_f)
        
        min_u = 0
        if not is_alm:
            for m in range(p1, p2):
                # Descontar Café Manhã, Café Tarde, Almoço e Ginástica (se ativa)
                if not ((m_cafe_m <= m < m_cafe_m+10) or 
                        (m_cafe_t <= m < m_cafe_t+10) or 
                        (m_alm_i <= m < m_alm_f) or 
                        (tem_gin and m_gin_i <= m < m_gin_f)):
                    min_u += 1
        
        acum += min_u
        p_h, m_n = 0, []
        
        if is_alm:
            res.append({'Horário': f"{pontos[p]} – {pontos[p+1]}", 'Modelos': "🍱 ALMOÇO", 'Peças': 0, 'Acum': int(tot)})
            continue

        while idx < len(df_in):
            t_pc = df_in.loc[idx, 'T_PC']
            if acum >= (t_pc - 0.001):
                q = min(math.floor(acum / t_pc + 0.001), df_ed.loc[idx, 'FALTA'] if 'FALTA' in df_ed else df_in.loc[idx, 'FALTA'])
                q = min(q, df_in.loc[idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_pc)
                    df_in.loc[idx, 'FALTA'] -= q
                    tot += q; p_h += q
                    m_n.append(f"{df_in.loc[idx, 'ID']} ({int(q)})")
                if df_in.loc[idx, 'FALTA'] <= 0: idx += 1
                else: break
            else: break
            
        res.append({'Horário': f"{pontos[p]} – {pontos[p+1]}", 'Modelos': " + ".join(m_n) if m_n else "-", 'Peças': int(p_h), 'Acum': int(tot)})
        
        if tot >= total_ped and termino == "Não finalizado" and total_ped > 0:
            sobra_min = min_u - acum
            dt = datetime.strptime(pontos[p], "%H:%M") + timedelta(minutes=int(sobra_min))
            termino = dt.strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
base = carregar_base()

if not base.empty:
    st.sidebar.title("🏭 NHS Produção")
    lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
    sel_ups = st.sidebar.selectbox("Célula de Trabalho", lista_ups)
    
    # NOVAS OPÇÕES SOLICITADAS
    liberar_modelos = st.sidebar.checkbox("🔓 Usar modelos de outras UPS?", value=False)
    tem_gin = st.sidebar.checkbox("🤸 Teve Ginástica Laboral?", value=False)
    
    h_ini = st.sidebar.text_input("Início da Produção", "07:45")
    n_dia = st.sidebar.number_input(f"Pessoas na {sel_ups}", 1, 20, 5)

    col_tit, col_clim = st.columns([0.6, 0.4])
    with col_tit: st.header(f"📋 Planejamento: {sel_ups}")
    with col_clim: st.markdown(f"<div style='font-size: 20px; padding-top: 10px; text-align: right;'>📍 Curitiba: <b>{pegar_clima()}</b></div>", unsafe_allow_html=True)
    
    # Filtro de modelos baseado na chave do menu lateral
    if liberar_modelos:
        opcoes = sorted(base['DISPLAY'].tolist())
    else:
        opcoes = sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())
        
    df_ed = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                           column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes),
                                         "Qtd": st.column_config.NumberColumn("Qtd", min_value=1)})

    if st.button("🚀 Gerar Planejamento"):
        df_v = df_ed.dropna(subset=['Equipamento'])
        if not df_v.empty:
            r = calcular(df_v, base, h_ini, n_dia, tem_gin)
            st.divider()
            c1, c2 = st.columns(2)
            c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
            c2.metric("Término Estimado", r['termino'])
            
            # Formatação para colorir o almoço
            def colorir_almoco(val):
                color = '#fff3cd' if 'ALMOÇO' in str(val) else ''
                return f'background-color: {color}'

            st.dataframe(
                r['df'].style.applymap(colorir_almoco, subset=['Modelos']),
                use_container_width=True,
                height=400
            )
else:
    st.error("⚠️ Base de dados não carregada. Verifique se a aba 'BASE' é a primeira da planilha.")
