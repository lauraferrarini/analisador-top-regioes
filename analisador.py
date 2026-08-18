import requests
import json
import os
import glob
import sys
import traceback
from datetime import datetime
from urllib.parse import urljoin, urlparse

# Configurações Gerais
PASTA_DADOS = "historico_dados"
PASTA_RELATORIOS = "historico_relatorios"
MARGEM_OSCILACAO = 2

# Endpoint oficial da API que alimenta o "mais acessadas" — usado no lugar do
# scraping de HTML (que quebrava toda vez que a estrutura da página mudava).
# A região é escolhida pelo header X-Region-SID, não pela URL/cookie como
# antes; os valores abaixo foram confirmados manualmente via navegador
# (ModHeader), batendo 1000 músicas em cada uma das 6 regiões.
API_URL = "https://api.letras.mus.br/v3/top/songs/?json=1"

# Mapeamento de Regiões: nome de exibição, código enviado no header
# X-Region-SID da API, e o domínio "canônico" usado para montar a URL
# absoluta de cada música (o Brasil usa letras.mus.br, as outras 5 usam
# letras.com — mas o CAMINHO da música é idêntico nos dois domínios).
REGIOES = {
    "br": {"nome": "Brasil", "api_regiao": "pt", "dominio": "https://www.letras.mus.br/"},
    "ar": {"nome": "Argentina", "api_regiao": "ar", "dominio": "https://www.letras.com/"},
    "co": {"nome": "Colômbia", "api_regiao": "co", "dominio": "https://www.letras.com/"},
    "sp": {"nome": "Espanha", "api_regiao": "sp", "dominio": "https://www.letras.com/"},
    "es": {"nome": "Hispanoamérica", "api_regiao": "es", "dominio": "https://www.letras.com/"},
    "mx": {"nome": "México", "api_regiao": "mx", "dominio": "https://www.letras.com/"}
}

def extrair_musicas(api_regiao, dominio):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'X-Region-SID': api_regiao
    }
    response = requests.get(API_URL, headers=headers, timeout=15)
    response.raise_for_status()

    dados = response.json()
    lista = dados.get('list', [])

    musicas_atuais = {}
    for rank, item in enumerate(lista, start=1):
        nome = item.get('name') or "Desconhecido"
        artista_info = item.get('artist') or {}
        artista = artista_info.get('name') or "Desconhecido"
        dns_artista = artista_info.get('dns') or ""
        slug_musica = item.get('url') or ""

        # Reconstrói o caminho relativo no MESMO formato que o scraping de
        # HTML produzia (ex.: "/radiohead/63485/"), pra manter compatível
        # tanto o histórico já salvo quanto a lógica de identidade entre
        # regiões (_caminho_identidade), sem precisar mexer em mais nada.
        caminho = f"/{dns_artista}/{slug_musica}/" if dns_artista and slug_musica else ""
        link_absoluto = urljoin(dominio, caminho.lstrip("/")) if caminho else ""

        # ⚡ ID ESTÁVEL: usa só o CAMINHO do link (sem domínio) como chave, e não
        # a URL inteira. O Brasil usa letras.mus.br e as outras 5 regiões usam
        # letras.com, mas pra mesma música o caminho é idêntico nos dois
        # domínios (ex.: /radiohead/63485/) — é a mesma numeração/slug do
        # catálogo. Usando só o caminho, uma música que aparece em várias
        # regiões cai na MESMA chave em todas elas, o que é o que permite o
        # cruzamento entre regiões (“Também aparece em”) no index.html
        # encontrar o Brasil também, sem precisar de nenhuma lógica extra lá.
        # Cai no formato antigo (Nome - Artista) só se não houver link.
        chave = caminho if caminho else f"{nome} - {artista}"
        musicas_atuais[chave] = {
            "posicao": rank,
            "nome": nome,
            "artista": artista,
            "url": link_absoluto
        }

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
            with open(ultimo_arquivo, 'r', encoding='utf-8') as f:
                return json.load(f)
    return {}

