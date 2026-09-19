"""
Script avulso (NÃO faz parte do analisador.py) só pra re-coletar o México
manualmente, sem depender do workflow automático. Rode isso DENTRO da pasta
do repositório clonado (onde ficam historico_dados/, historico_relatorios/,
etc.) — ele usa a mesma lógica do analisador.py, só que restrita à região mx.

Como rodar (no terminal do VS Code, dentro da pasta do repo):
    pip install requests beautifulsoup4
    python puxar_mexico_manual.py

Ao final ele deixa prontos, exatamente como o robô deixaria:
  - historico_dados/mx/dados_<hoje>.json
  - historico_relatorios/mx/relatorio_<hoje>.md
  - relatorio_diario_mx.md
  - dados_dashboard_mx.json

Depois é só conferir e subir (git add / commit / push) como de costume.
"""
import requests
from bs4 import BeautifulSoup
import json
import os
import glob
from datetime import datetime
from urllib.parse import urljoin, urlparse

PASTA_DADOS = "historico_dados"
PASTA_RELATORIOS = "historico_relatorios"
MARGEM_OSCILACAO = 2

REGIAO = "mx"
CONFIG = {
    "nome": "México",
    "url": "https://www.letras.com/mais-acessadas/",
    "cookies": {"content": "mx"},
}


def extrair_musicas(url, cookies):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    response = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    musicas_atuais = {}
    lista_top = soup.find('ol', class_='top-list_mus')

    if not lista_top:
        trecho = response.text.strip().replace("\n", " ")[:300]
        print(f"   ↳ Nada encontrado. Início da resposta recebida: {trecho!r}")
        return musicas_atuais

    itens = lista_top.find_all('li')
    for rank, item in enumerate(itens, start=1):
        tag_nome = item.find('b')
        tag_artista = item.find('span')
        tag_a = item.find('a') or (tag_nome.find_parent('a') if tag_nome else None)

        nome = tag_nome.text.strip() if tag_nome else "Desconhecido"
        artista = tag_artista.text.strip() if tag_artista else "Desconhecido"

        href = tag_a['href'] if tag_a and tag_a.has_attr('href') else ""
        link_absoluto = urljoin(url, href) if href else ""
        caminho = urlparse(link_absoluto).path if link_absoluto else ""
        chave = caminho if caminho else f"{nome} - {artista}"

        musicas_atuais[chave] = {
            "posicao": rank,
            "nome": nome,
            "artista": artista,
            "url": link_absoluto,
        }

    print(f"   ↳ {len(musicas_atuais)} músicas capturadas.")
    return musicas_atuais


def buscar_dados_anteriores(regiao):
    data_hoje_iso = datetime.now().strftime("%Y-%m-%d")
    pasta_regiao = os.path.join(PASTA_DADOS, regiao)

    if os.path.exists(pasta_regiao):
        arquivos = sorted([
            f for f in os.listdir(pasta_regiao)
            if f.endswith('.json') and f != f"dados_{data_hoje_iso}.json"
        ])
        if arquivos:
            ultimo_arquivo = os.path.join(pasta_regiao, arquivos[-1])
            print(f"   ↳ Comparando com o último arquivo encontrado: {ultimo_arquivo}")
            with open(ultimo_arquivo, 'r', encoding='utf-8') as f:
                return json.load(f)
    return {}


def _texto_identidade(info):
    return (
        (info.get("nome") or "").strip().casefold(),
        (info.get("artista") or "").strip().casefold(),
    )


def _caminho_identidade(info):
    url = info.get("url") or ""
    return urlparse(url).path if url else ""


