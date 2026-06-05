import streamlit as st
import pandas as pd
import requests
from io import StringIO

st.set_page_config(page_title="Planejamento NHS", page_icon="🏭", layout="wide")

ID_PLANILHA = "11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E"
URL_BASE = f"https://docs.google.com/spreadsheets/d/{ID_PLANILHA}/export?format=csv&gid=0"

MAPA_N_NATURAL = {
    "UPS - 1": 5,
    "UPS - 2": 3,
    "UPS - 3": 3,
    "UPS - 4": 3,
    "UPS - 6": 4,
    "UPS - 7": 4,
    "UPS - 8": 4,
    "ACS - 01": 3,
}

if 'paradas_reset_key' not in st.session_state:
    st.session_state['paradas_reset_key'] = 0

if 'resultado_planejamento' not in st.session_state:
    st.session_state['resultado_planejamento'] = None

@st.cache_data(ttl=2)
def carregar_base():
    try:
        response = requests.get(URL_BASE, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
        df_raw = pd.read_csv(StringIO(response.text), header=None).astype(str)
        m_row, m_col = -1, -1
        for r in range(min(50, len(df_raw))):
            for c in range(len(df_raw.columns)):
                celula = str(df_raw.iloc[r, c]).strip().upper()
                if celula == "MODELO":
                    if str(df_raw.iloc[r + 2, c]).lower() != "nan":
                        m_row, m_col = r, c
                        break
            if m_row != -1:
                break
        if m_row == -1:
            return pd.DataFrame()
        dados = df_raw.iloc[m_row + 1:].copy()
        lista_final = []
        cel_atual = "Indefinida"
        for i in range(len(dados)):
            mod = str(dados.iloc[i, m_col]).strip()
            try:
                unid = pd.to_numeric(dados.iloc[i, m_col + 1].replace(",", "."), errors="coerce")
                desc = str(dados.iloc[i, m_col + 2]).strip()
                ups_linha = str(dados.iloc[i, m_col + 3]).strip().upper()
                if any(x in ups_linha for x in ["UPS", "ACS", "ACE"]):
                    cel_atual = str(dados.iloc[i, m_col + 3]).strip()
                if mod != "nan" and len(mod) > 5 and not pd.isna(unid):
                    lista_final.append({
                        "ID": mod,
                        "UNIDADE_HORA": unid,
                        "DESCRICAO": desc,
                        "CEL_ORIGEM": cel_atual,
                        "DISPLAY": f"[{cel_atual}] {mod} - {desc} ({unid} pç/h)",
                    })
            except:
                continue
                
        df_final = pd.DataFrame(lista_final)
        
        # --- BLOQUEIO DE DUPLICATAS DA PLANILHA ---
        # Impede que cadastros repetidos no Google Sheets multipliquem os cálculos na tela
        if not df_final.empty:
            df_final = df_final.drop_duplicates(subset=["DISPLAY"]).reset_index(drop=True)
            
        return df_final
    except:
        return pd.DataFrame()


def calcular(df_in, df_ba, h_ini, n_dia, tem_gin, sel_ups, df_paradas):
    def para_min(s):
        try:
            s_str = str(s).strip().replace(",", ".")
            if not s_str or s_str.lower() == "nan":
                return -1
            if ":" in s_str:
                h, m = map(int, s_str.split(":"))
                return h * 60 + m
            else:
                val = int(float(s_str))
                return val * 60
        except:
            return -1

    def para_str(m_tot):
        return f"{m_tot // 60:02d}:{m_tot % 60:02d}"

    m_alm_i  = para_min("11:30")
    m_alm_f  = para_min("12:30")
    m_cafe_m = para_min("09:20")
    m_cafe_t = para_min("15:20")
    m_gin_i  = para_min("09:30")
    m_gin_f  = para_min("09:40")
    m_ini    = para_min(h_ini)

    paradas_customizadas = []
    if df_paradas is not None and not df_paradas.empty:
        for _, row in df_paradas.iterrows():
            if pd.isna(row["Início"]) or pd.isna(row["Fim"]):
                continue
            ini_p = para_min(row["Início"])
            fim_p = para_min(row["Fim"])
            motivo = str(row["Motivo"]).strip() if not pd.isna(row["Motivo"]) and str(row["Motivo"]).strip() != "" and str(row["Motivo"]).strip().lower() != "nan" else "PARADA"
            if ini_p != -1 and fim_p != -1 and fim_p > ini_p:
                paradas_customizadas.append({"ini": ini_p, "fim": fim_p, "motivo": motivo.upper()})

    marcos_fixos = ["08:30","09:30","10:30","11:30","12:30","13:30","14:30","15:30","16:30","17:30"]
    marcos_min = [para_min(x) for x in marcos_fixos if para_min(x) > m_ini]
    
    marcos_dinamicos = set(marcos_min)
    marcos_dinamicos.add(m_alm_i)
    marcos_dinamicos.add(m_alm_f)
    for pc in paradas_customizadas:
        marcos_dinamicos.add(pc["ini"])
        marcos_dinamicos.add(pc["fim"])
        
    pontos_min = sorted([x for x in marcos_dinamicos if x >= m_ini])
    if m_ini not in pontos_min:
        pontos_min = [m_ini] + pontos_min

    # Trava de sequência estrita e preservação de linhas
    df_in = df_in.reset_index(drop=True)
    df_in["ID_UNICO_PRODUCAO"] = range(len(df_in))
    df_in = df_in.merge(df_ba, left_on="Equipamento", right_on="DISPLAY", how="left")
    df_in = df_in.sort_values(by="ID_UNICO_PRODUCAO").reset_index(drop=True)

    def cad_real(row):
        n_nom = MAPA_N_NATURAL.get(row["CEL_ORIGEM"], 5)
        return (row["UNIDADE_HORA"] / n_nom) * n_dia

    df_in["CAD_R"] = df_in.apply(cad_real, axis=1)
    df_in["T_PC"]  = 60.0 / df_in["CAD_R"]
    df_in["FALTA"] = pd.to_numeric(df_in["Qtd"]).astype(float)

    total_ped = int(df_in["FALTA"].sum())

    res   = []
    acum  = 0.0   
    idx   = 0
    tot   = 0
    ultimo_min = None

    for p in range(len(pontos_min) - 1):
        p1 = pontos_min[p]
        p2 = pontos_min[p + 1]
        
        if p1 == p2:
            continue

        horario_label = f"{para_str(p1)} – {para_str(p2)}"

        if p1 >= m_alm_i and p2 <= m_alm_f:
            res.append({"Horário": horario_label, "Modelos": "🍱 INTERVALO DE ALMOÇO", "Peças": 0, "Acum": int(tot)})
            continue

        motivo_custom_ativo = None
        for pc in paradas_customizadas:
            if p1 >= pc["ini"] and p2 <= pc["fim"]:
                motivo_custom_ativo = pc["motivo"]
                break
                
        if motivo_custom_ativo:
            res.append({"Horário": horario_label, "Modelos": f"🛑 PARADA: {motivo_custom_ativo}", "Peças": 0, "Acum": int(tot)})
            continue

        mins_uteis = []
        for m in range(p1, p2):
            if not (
                (m_cafe_m <= m < m_cafe_m + 10)
                or (m_cafe_t <= m < m_cafe_t + 10)
                or (m_alm_i  <= m < m_alm_f)
                or (tem_gin and m_gin_i <= m < m_gin_f)
            ):
                mins_uteis.append(m)

        p_h = 0
        m_n = []  

        for m_util in mins_uteis:
            if idx >= len(df_in):
                break

            acum += 1.0  

            while idx < len(df_in):
                t_pc = df_in.loc[idx, "T_PC"]
                if (acum + 0.1) >= t_pc - 0.001:
                    acum -= t_pc
                    if acum < 0:
                        acum = 0.0
                    df_in.loc[idx, "FALTA"] -= 1
                    tot    += 1
                    p_h    += 1
                    ultimo_min = m_util

                    nome = df_in.loc[idx, "ID"]
                    if m_n and m_n[-1].startswith(nome + " ("):
                        qtd_ant   = int(m_n[-1].split("(")[1].rstrip(")"))
                        m_n[-1]   = f"{nome} ({qtd_ant + 1})"
                    else:
                        m_n.append(f"{nome} (1)")

                    if df_in.loc[idx, "FALTA"] <= 0:
                        idx += 1
                else:
                    break  

        res.append({
            "Horário": horario_label,
            "Modelos": " + ".join(m_n) if m_n else "-",
            "Peças":   int(p_h),
            "Acum":    int(tot),
        })

    if total_ped == 0:
        termino = "Sem demanda"
    elif tot >= total_ped and ultimo_min is not None:
        termino = para_str(ultimo_min)
    elif ultimo_min is not None:
        termino = f"{para_str(ultimo_min)} (Capacidade Máxima do Turno)"
    else:
        termino = "Não iniciado"

    return {
        "df":        pd.DataFrame(res),
        "tot":       tot,
        "total_ped": total_ped,
        "termino":   termino
    }


# ===================== INTERFACE =====================
base = carregar_base()

if not base.empty:
    st.sidebar.markdown("### Tecnologia de Processos")
    st.sidebar.title("🏭 NHS Produção")

    lista_ups = sorted(base["CEL_ORIGEM"].unique().tolist())
    default_index = lista_ups.index("UPS - 4") if "UPS - 4" in lista_ups else 0
    st.sidebar.selectbox("Célula de Trabalho", lista_ups, index=default_index, key="sel_ups_key")
    sel_ups = st.session_state["sel_ups_key"]

    n_sugerido = MAPA_N_NATURAL.get(sel_ups, 5)

    liberar_modelos = st.sidebar.checkbox("🔓 Usar modelos de outras UPS?", value=False)
    tem_gin         = st.sidebar.checkbox("🤸 Haverá Ginástica Laboral?",   value=False)
    h_ini            = st.sidebar.text_input("Início da Produção", "07:45")
    n_dia            = st.sidebar.number_input(f"Pessoas na {sel_ups}", 1, 20, value=n_sugerido)

    st.sidebar.write("---")
    st.sidebar.markdown("### 🛑 Paradas Programadas")
    
    df_paradas_vazias = pd.DataFrame(columns=["Início", "Fim", "Motivo"])
    editor_key = f"paradas_editor_{st.session_state['paradas_reset_key']}"
    
    df_p_ed = st.sidebar.data_editor(
        df_paradas_vazias,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=editor_key
    )

    if st.sidebar.button("🗑️ Limpar Paradas", use_container_width=True):
        st.session_state['paradas_reset_key'] += 1
        st.session_state['resultado_planejamento'] = None
        st.rerun()

    st.header(f"📋 Planejamento: {sel_ups}")

    if liberar_modelos:
        opcoes = sorted(base["DISPLAY"].tolist())
    else:
        opcoes = sorted(base[base["CEL_ORIGEM"] == sel_ups]["DISPLAY"].tolist())

    df_ed = st.data_editor(
        pd.DataFrame(columns=["Equipamento", "Qtd"]),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes),
            "Qtd":         st.column_config.NumberColumn("Qtd", min_value=1),
        },
        key="modelos_editor"
    )

    if st.button("🚀 Gerar Planejamento"):
        df_v = df_ed.dropna(subset=["Equipamento", "Qtd"])
        df_v = df_v[df_v["Qtd"] > 0].copy()

        df_p_validas = df_p_ed.dropna(subset=["Início", "Fim"]) if not df_p_ed.empty else None

        if not df_v.empty:
            st.session_state['resultado_planejamento'] = calcular(df_v, base, h_ini, n_dia, tem_gin, sel_ups, df_p_validas)

    if st.session_state['resultado_planejamento'] is not None:
        r = st.session_state['resultado_planejamento']
        st.divider()

        c1, c2 = st.columns(2)
        c1.metric("Total Produzido", f"{r['tot']} pçs")
        c2.metric("Horário da Última Peça", r["termino"])

        def style_almoco(row):
            celula_texto = str(row["Modelos"])
            if "ALMOÇO" in celula_texto:
                return ["background-color: #fff3cd"] * len(row)
            if "🛑" in celula_texto or "PARADA" in celula_texto:
                return ["background-color: #f8d7da; color: #721c24; font-weight: bold;"] * len(row)
            return [""] * len(row)

        st.subheader("📅 Cronograma Detalhado por Hora")
        st.dataframe(
            r["df"].style.apply(style_almoco, axis=1),
            use_container_width=True,
            height=450,
        )
else:
    st.error("⚠️ Base de dados não carregada. Verifique se a aba 'BASE' é a primeira da planilha.")
