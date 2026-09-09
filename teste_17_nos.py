from __future__ import annotations

from report_tests import (
    Cluster,
    global_history,
    latest_status,
    same_histories,
    wait_for,
    wait_history,
    write_evidence,
)


def main() -> int:
    print("=" * 92)
    print("TESTE DE ESCALA — 17 NÓS SIMULTÂNEOS")
    print("=" * 92)
    print("Objetivo: comprovar que o sistema funciona com mais de 15 nós.")
    print()
    print("[TESTE] Iniciando 17 processos independentes nas portas 5001-5017...")

    with Cluster(17) as cluster:
        print("[OK] As 17 portas TCP estão acessíveis simultaneamente.")

        # Verifica o líder e o tamanho do relógio vetorial nos dois extremos
        # do catálogo de nós.
        cluster.send(1, "status")
        cluster.send(17, "status")

        wait_for(
            lambda: latest_status(cluster.nodes[1]) is not None
            and latest_status(cluster.nodes[17]) is not None,
            timeout=5,
            description="status dos Nodes 1 e 17",
        )

        status_1 = latest_status(cluster.nodes[1])
        status_17 = latest_status(cluster.nodes[17])
        assert status_1 is not None and status_17 is not None

        lider_ok = status_1[1] == 17 and status_17[1] == 17
        vetor_ok = len(status_1[2]) == 17 and len(status_17[2]) == 17

        print(f"[{'OK' if lider_ok else 'FALHOU'}] Node 17 reconhecido como líder inicial.")
        print(f"[{'OK' if vetor_ok else 'FALHOU'}] Relógio vetorial possui 17 posições.")

        print("[TESTE] Enviando mensagens de grupo concorrentes pelos Nodes 1, 9 e 17...")
        cluster.send_concurrent(
            {
                1: "sendall ESCALA17-N1",
                9: "sendall ESCALA17-N9",
                17: "sendall ESCALA17-N17",
            }
        )

        wait_history(cluster, 3, timeout=20)

        historicos = {
            node_id: global_history(cluster.nodes[node_id])
            for node_id in range(1, 18)
        }

        historicos_ok = same_histories(cluster.nodes.values()) and all(
            len(historico) == 3 for historico in historicos.values()
        )

        vetores_mensagens_ok = all(
            len(mensagem.vector) == 17
            for historico in historicos.values()
            for mensagem in historico
        )

        print(
            f"[{'OK' if historicos_ok else 'FALHOU'}] "
            "Os 17 nós possuem o mesmo histórico global."
        )
        print(
            f"[{'OK' if vetores_mensagens_ok else 'FALHOU'}] "
            "As mensagens entregues carregam vetores de 17 posições."
        )

        referencia = historicos[1]
        referencia_compacta = [mensagem.compact() for mensagem in referencia]

        corpo = [
            "Objetivo: comprovar execução real com mais de 15 instâncias simultâneas.",
            "",
            "O testador iniciou 17 processos independentes e confirmou que as portas TCP 5001-5017 ficaram acessíveis simultaneamente.",
            f"Status do Node 1: {status_1}",
            f"Status do Node 17: {status_17}",
            f"Node 17 reconhecido como líder inicial: {'SIM' if lider_ok else 'NÃO'}",
            f"Relógios vetoriais possuem 17 posições: {'SIM' if vetor_ok else 'NÃO'}",
            "",
            "Foram emitidas três mensagens sendall concorrentemente pelos Nodes 1, 9 e 17.",
            "Histórico global de referência (Node 1):",
            *[f"  {mensagem.full()}" for mensagem in referencia],
            "",
            "Comparação dos 17 históricos globais:",
        ]

        for node_id in range(1, 18):
            atual = [mensagem.compact() for mensagem in historicos[node_id]]
            corpo.append(
                f"Node {node_id:02d}: sequências "
                f"{[mensagem.sequence for mensagem in historicos[node_id]]} | "
                f"{'IDÊNTICO' if atual == referencia_compacta else 'DIVERGENTE'}"
            )

        aprovado = lider_ok and vetor_ok and historicos_ok and vetores_mensagens_ok

        corpo.extend(
            [
                "",
                "17 processos simultâneos confirmados: SIM",
                f"Históricos idênticos nos 17 nós: {'SIM' if historicos_ok else 'NÃO'}",
                f"Vetores das mensagens possuem 17 posições: {'SIM' if vetores_mensagens_ok else 'NÃO'}",
                f"RESULTADO: {'APROVADO' if aprovado else 'FALHOU'}",
            ]
        )

        caminho = write_evidence(
            "08_escala_17_nos.txt",
            "EVIDÊNCIA 8 — EXECUÇÃO E ORDEM TOTAL COM 17 NÓS",
            corpo,
        )

        if not aprovado:
            print()
            print(f"[FALHOU] Consulte a evidência em: {caminho}")
            return 1

    print()
    print("=" * 92)
    print("RESULTADO: APROVADO")
    print("O SISTEMA EXECUTOU 17 NÓS SIMULTÂNEOS COM ORDEM GLOBAL CONSISTENTE.")
    print("=" * 92)
    print("Evidência salva em: evidencias_relatorio/08_escala_17_nos.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