def atualizar_dados_dashboard(regiao):
    pasta_regiao = os.path.join(PASTA_DADOS, regiao)
    arquivos = sorted(glob.glob(os.path.join(pasta_regiao, "dados_*.json")))
    historico_global = {}
    todas_datas = []

    caminho_para_bucket = {}
    texto_para_bucket = {}

    for arq in arquivos:
        nome_base = os.path.basename(arq)
        data_str = nome_base.replace("dados_", "").replace(".json", "")
        todas_datas.append(data_str)

        with open(arq, 'r', encoding='utf-8') as f:
            dados_dia = json.load(f)

        for chave, info in dados_dia.items():
            caminho_info = _caminho_identidade(info)
            texto_info = _texto_identidade(info)

            if caminho_info and caminho_info in caminho_para_bucket:
                bucket = caminho_para_bucket[caminho_info]
            elif texto_info in texto_para_bucket:
                bucket = texto_para_bucket[texto_info]
            else:
                bucket = caminho_info or chave

            if caminho_info:
                caminho_para_bucket[caminho_info] = bucket
            texto_para_bucket[texto_info] = bucket

            if bucket not in historico_global:
                historico_global[bucket] = {}

            if info.get("url"):
                historico_global[bucket]["url"] = info["url"]
            if info.get("nome"):
                historico_global[bucket]["nome"] = info["nome"]
            if info.get("artista"):
                historico_global[bucket]["artista"] = info["artista"]

            historico_global[bucket][data_str] = info["posicao"]

    dados_finais = {"datas": todas_datas, "musicas": historico_global}

    with open(f"dados_dashboard_{regiao}.json", "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, separators=(",", ":"))

    print(f"   ↳ dados_dashboard_{regiao}.json reconstruído ({len(todas_datas)} dias).")


def processar_regiao(regiao, config):
    print(f"🌍 Coletando dados da região: {config['nome']} ({regiao})...")

    pasta_dados_regiao = os.path.join(PASTA_DADOS, regiao)
    pasta_relatorios_regiao = os.path.join(PASTA_RELATORIOS, regiao)
    os.makedirs(pasta_dados_regiao, exist_ok=True)
    os.makedirs(pasta_relatorios_regiao, exist_ok=True)

    atuais = extrair_musicas(config['url'], config['cookies'])
    if not atuais:
        print(f"⚠️ Alerta: Nenhuma música coletada para {config['nome']}. Estrutura mudou ou bloqueio.")
        return False

    anteriores = buscar_dados_anteriores(regiao)

    data_hoje_iso = datetime.now().strftime("%Y-%m-%d")
    data_hoje_br = datetime.now().strftime("%d/%m/%Y")

    novas_entradas = []
    subidas_absurdas = []
    grandes_saltos = []
    subidas_moderadas = []
    pequenas_subidas = []

    if not anteriores:
        conteudo_md = f"# 📊 Relatório Letras - {config['nome']} - {data_hoje_br}\n\n"
        conteudo_md += f"ℹ️ **Base de dados de {config['nome']} estruturada com sucesso hoje!**\n"
        conteudo_md += "As movimentações e gráficos interativos começarão a rodar a partir do próximo ciclo de coleta.\n\n"
        conteudo_md += "### 📋 Prévia do Top 10 Atual:\n"
        for i, (chave, m) in enumerate(atuais.items(), start=1):
            if i > 10:
                break
            conteudo_md += f"{i}º. **{m['nome']}** — *{m['artista']}*\n"
    else:
        anteriores_por_caminho = {}
        for info in anteriores.values():
            caminho = _caminho_identidade(info)
            if caminho:
                anteriores_por_caminho.setdefault(caminho, info)
        anteriores_por_texto = {}
        for info in anteriores.values():
            texto = _texto_identidade(info)
            anteriores_por_texto.setdefault(texto, info)

        total_com_mudanca = 0

        for chave, dados_atuais in atuais.items():
            pos_atual = dados_atuais['posicao']
            caminho_atual = _caminho_identidade(dados_atuais)
            texto_atual = _texto_identidade(dados_atuais)

            if chave in anteriores:
                info_anterior = anteriores[chave]
            elif caminho_atual and caminho_atual in anteriores_por_caminho:
                info_anterior = anteriores_por_caminho[caminho_atual]
            elif texto_atual in anteriores_por_texto:
                info_anterior = anteriores_por_texto[texto_atual]
            else:
                info_anterior = None

            if info_anterior is None:
                novas_entradas.append(dados_atuais)
            else:
                pos_anterior = info_anterior['posicao']
                diferenca = pos_anterior - pos_atual

                if diferenca != 0:
                    total_com_mudanca += 1

                dados_item = {
                    "dados": dados_atuais,
                    "pos_anterior": pos_anterior,
                    "pos_atual": pos_atual,
                    "posicoes_ganhas": diferenca,
                }

                if diferenca > 400:
                    subidas_absurdas.append(dados_item)
                elif diferenca > 200:
                    grandes_saltos.append(dados_item)
                elif diferenca >= 100:
                    subidas_moderadas.append(dados_item)
                elif diferenca > MARGEM_OSCILACAO:
                    pequenas_subidas.append(dados_item)

        # ⚡ Aviso (não bloqueia): mostra se o dado de hoje veio suspeito de
        # cache/bloqueio (poucas mudanças no total). Não veta o salvamento
        # aqui de propósito — a decisão final de subir ou não é sua, olhando
        # esse aviso.
        mudanca_total = total_com_mudanca + len(novas_entradas)
        if mudanca_total <= 1:
            print(
                f"⚠️ ATENÇÃO: só {mudanca_total} mudança(s) no total em relação ao dia anterior "
                f"({total_com_mudanca} música(s) mudou/mudaram de posição, {len(novas_entradas)} "
                f"entrada(s) nova(s)). Isso é sintoma do mesmo problema de cache/bloqueio de antes — "
                f"os arquivos abaixo foram gerados mesmo assim, mas CONFIRA antes de subir."
            )

        subidas_absurdas.sort(key=lambda x: x['posicoes_ganhas'], reverse=True)
        grandes_saltos.sort(key=lambda x: x['posicoes_ganhas'], reverse=True)
        subidas_moderadas.sort(key=lambda x: x['posicoes_ganhas'], reverse=True)
        pequenas_subidas.sort(key=lambda x: x['posicoes_ganhas'], reverse=True)

        conteudo_md = f"# 📊 Relatório Letras - {config['nome']} - {data_hoje_br}\n\n"

        if subidas_absurdas:
            conteudo_md += "## 🚨 🚨 EXPLOSÃO NO TOP: SUBIDAS ABSURDAS (+400 posições) 🚨 🚨\n"
            for m in subidas_absurdas:
                conteudo_md += f"> ### 💥 **{m['dados']['nome']}** — *{m['dados']['artista']}*\n"
                conteudo_md += f"> 🛑 **Subida histórica!** Saltou de {m['pos_anterior']}º direto para **{m['pos_atual']}º** (🔼 **+{m['posicoes_ganhas']}** posições)\n\n"

        conteudo_md += "## 🔥 Grandes Saltos (+200 a 400 posições)\n"
        if grandes_saltos:
            for m in grandes_saltos:
                conteudo_md += f"- **{m['dados']['nome']}** ({m['dados']['artista']}): Subiu de {m['pos_anterior']}º para **{m['pos_atual']}º** (🔥 +{m['posicoes_ganhas']} posições)\n"
        else:
            conteudo_md += "- Nenhuma música com grande salto nesta faixa hoje.\n"

        conteudo_md += "\n## 📈 Subidas Significativas (100 a 200 posições)\n"
        if subidas_moderadas:
            for m in subidas_moderadas:
                conteudo_md += f"- **{m['dados']['nome']}** ({m['dados']['artista']}): Subiu de {m['pos_anterior']}º para **{m['pos_atual']}º** (📈 +{m['posicoes_ganhas']} posições)\n"
        else:
            conteudo_md += "- Nenhuma subida nesta faixa hoje.\n"

        conteudo_md += f"\n## 🌱 Pequenas Subidas (Abaixo de 100 posições)\n"
        conteudo_md += f"> Omitindo oscilações menores ou iguais a {MARGEM_OSCILACAO} posições.\n\n"
        if pequenas_subidas:
            for m in pequenas_subidas:
                conteudo_md += f"- **{m['dados']['nome']}** ({m['dados']['artista']}): {m['pos_anterior']}º → **{m['pos_atual']}º** (+{m['posicoes_ganhas']})\n"
        else:
            conteudo_md += "- Sem oscilações relevantes para cima hoje.\n"

        conteudo_md += "\n## 🚀 Novas Entradas no Top\n"
        if novas_entradas:
            for m in novas_entradas:
                conteudo_md += f"- **{m['nome']}** ({m['artista']}) - Apareceu direto na posição **{m['posicao']}º**\n"
        else:
            conteudo_md += "- Nenhuma música inédita detectada hoje.\n"

    with open(os.path.join(pasta_relatorios_regiao, f"relatorio_{data_hoje_iso}.md"), 'w', encoding='utf-8') as f:
        f.write(conteudo_md)

    with open(f"relatorio_diario_{regiao}.md", 'w', encoding='utf-8') as f:
        f.write(conteudo_md)

    with open(os.path.join(pasta_dados_regiao, f"dados_{data_hoje_iso}.json"), 'w', encoding='utf-8') as f:
        json.dump(atuais, f, ensure_ascii=False, separators=(",", ":"))

    return True


if __name__ == "__main__":
    if not os.path.isdir(PASTA_DADOS):
        print(f"⚠️ Não achei a pasta '{PASTA_DADOS}' aqui. Rode este script DENTRO da pasta do repositório clonado.")
        raise SystemExit(1)

    ok = processar_regiao(REGIAO, CONFIG)
    if ok:
        atualizar_dados_dashboard(REGIAO)
        print("✅ México processado. Confira os arquivos listados no topo do script antes de subir.")
    else:
        print("❌ Não deu pra coletar o México agora (bloqueio ou mudança na estrutura do site).")
