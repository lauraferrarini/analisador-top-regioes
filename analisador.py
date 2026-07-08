import requests
from bs4 import BeautifulSoup
import json
import os
import glob
import sys
import traceback
import time
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

# Configurações Gerais
PASTA_DADOS = "historico_dados"
PASTA_RELATORIOS = "historico_relatorios"
MARGEM_OSCILACAO = 2 
FUSO_BR = ZoneInfo("America/Sao_Paulo")

# Mapeamento de Regiões, URLs e seus respectivos Cookies de controle
REGIOES = {
    "br": {"nome": "Brasil", "url": "https://www.letras.mus.br/mais-acessadas/", "cookies": {}},
    "ar": {"nome": "Argentina", "url": "https://www.letras.com/mais-acessadas/", "cookies": {"content": "ar"}},
    "co": {"nome": "Colômbia", "url": "https://www.letras.com/mais-acessadas/", "cookies": {"content": "co"}},
    "sp": {"nome": "Espanha", "url": "https://www.letras.com/mais-acessadas/", "cookies": {"content": "sp"}},
    "es": {"nome": "Hispanoamérica", "url": "https://www.letras.com/mais-acessadas/", "cookies": {"content": "es"}},
    "mx": {"nome": "México", "url": "https://www.letras.com/mais-acessadas/", "cookies": {"content": "mx"}}
}

def extrair_musicas(url, cookies):
    session = requests.Session()
    
    # 🕵️‍♂️ IP FALSO LATINO: Simulamos um IP residencial do México/Colômbia (186.154.201.42)
    # Isso engana os balanceadores de carga e proxies do Letras, fazendo-os ignorar o cache de servidor dos EUA.
    ip_latam = "186.154.201.42"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1', # Mudado para Mobile para abrir outra rota de cache
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-419,es;q=0.9',
        # 🔥 Headers de Spoofing de IP para burlar o bloqueio geográfico de Data Center do GitHub
        'X-Forwarded-For': ip_latam,
        'X-Real-IP': ip_latam,
        'Client-IP': ip_latam,
        'X-Cluster-Client-IP': ip_latam,
        'X-Target-URI': 'https://www.letras.com',
        'Connection': 'keep-alive'
    }
    
    session.headers.update(headers)
    
    # Cookies humanos + região
    cookies_humanos = {
        '_ga': 'GA1.1.555555555.1710000000',
        '_gid': 'GA1.1.666666666.1710000000',
        'letras_edition': 'es' if cookies and cookies.get('content') == 'es' else 'br'
    }
    
    if cookies:
        cookies_humanos.update(cookies)
        
    session.cookies.update(cookies_humanos)
    
    url_limpa = url.rstrip('/')
    # Cache buster agressivo gerando um parâmetro randômico novo
    url_com_cb = f"{url_limpa}/?update={int(time.time())}"
    
    response = session.get(url_com_cb, timeout=15)
    response.raise_for_status()
    
    if response.url != url_com_cb:
        print(f"🔗 [Aviso] Redirecionamento detectado: {url_com_cb} -> {response.url}")
        
    soup = BeautifulSoup(response.text, 'html.parser')
    musicas_atuais = {}
    lista_top = soup.find('ol', class_='top-list_mus')
    
    if not lista_top:
        return musicas_atuais
        
    itens = lista_top.find_all('li')
    for rank, item in enumerate(itens, start=1):
        tag_nome = item.find('b')
        tag_artista = item.find('span')
        tag_a = item.find('a')
        
        nome = tag_nome.text.strip() if tag_nome else "Desconhecido"
        artista = tag_artista.text.strip() if tag_artista else "Desconhecido"
        
        href = tag_a['href'] if tag_a and tag_a.has_attr('href') else ""
        link_absolute = urljoin(url, href) if href else ""
        
        chave = f"{nome} - {artista}"
        musicas_atuais[chave] = {
            "posicao": rank,
            "nome": nome,
            "artista": artista,
            "url": link_absolute
        }
            
    return musicas_atuais

def buscar_dados_anteriores(regiao):
    data_hoje_iso = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
    pasta_regiao = os.path.join(PASTA_DADOS, regiao)
    
    if os.path.exists(pasta_regiao):
        arquivos = sorted([
            f for f in os.listdir(pasta_regiao) 
            if f.endswith('.json') and f != f"dados_{data_hoje_iso}.json"
        ])
        if arquivos:
            ultimo_arquivo = os.path.join(pasta_regiao, arquivos[-1])
            with open(ultimo_arquivo, 'r', encoding='utf-8') as f:
                return json.load(f)
    return {}

def atualizar_dados_dashboard(regiao):
    pasta_regiao = os.path.join(PASTA_DADOS, regiao)
    arquivos = sorted(glob.glob(os.path.join(pasta_regiao, "dados_*.json")))
    historico_global = {}
    todas_datas = []
    
    for arq in arquivos:
        nome_base = os.path.basename(arq)
        data_str = nome_base.replace("dados_", "").replace(".json", "")
        todas_datas.append(data_str)
        
        with open(arq, 'r', encoding='utf-8') as f:
            dados_dia = json.load(f)
            
        for chave, info in dados_dia.items():
            if chave not in historico_global:
                historico_global[chave] = {}
            if "url" in info and "url" not in historico_global[chave]:
                historico_global[chave]["url"] = info["url"]
            historico_global[chave][data_str] = info["posicao"]
            
    dados_finais = {
        "datas": todas_datas,
        "musicas": historico_global
    }
    
    with open(f"dados_dashboard_{regiao}.json", "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=4)

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
    
    data_hoje_iso = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
    data_hoje_br = datetime.now(FUSO_BR).strftime("%d/%m/%Y")

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
            if i > 10: break
            conteudo_md += f"{i}º. **{m['nome']}** — *{m['artista']}*\n"
    else:
        for chave, dados_atuais in atuais.items():
            pos_atual = dados_atuais['posicao']
            
            if chave not in anteriores:
                novas_entradas.append(dados_atuais)
            else:
                pos_anterior = anteriores[chave]['posicao']
                diferenca = pos_anterior - pos_atual 
                
                dados_item = {
                    "dados": dados_atuais,
                    "pos_anterior": pos_anterior,
                    "pos_atual": pos_atual,
                    "posicoes_ganhas": diferenca
                }

                if diferenca > 400:
                    subidas_absurdas.append(dados_item)
                elif diferenca > 200:
                    grandes_saltos.append(dados_item)
                elif diferenca >= 100:
                    subidas_moderadas.append(dados_item)
                elif diferenca > MARGEM_OSCILACAO:
                    pequenas_subidas.append(dados_item)

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
        json.dump(atuais, f, ensure_ascii=False, indent=4)
        
    return True

if __name__ == "__main__":
    try:
        sucesso_geral = True
        for regiao, config in REGIOES.items():
            try:
                if processar_regiao(regiao, config):
                    atualizar_dados_dashboard(regiao)
                    print(f"✅ Região {regiao.upper()} processada com sucesso.\n")
                else:
                    sucesso_geral = False
            except Exception as e:
                print(f"\n💥 Erro ao processar a região {regiao.upper()}:")
                traceback.print_exc()
                sucesso_geral = False
        
        if sucesso_geral:
            print("🚀 Módulo executado com sucesso total para todas as regiões!")
        else:
            print("⚠️ Execução concluída com falhas parciais em algumas regiões.")
            sys.exit(1)
            
    except Exception as e:
        print("\n💥 --- ERRO CRÍTICO INESPERADO NO SCRIPT --- 💥")
        traceback.print_exc()
        sys.exit(1)
