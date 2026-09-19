"""
resetar_hoje.py

Apaga os dados de HOJE (historico_dados/*/dados_{hoje}.json e
historico_relatorios/*/relatorio_{hoje}.md, pra todas as regiões), roda o
analisador.py de novo do zero pra recoletar o top atual do site, e sobe o
resultado pro GitHub (commit + push).

Use isso quando desconfiar que a coleta de hoje saiu errada/incompleta (tipo
o caso do MX no dia 17/09) e quiser forçar puxar de novo, limpo.

COMO USAR:
1. Coloque este arquivo na MESMA pasta do analisador.py (a raiz do repositório
   clonado localmente).
2. Confira que tem instalado: `pip install requests beautifulsoup4`
3. Confira que o `git` nessa pasta já está logado/autenticado com permissão
   de push pro repositório (senão o push no final vai falhar).
4. No terminal do VS Code, dentro dessa pasta, rode:
       python resetar_hoje.py
   Ele vai mostrar o que apagou, rodar a coleta, mostrar o que mudou (git
   status) e pedir uma confirmação antes de comitar e dar push.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# Fuso de Brasília fixo (Brasil não observa horário de verão desde 2019) —
# evita depender do pacote tzdata, que o Windows não traz por padrão.
BRT = timezone(timedelta(hours=-3))


def hoje_str():
    return datetime.now(BRT).strftime("%Y-%m-%d")


def apagar_dia(analisador, hoje):
    apagados = []
    for regiao in analisador.REGIOES:
        candidatos = [
            os.path.join(analisador.PASTA_DADOS, regiao, f"dados_{hoje}.json"),
            os.path.join(analisador.PASTA_RELATORIOS, regiao, f"relatorio_{hoje}.md"),
        ]
        for caminho in candidatos:
            if os.path.exists(caminho):
                os.remove(caminho)
                apagados.append(caminho)
    return apagados


def rodar_analisador():
    print("\n🚀 Rodando o analisador.py de novo (puxando o top atual do site)...\n")
    resultado = subprocess.run([sys.executable, "analisador.py", "all"])
    if resultado.returncode != 0:
        print(
            "\n⚠️ O analisador.py terminou com erro (veja o log acima). "
            "Não vou continuar pro git — resolve o problema e roda o script de novo."
        )
        sys.exit(1)


def git(*args):
    return subprocess.run(["git", *args], check=False)


def subir_pro_git(hoje):
    print("\n📋 Alterações detectadas pelo git:\n")
    subprocess.run(["git", "status", "--short"])

    resposta = input(
        f"\nConfirma o commit e push dessas alterações (dado de {hoje} recoletado)? [s/N] "
    ).strip().lower()
    if resposta != "s":
        print("Cancelado — nada foi commitado nem enviado.")
        return

    git("add", "-A")
    commit = git("commit", "-m", f"Recoleta manual do dia {hoje}")
    if commit.returncode != 0:
        print("Não havia nada novo pra commitar (o resultado deve ter ficado igual ao anterior).")
        return

    push = git("push")
    if push.returncode != 0:
        print(
            "\n⚠️ O commit foi feito localmente, mas o push falhou — "
            "confira sua conexão/login com o GitHub e rode 'git push' manualmente."
        )
        sys.exit(1)

    print(f"\n✅ Pronto! Dado de {hoje} recoletado e enviado pro GitHub.")


def main():
    if not os.path.exists("analisador.py"):
        print(
            "❌ Não encontrei o analisador.py nesta pasta. Rode este script "
            "de dentro da pasta do repositório (onde está o analisador.py)."
        )
        sys.exit(1)

    sys.path.insert(0, os.getcwd())
    import analisador  # importa o analisador.py real desta pasta

    hoje = hoje_str()
    print(f"📅 Recoletando o dia de hoje: {hoje}\n")

    apagados = apagar_dia(analisador, hoje)
    if apagados:
        print("🗑️  Apagado:")
        for a in apagados:
            print("   -", a)
    else:
        print("ℹ️  Não havia dado de hoje salvo ainda — vou coletar direto.")

    rodar_analisador()
    subir_pro_git(hoje)


if __name__ == "__main__":
    main()