def _texto_identidade(info):
    """Par (nome, artista) normalizado — usado como identidade alternativa
    quando não há URL (ex.: captura manual colada sem o link)."""
    return (
        (info.get("nome") or "").strip().casefold(),
        (info.get("artista") or "").strip().casefold()
    )

def _caminho_identidade(info):
    """Caminho da URL (sem domínio) — extraído sempre do campo 'url', não da
    chave do dia — usado como identidade principal entre dias e regiões.
    Isso é o que faz o cruzamento entre regiões funcionar (Brasil usa
    letras.mus.br, as outras 5 usam letras.com, mas o caminho é igual pra
    mesma música) e também une o histórico de uma região quando o próprio
    site trocou de domínio no meio do caminho pra ela (aconteceu com
    ar/co/sp/es/mx por volta de 07/2026: passaram de letras.mus.br pra
    letras.com nos links, mesma música, mesmo caminho, domínio diferente)."""
    url = info.get("url") or ""
    return urlparse(url).path if url else ""

def atualizar_dados_dashboard(regiao):
    pasta_regiao = os.path.join(PASTA_DADOS, regiao)
    arquivos = sorted(glob.glob(os.path.join(pasta_regiao, "dados_*.json")))
    historico_global = {}
    todas_datas = []

    # Índices vivos, atualizados dia a dia, que ligam uma música à sua "bucket"
    # (chave definitiva dentro de historico_global) — pelo CAMINHO da URL (sem
    # domínio) e por texto (nome+artista). Usar o caminho em vez da URL
    # inteira é o que une o histórico mesmo quando o domínio muda com o tempo
    # (ex.: ar/co/sp/es/mx passaram a receber links letras.com em vez de
    # letras.mus.br a partir de certa altura) e é também o que faz essa
    # música bater com a mesma música salva no dashboard de outra região.
    # O texto (nome+artista) continua como último recurso pra capturas
    # manuais sem link (gerador_json.py) ou pro formato bem antigo.
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
                # Bucket novo: prioriza o caminho como chave definitiva quando
                # existe; cai para a própria chave do dia (formato antigo/manual)
                # se não houver URL.
                bucket = caminho_info or chave

            if caminho_info:
                caminho_para_bucket[caminho_info] = bucket
            texto_para_bucket[texto_info] = bucket

            if bucket not in historico_global:
                historico_global[bucket] = {}

            # Atualiza e preserva a URL válida (não vazia), além do nome/artista mais recentes
            if info.get("url"):
                historico_global[bucket]["url"] = info["url"]
            if info.get("nome"):
                historico_global[bucket]["nome"] = info["nome"]
            if info.get("artista"):
                historico_global[bucket]["artista"] = info["artista"]

            historico_global[bucket][data_str] = info["posicao"]

    dados_finais = {
        "datas": todas_datas,
        "musicas": historico_global
    }

    with open(f"dados_dashboard_{regiao}.json", "w", encoding="utf-8") as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=4)

