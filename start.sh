#!/usr/bin/env bash

set -u

count=3
terminal_pids=()
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Uso: $0 [--count N]"
}

cleanup() {
    trap - EXIT INT TERM HUP

    if ((${#terminal_pids[@]} > 0)); then
        echo
        echo "Encerrando os terminais..."

        for pid in "${terminal_pids[@]}"; do
            # Cada terminal foi iniciado em seu proprio grupo de processos.
            # Assim, o terminal e o comando executado dentro dele sao encerrados.
            kill -TERM -- "-$pid" 2>/dev/null || true
        done

        # Da aos processos a oportunidade de encerrar normalmente antes de
        # garantir que nenhum deles fique executando em segundo plano.
        sleep 0.5
        for pid in "${terminal_pids[@]}"; do
            if kill -0 -- "-$pid" 2>/dev/null; then
                kill -KILL -- "-$pid" 2>/dev/null || true
            fi
        done

        for pid in "${terminal_pids[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

while (($# > 0)); do
    case "$1" in
        --count|-c)
            if (($# < 2)); then
                echo "Erro: $1 precisa receber um valor." >&2
                usage >&2
                exit 2
            fi
            count="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Erro: parametro desconhecido: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "$count" =~ ^[1-9][0-9]*$ ]]; then
    echo "Erro: --count deve ser um numero inteiro maior que zero." >&2
    exit 2
fi

if ! command -v konsole >/dev/null 2>&1; then
    echo "Erro: o terminal 'konsole' nao esta instalado." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "Erro: o comando 'uv' nao esta instalado." >&2
    exit 1
fi

if ! command -v setsid >/dev/null 2>&1; then
    echo "Erro: o comando 'setsid' nao esta instalado." >&2
    exit 1
fi

for ((id = 1; id <= count; id++)); do
    setsid konsole --separate --workdir "$project_dir" \
        -e uv run lauch_node.py --id "$id" --count "$count"&
    terminal_pids+=("$!")
done

echo "$count terminais iniciados. Pressione Ctrl+C para encerrar todos."

# Mantem este script ativo enquanto houver terminais em execucao.
wait

# Se todos os terminais ja foram fechados manualmente, nao ha mais nada
# para o trap de saida encerrar.
terminal_pids=()