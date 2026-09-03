#!/usr/bin/env python3
"""
Reduz um arquivo .har, mantendo apenas um intervalo de entradas
(requisição/resposta) de log.entries.

Uso:
    python reduzir_har.py progressofit.har
    python reduzir_har.py progressofit.har -n 2 -o saida.har
    python reduzir_har.py progressofit.har --from 3 -n 5
    python reduzir_har.py progressofit.har --from 3 --to 7
"""
import json
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Reduz um arquivo .har a um intervalo de entradas.")
    parser.add_argument("arquivo", help="Caminho do arquivo .har original")
    parser.add_argument("--from", dest="inicio", type=int, default=0,
                         help="Índice da primeira entrada a manter (padrão: 0)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-n", "--num", type=int, default=None,
                        help="Quantidade de entradas a manter a partir de --from (padrão: 2 se --to não for usado)")
    group.add_argument("--to", dest="fim", type=int, default=None,
                        help="Índice da última entrada a manter (inclusive), alternativa a -n/--num")
    parser.add_argument("-o", "--output", default=None,
                         help="Nome do arquivo de saída (padrão: <arquivo>_reduzido.har)")
    args = parser.parse_args()

    if args.fim is not None:
        num = args.fim - args.inicio + 1
        if num <= 0:
            print(f"Erro: --to ({args.fim}) precisa ser >= --from ({args.inicio}).", file=sys.stderr)
            sys.exit(1)
    else:
        num = args.num if args.num is not None else 2

    saida = args.output or args.arquivo.rsplit(".", 1)[0] + "_reduzido.har"

    print(f"Lendo {args.arquivo} ...")
    try:
        with open(args.arquivo, "r", encoding="utf-8") as f:
            har = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Erro: o arquivo não é um JSON válido ({e}).", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Erro: arquivo '{args.arquivo}' não encontrado.", file=sys.stderr)
        sys.exit(1)

    entries = har.get("log", {}).get("entries", [])
    total = len(entries)
    print(f"Total de entradas encontradas: {total}")

    selecionadas = entries[args.inicio: args.inicio + num]
    har["log"]["entries"] = selecionadas

    with open(saida, "w", encoding="utf-8") as f:
        json.dump(har, f, ensure_ascii=False, indent=2)

    print(f"Arquivo reduzido salvo em: {saida}")
    print(f"Mantidas {len(selecionadas)} de {total} entradas (índices {args.inicio} a {args.inicio + len(selecionadas) - 1}).")


if __name__ == "__main__":
    main()