def processar_regiao(regiao, config):
    print(f"🌍 Coletando dados da região: {config['nome']} ({regiao})...")
    
    # Garante as subpastas específicas da região
    pasta_dados_regiao = os.path.join(PASTA_DADOS, regiao)
    pasta_relatorios_regiao = os.path.join(PASTA_RELATORIOS, regiao)
    os.makedirs(pasta_dados_regiao, exist_ok=True)
    os.makedirs(pasta_relatorios_regiao, exist_ok=True)
    
    atuais = extrair_musicas(config['api_regiao'], config['dominio'])
    if not atuais:
        print(f"⚠️ Alerta: Nenhuma música coletada para {config['nome']}. API mudou ou bloqueio.")
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
            if i > 10: break
            conteudo_md += f"{i}º. **{m['nome']}** — *{m['artista']}*\n"
    else:
        # Índices de apoio pra achar a versão de "ontem" de cada música mesmo
        # quando o formato da chave difere entre os dois dias (ex.: ontem foi
        # uma captura manual sem link — chave "Nome - Artista" — e hoje o
        # robô trouxe a URL real, ou vice-versa; ou o domínio da URL mudou de
        # um dia pro outro). Sem isso, toda música de um dia com identidade
        # diferente do anterior aparece como "nova entrada" em vez de
        # calcular a diferença de posição de verdade.
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

        # ⚡ GUARDA CONTRA CACHE/BUG DO SITE: se NENHUMA música mudou de posição
        # em relação a ontem e apareceu no máximo 1 entrada nova, isso não é um
        # dia real "parado" — é o sintoma do bug de cache/CDN do site de
        # origem devolvendo a mesma resposta de ontem pro robô. Nesse caso não
        # salva nada hoje (nem o JSON bruto, nem os relatórios): assim
        # "buscar_dados_anteriores" continua enxergando o último dia bom de
        # verdade, em vez de gravar por cima com um dado provavelmente velho.
        if total_com_mudanca == 0 and len(novas_entradas) <= 1:
            print(
                f"⚠️ Suspeita de cache/bug do site para {config['nome']}: "
                f"0 músicas mudaram de posição e {len(novas_entradas)} entrada(s) nova(s) hoje. "
                f"Dados NÃO salvos — rode de novo mais tarde para tentar pegar dados reais."
            )
            return "ZERADO"

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

    # Salva os relatórios específicos da região
    with open(os.path.join(pasta_relatorios_regiao, f"relatorio_{data_hoje_iso}.md"), 'w', encoding='utf-8') as f:
        f.write(conteudo_md)
        
    # Relatório raiz específico da região (ex: relatorio_diario_ar.md)
    with open(f"relatorio_diario_{regiao}.md", 'w', encoding='utf-8') as f:
        f.write(conteudo_md)
        
    # Salva o JSON na subpasta correspondente
    with open(os.path.join(pasta_dados_regiao, f"dados_{data_hoje_iso}.json"), 'w', encoding='utf-8') as f:
        json.dump(atuais, f, ensure_ascii=False, indent=4)
        
    return True

if __name__ == "__main__":
    try:
        # Define o alvo baseado no argumento do terminal (ex: "br", "latam", ou "all")
        alvo = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
        
        if alvo == "br":
            regioes_para_processar = ["br"]
        elif alvo == "latam":
            regioes_para_processar = ["ar", "co", "sp", "es", "mx"]
        else:
            regioes_para_processar = list(REGIOES.keys())

        print(f"🚀 Iniciando módulo de análise para o alvo: {alvo.upper()}")

        sucesso_geral = True
        for regiao in regioes_para_processar:
            config = REGIOES[regiao]
            try:
                resultado = processar_regiao(regiao, config)
                if resultado is True:
                    atualizar_dados_dashboard(regiao)
                    print(f"✅ Região {regiao.upper()} processada com sucesso.\n")
                elif resultado == "ZERADO":
                    # Não é uma falha do robô — é o site tendo devolvido dado
                    # repetido/suspeito. Não conta como erro pra não disparar
                    # alarme falso, mas fica registrado no log pra rodar de
                    # novo depois.
                    print(f"⏭️ Região {regiao.upper()} pulada hoje (dados suspeitos de cache). Rode de novo mais tarde.\n")
                else:
                    sucesso_geral = False
            except Exception as e:
                print(f"\n💥 Erro ao processar a região {regiao.upper()}:")
                traceback.print_exc()
                sucesso_geral = False
        
        if sucesso_geral:
            print(f"🚀 Módulo executado com sucesso total para as regiões ({alvo.upper()})!")
        else:
            print("⚠️ Execução concluída com falhas parciais em algumas regiões.")
            sys.exit(1)
            
    except Exception as e:
        print("\n💥 --- ERRO CRÍTICO INESPERADO NO SCRIPT --- 💥")
        traceback.print_exc()
        sys.exit(1)
