import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="🧪 LAB MULTI - Planejador NHS", page_icon="🧪", layout="wide")

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
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 2},
}

@st.cache_data(ttl=5)
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        m_row = -1
        for r in range(min(300, len(df_raw))):
            val = str(df_raw.iloc[r, 6]).strip().upper()
            if val == "MODELO":
                m_row = r
                break
        if m_row == -1: return pd.DataFrame()
        dados = df_raw.iloc[m_row+1:m_row+3000].copy()
        lista_final = []
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, 6]).strip()
            unidade = pd.to_numeric(dados.iloc[i, 7], errors='coerce')
            descricao = str(dados.iloc[i, 8]).strip()
            celula = str(dados.iloc[i, 9]).strip()
            if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade, 'DESCRICAO': descricao,
                    'CELULA': celula, 'DISPLAY': f"[{celula}] {modelo} - {descricao}"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro na leitura: {e}"); return pd.DataFrame()

def gerar_grade_fixa(h_ini_input, regras, tem_gin):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m

    m_cafe_m = para_min(regras['cafe_m'])
    m_alm_ini = para_min("11:30")
    m_alm_fim = para_min("12:30")
    m_cafe_t = para_min(regras['cafe_t'])
    m_gin = para_min("09:30")

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
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': m_uteis, 'Label': "🍱 ALMOÇO" if is_almoco else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin, regras):
    slots = gerar_grade_fixa(h_ini, regras, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['T_PC'] = 60 / (df_in['UNIDADE_HORA'] * fat)
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    res, acum, c_idx, tot = [], 0.0, 0, 0
    total_desejado = df_in['FALTA'].sum()
    termino = "Não finalizado"
    
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acumulada': tot})
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
                    mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)})")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(mods) if mods else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        if tot >= total_desejado and termino == "Não finalizado" and total_desejado > 0:
            m_usados = s['Minutos'] - acum
            h_s, m_s = s['Horário'].split(' – ')[0].split(':')
            termino = (datetime.strptime(f"{h_s}:{m_s}", "%H:%M") + timedelta(minutes=m_usados)).strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("🧪 Laboratório Multi-Células")
        lista_ups = sorted(REGRAS_HORARIOS.keys())
        selecionadas = st.sidebar.multiselect("Selecione as UPS para planejar", lista_ups, default=[lista_ups[0]])
        liberar = st.sidebar.checkbox("🔓 Liberar modelos de todas as UPS?", value=False)
        h_ini = st.sidebar.text_input("Horário Início", value="07:45")
        tem_gin = st.sidebar.checkbox("Ginástica Laboral?", value=False)
        
        dados_entrada = {}
        for ups in selecionadas:
            st.subheader(f"⚙️ Entrada de Dados: {ups}")
            regra = REGRAS_HORARIOS[ups]
            opcoes = sorted(base['DISPLAY'].tolist()) if liberar else sorted(base[base['CELULA'] == ups]['DISPLAY'].tolist())
            
            c1, c2 = st.columns(2)
            n_nat = c1.number_input(f"N Natural ({ups})", value=regra['n_nat'], key=f"nat_{ups}")
            n_dia = c2.number_input(f"N do Dia ({ups})", value=regra['n_nat'], key=f"dia_{ups}")
            
            editor = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
                column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True), 
                               "Qtd": st.column_config.NumberColumn("Qtd", min_value=0)}, key=f"ed_{ups}")
            dados_entrada[ups] = {"df": editor, "fator": n_dia/n_nat, "regra": regra}

        if st.button("🚀 GERAR TODOS OS PLANEJAMENTOS"):
            for ups, info in dados_entrada.items():
                if not info['df'].empty:
                    r = calcular(info['df'], base, h_ini, info['fator'], tem_gin, info['regra'])
                    st.write(f"---")
                    st.header(f"📊 Quadro de Produção: {ups}")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Peças Totais", int(r['tot']))
                    col2.metric("Término Real", r['termino'])
                    col3.metric("Eficiência", f"{info['fator']:.2%}")
                    
                    def style_alm(row):
                        return ['background-color: #fff3cd'] * len(row) if "🍱" in str(row.Modelos) else [''] * len(row)
                    st.dataframe(r['df'].style.apply(style_alm, axis=1), use_container_width=True)
                else:
                    st.warning(f"UPS {ups} está sem modelos.")
    else: st.error("Erro na Planilha.")
except Exception as e: st.error(f"Erro: {e}")
