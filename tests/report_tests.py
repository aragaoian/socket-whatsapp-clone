from __future__ import annotations

import argparse
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT / "evidencias_relatorio"
ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
GLOBAL_RE = re.compile(
    r"\[GLOBAL (\d+)\] Node (\d+) \(local (\d+)\) \| "
    r"VClock (\[[^\]]*\]): (.*)"
)
LOCAL_RE = re.compile(r"\[LOCAL (\d+)\] para (.+?) \| VClock (\[[^\]]*\]): (.*)")
STATUS_RE = re.compile(
    r"Node (\d+) \| líder (\d+) \| VClock (\[[^\]]*\]) \| "
    r"próxima entrega global (\d+)"
)
PRIVATE_RE = re.compile(r"\[PRIVADA\].*?: (.*)")

VISUAL = False
VISUAL_SCENARIO = ""
ECHO_NODE_OUTPUT = True
PRINT_LOCK = threading.Lock()


def visual(message: str = "") -> None:
    if not VISUAL:
        return
    with PRINT_LOCK:
        print(message, flush=True)


def should_echo_node_line(node_id: int, line: str) -> bool:
    if not VISUAL or not ECHO_NODE_OUTPUT:
        return False

    # Exiba somente saídas úteis para a evidência. Heartbeats e prompts internos
    # ficam ocultos para o print não virar uma parede de texto.
    if VISUAL_SCENARIO == "order15":
        return node_id == 1 and "[GLOBAL " in line
    if VISUAL_SCENARIO == "private":
        return "[PRIVADA]" in line
    if VISUAL_SCENARIO == "snapshot":
        return node_id == 2 and (
            "--- ESTADO GLOBAL " in line
            or "--- FIM DO ESTADO GLOBAL ---" in line
            or (line.startswith("Node ") and "| líder " in line)
        )
    if VISUAL_SCENARIO == "election":
        return node_id in (1, 2) and any(
            tag in line
            for tag in (
                "[GLOBAL ",
                "[ELEIÇÃO]",
                "[RECUPERAÇÃO]",
                "[COORDENADOR]",
                "Líder não acessível",
            )
        )
    if VISUAL_SCENARIO in ("order3", "causal"):
        return "[GLOBAL " in line
    return False


@dataclass(frozen=True)
class GlobalMessage:
    sequence: int
    origin: int
    local_sequence: int
    vector: tuple[int, ...]
    message: str

    def compact(self) -> str:
        return f"{self.sequence}:N{self.origin}:{self.message}"

    def full(self) -> str:
        return (
            f"[GLOBAL {self.sequence}] Node {self.origin} (local {self.local_sequence}) "
            f"| VClock {list(self.vector)}: {self.message}"
        )


class NodeProcess:
    def __init__(self, node_id: int, count: int) -> None:
        self.id = node_id
        self.count = count
        self.lines: list[str] = []
        self._lock = threading.Lock()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("COLUMNS", "120")
        env.setdefault("LINES", "40")

        self.process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "lauch_node.py",
                "--id",
                str(node_id),
                "--count",
                str(count),
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        while True:
            chunk = self.process.stdout.readline()
            if chunk == "":
                break
            clean = ANSI_RE.sub("", chunk).replace("\r", "").strip()
            if not clean:
                continue
            # Prompts can be concatenated with output when stdin/stdout are pipes.
            clean = re.sub(r"^\d+>\s*", "", clean)
            if clean:
                with self._lock:
                    self.lines.append(clean)
                if should_echo_node_line(self.id, clean):
                    visual(f"[NODE {self.id}] {clean}")

    def command(self, command: str) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(f"Node {self.id} is not running")
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def snapshot_lines(self) -> list[str]:
        with self._lock:
            return self.lines.copy()

    def stop(self, force: bool = False) -> None:
        if self.process.poll() is not None:
            return
        try:
            if not force:
                self.command("exit")
                self.process.wait(timeout=2)
                return
        except (BrokenPipeError, RuntimeError, subprocess.TimeoutExpired):
            pass
        self.process.kill()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()


def parse_vector(text: str) -> tuple[int, ...]:
    inside = text.strip()[1:-1].strip()
    if not inside:
        return ()
    return tuple(int(item.strip()) for item in inside.split(","))


def global_history(node: NodeProcess) -> list[GlobalMessage]:
    by_seq: dict[int, GlobalMessage] = {}
    for line in node.snapshot_lines():
        for match in GLOBAL_RE.finditer(line):
            item = GlobalMessage(
                sequence=int(match.group(1)),
                origin=int(match.group(2)),
                local_sequence=int(match.group(3)),
                vector=parse_vector(match.group(4)),
                message=match.group(5).strip(),
            )
            by_seq[item.sequence] = item
    return [by_seq[key] for key in sorted(by_seq)]


def latest_status(node: NodeProcess) -> tuple[int, int, tuple[int, ...], int] | None:
    result = None
    for line in node.snapshot_lines():
        for match in STATUS_RE.finditer(line):
            result = (
                int(match.group(1)),
                int(match.group(2)),
                parse_vector(match.group(3)),
                int(match.group(4)),
            )
    return result


def wait_for(
    predicate: Callable[[], bool],
    timeout: float = 10.0,
    description: str = "condition",
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(f"Timeout waiting for {description}")


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def assert_ports_free(count: int) -> None:
    busy = [5000 + i for i in range(1, count + 1) if port_is_open(5000 + i)]
    if busy:
        raise RuntimeError(
            "As seguintes portas já estão ocupadas: "
            + ", ".join(map(str, busy))
            + ". Feche o start.ps1/nós que já estão rodando antes de executar os testes."
        )


class Cluster:
    def __init__(self, count: int) -> None:
        self.count = count
        self.nodes: dict[int, NodeProcess] = {}

    def __enter__(self) -> Cluster:
        assert_ports_free(self.count)
        try:
            for node_id in range(1, self.count + 1):
                self.nodes[node_id] = NodeProcess(node_id, self.count)
            wait_for(
                lambda: all(port_is_open(5000 + i) for i in range(1, self.count + 1)),
                timeout=max(8.0, self.count * 0.7),
                description=f"startup of {self.count} nodes",
            )
            # Let all accept/listener threads settle before issuing commands.
            time.sleep(0.4)
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        for node in self.nodes.values():
            node.stop()
        time.sleep(0.15)

    def send(self, node_id: int, command: str) -> None:
        self.nodes[node_id].command(command)

    def send_concurrent(self, commands: dict[int, str]) -> None:
        barrier = threading.Barrier(len(commands))
        errors: queue.Queue[BaseException] = queue.Queue()

        def worker(node_id: int, command: str) -> None:
            try:
                barrier.wait(timeout=3)
                self.send(node_id, command)
            except BaseException as exc:  # propagate thread errors to caller
                errors.put(exc)

        threads = [
            threading.Thread(target=worker, args=(node_id, command), daemon=True)
            for node_id, command in commands.items()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=4)
        if not errors.empty():
            raise errors.get()


def same_histories(nodes: Iterable[NodeProcess]) -> bool:
    histories = [global_history(node) for node in nodes]
    if not histories:
        return True
    reference = histories[0]
    return all(history == reference for history in histories[1:])


def wait_history(
    cluster: Cluster,
    expected: int,
    node_ids: Iterable[int] | None = None,
    timeout: float = 10.0,
) -> None:
    ids = list(node_ids or cluster.nodes.keys())
    wait_for(
        lambda: all(
            len(global_history(cluster.nodes[node_id])) >= expected for node_id in ids
        ),
        timeout=timeout,
        description=f"{expected} global messages on nodes {ids}",
    )


def write_evidence(filename: str, title: str, body: list[str]) -> Path:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    path = EVIDENCE_DIR / filename
    width = 92
    text = ["=" * width, title, "=" * width, *body, "=" * width]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    if VISUAL:
        visual("")
        visual(f"[TESTE] {title}")
        for line in body:
            if any(
                marker in line
                for marker in (
                    "Históricos idênticos",
                    "Somente o destinatário",
                    "Vetor de B incorpora A",
                    "Ordem global preserva A",
                    "Relatórios dos três",
                    "Novo líder é",
                    "Sequência continuou",
                    "RESULTADO:",
                )
            ):
                visual(f"[TESTE] {line}")
        visual(f"[TESTE] Evidência registrada em {path.name}")
    else:
        print("\n" + "\n".join(text) + "\n")
        print(f"Arquivo salvo em: {path}")
    return path


def scenario_order3() -> Path:
    global ECHO_NODE_OUTPUT
    visual("[TESTE] Subindo 3 processos independentes nas portas 5001-5003...")
    with Cluster(3) as c:
        ECHO_NODE_OUTPUT = False
        visual(
            "[TESTE] Nós ativos. Liberando 3 comandos sendall pela mesma barreira..."
        )
        c.send_concurrent(
            {
                1: "sendall CONCORRENTE-N1",
                2: "sendall CONCORRENTE-N2",
                3: "sendall CONCORRENTE-N3",
            }
        )
        wait_history(c, 3, timeout=8)
        visual(
            "[TESTE] As 3 mensagens foram entregues. Executando 'global' nos três nós..."
        )
        ECHO_NODE_OUTPUT = True
        for i in range(1, 4):
            c.send(i, "global")
        time.sleep(0.4)

        histories = {i: global_history(c.nodes[i]) for i in range(1, 4)}
        passed = same_histories(c.nodes.values()) and all(
            len(h) == 3 for h in histories.values()
        )
        body = [
            "Objetivo: demonstrar comunicação de grupo e ordem total em três processos independentes.",
            "Os três comandos sendall foram liberados por uma barreira de threads do testador.",
            "",
        ]
        for i in range(1, 4):
            body.append(f"--- ORDEM GLOBAL DO NODE {i} ---")
            body.extend(message.full() for message in histories[i])
        body.extend(
            [
                "",
                f"Históricos idênticos: {'SIM' if passed else 'NÃO'}",
                f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
            ]
        )
        if not passed:
            raise AssertionError("Históricos globais divergiram no cenário de 3 nós")
        return write_evidence(
            "01_ordem_total_3_nos.txt", "EVIDÊNCIA 1 — ORDEM TOTAL COM 3 NÓS", body
        )


def scenario_order15() -> Path:
    visual("[TESTE] Subindo 15 processos independentes nas portas 5001-5015...")
    with Cluster(15) as c:
        visual("[TESTE] 15 nós ativos. Liberando sendall concorrente nos Nodes 1-5...")
        c.send_concurrent(
            {
                1: "sendall ESCALA-N1",
                2: "sendall ESCALA-N2",
                3: "sendall ESCALA-N3",
                4: "sendall ESCALA-N4",
                5: "sendall ESCALA-N5",
            }
        )
        wait_history(c, 5, timeout=15)
        histories = {i: global_history(c.nodes[i]) for i in range(1, 16)}
        passed = same_histories(c.nodes.values()) and all(
            len(h) == 5 for h in histories.values()
        )
        reference = histories[1]
        body = [
            "Objetivo: demonstrar inicialização configurável com 15 processos e convergência da ordem global.",
            "Cinco nós emitiram mensagens de grupo concorrentes; todos os 15 receptores foram verificados.",
            "",
            "Histórico de referência (Node 1):",
            *[f"  {message.full()}" for message in reference],
            "",
            "Comparação dos 15 históricos:",
        ]
        reference_compact = [message.compact() for message in reference]
        if VISUAL:
            visual(
                "[TESTE] Comparando automaticamente as filas globais dos 15 processos:"
            )
        for i in range(1, 16):
            current = [message.compact() for message in histories[i]]
            comparison = (
                f"Node {i:02d}: sequências {[m.sequence for m in histories[i]]} | "
                f"{'IDÊNTICO' if current == reference_compact else 'DIVERGENTE'}"
            )
            body.append(comparison)
            if VISUAL:
                visual(f"[TESTE] {comparison}")
        body.extend(
            [
                "",
                f"Históricos idênticos nos 15 nós: {'SIM' if passed else 'NÃO'}",
                f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
            ]
        )
        if not passed:
            raise AssertionError("Históricos globais divergiram no cenário de 15 nós")
        return write_evidence(
            "02_ordem_total_15_nos.txt", "EVIDÊNCIA 2 — ORDEM TOTAL COM 15 NÓS", body
        )


def scenario_private() -> Path:
    visual("[TESTE] Subindo 3 processos e enviando unicast Node 1 -> Node 2...")
    with Cluster(3) as c:
        visual("[TESTE] Node 1: send 2 PRIVADA-N1-PARA-N2")
        c.send(1, "send 2 PRIVADA-N1-PARA-N2")
        wait_for(
            lambda: any(
                "[PRIVADA]" in line and "PRIVADA-N1-PARA-N2" in line
                for line in c.nodes[2].snapshot_lines()
            ),
            timeout=5,
            description="private message at node 2",
        )
        time.sleep(0.25)
        private_counts = {
            i: sum(
                1
                for line in c.nodes[i].snapshot_lines()
                if "[PRIVADA]" in line and "PRIVADA-N1-PARA-N2" in line
            )
            for i in range(1, 4)
        }
        global_counts = {i: len(global_history(c.nodes[i])) for i in range(1, 4)}
        node2_line = next(
            line
            for line in c.nodes[2].snapshot_lines()
            if "[PRIVADA]" in line and "PRIVADA-N1-PARA-N2" in line
        )
        passed = private_counts == {1: 0, 2: 1, 3: 0} and global_counts == {
            1: 0,
            2: 0,
            3: 0,
        }
        body = [
            "Comando emitido pelo Node 1: send 2 PRIVADA-N1-PARA-N2",
            "",
            f"Node 2 recebeu: {node2_line}",
            f"Ocorrências da mensagem privada: Node 1={private_counts[1]}, Node 2={private_counts[2]}, Node 3={private_counts[3]}",
            f"Mensagens na ordem global: Node 1={global_counts[1]}, Node 2={global_counts[2]}, Node 3={global_counts[3]}",
            "",
            f"Somente o destinatário recebeu e a mensagem não entrou na ordem global: {'SIM' if passed else 'NÃO'}",
            f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
        ]
        if not passed:
            raise AssertionError("Falha no cenário de mensagem privada")
        return write_evidence(
            "03_mensagem_privada.txt", "EVIDÊNCIA 3 — MENSAGEM PRIVADA UNICAST", body
        )


def scenario_causal() -> Path:
    visual("[TESTE] Subindo 3 processos para o cenário causal...")
    with Cluster(3) as c:
        visual("[TESTE] Node 1 emite CAUSAL-A")
        c.send(1, "sendall CAUSAL-A")
        # Important: B is emitted only after Node 2 has delivered A.
        wait_for(
            lambda: any(m.message == "CAUSAL-A" for m in global_history(c.nodes[2])),
            timeout=6,
            description="delivery of CAUSAL-A at node 2",
        )
        visual("[TESTE] Node 2 entregou CAUSAL-A; somente agora Node 2 emite CAUSAL-B")
        c.send(2, "sendall CAUSAL-B")
        wait_history(c, 2, timeout=8)
        histories = {i: global_history(c.nodes[i]) for i in range(1, 4)}
        reference = histories[1]
        a = next(m for m in reference if m.message == "CAUSAL-A")
        b = next(m for m in reference if m.message == "CAUSAL-B")
        dominates = (
            all(x <= y for x, y in zip(a.vector, b.vector)) and a.vector != b.vector
        )
        ordered = a.sequence < b.sequence
        passed = same_histories(c.nodes.values()) and dominates and ordered
        body = [
            "Procedimento controlado:",
            "1. Node 1 emitiu CAUSAL-A.",
            "2. O testador aguardou a ENTREGA de CAUSAL-A no Node 2.",
            "3. Somente então o Node 2 emitiu CAUSAL-B.",
            "Logo, a emissão de B ocorre causalmente após a observação de A (A -> B).",
            "",
            f"A: sequência global {a.sequence}, VClock {list(a.vector)}",
            f"B: sequência global {b.sequence}, VClock {list(b.vector)}",
            f"Vetor de B incorpora A (A <= B componente a componente): {'SIM' if dominates else 'NÃO'}",
            f"Ordem global preserva A antes de B: {'SIM' if ordered else 'NÃO'}",
            "",
        ]
        for i in range(1, 4):
            body.append(f"Node {i}: " + " | ".join(m.compact() for m in histories[i]))
        body.extend(["", f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}"])
        if not passed:
            raise AssertionError("Falha no cenário de dependência causal")
        return write_evidence(
            "04_dependencia_causal.txt", "EVIDÊNCIA 4 — DEPENDÊNCIA CAUSAL", body
        )


def extract_snapshot_block(lines: list[str]) -> list[str]:
    start = None
    end = None
    for idx, line in enumerate(lines):
        if "--- ESTADO GLOBAL " in line:
            start = idx
        if start is not None and "--- FIM DO ESTADO GLOBAL ---" in line:
            end = idx
            break
    if start is None or end is None:
        return []
    return lines[start : end + 1]


def scenario_snapshot() -> Path:
    visual("[TESTE] Subindo 3 processos para captura Chandy-Lamport...")
    with Cluster(3) as c:
        c.send(1, "sendall SNAPSHOT-ANTES-1")
        wait_history(c, 1, timeout=6)
        c.send(2, "sendall SNAPSHOT-ANTES-2")
        wait_history(c, 2, timeout=6)
        visual("[TESTE] Node 2 executa: snapshot")
        c.send(2, "snapshot")
        wait_for(
            lambda: bool(extract_snapshot_block(c.nodes[2].snapshot_lines())),
            timeout=10,
            description="completed Chandy-Lamport snapshot",
        )
        block = extract_snapshot_block(c.nodes[2].snapshot_lines())
        nodes_reported = {
            int(match.group(1))
            for line in block
            if (match := re.search(r"^Node (\d+) \| líder", line))
        }
        passed = nodes_reported == {1, 2, 3}
        body = [
            "Comando executado no Node 2: snapshot",
            "",
            *block,
            "",
            f"Relatórios dos três participantes presentes: {'SIM' if passed else 'NÃO'}",
            f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
        ]
        if not passed:
            raise AssertionError("Snapshot não agregou os três participantes")
        return write_evidence(
            "05_snapshot_estado_global.txt",
            "EVIDÊNCIA 5 — ESTADO GLOBAL (CHANDY–LAMPORT)",
            body,
        )


def scenario_election() -> Path:
    visual("[TESTE] Subindo Nodes 1, 2 e 3; o maior ID deve iniciar como líder...")
    with Cluster(3) as c:
        c.send(1, "sendall ANTES-FALHA-1")
        wait_history(c, 1, timeout=6)
        c.send(2, "sendall ANTES-FALHA-2")
        wait_history(c, 2, timeout=6)
        before = [m.compact() for m in global_history(c.nodes[1])]

        visual("[TESTE] Encerrando à força o processo do Node 3 (líder)...")
        c.nodes[3].stop(force=True)
        time.sleep(0.25)
        # This send attempts to contact the dead coordinator and triggers election immediately.
        visual(
            "[TESTE] Node 1 tenta sendall APOS-REELEICAO; a falha deve disparar a eleição..."
        )
        c.send(1, "sendall APOS-REELEICAO")

        wait_for(
            lambda: any(
                "[COORDENADOR] Node 2 é o novo líder." in line
                for line in c.nodes[2].snapshot_lines()
            ),
            timeout=10,
            description="Node 2 becoming coordinator",
        )
        wait_history(c, 3, node_ids=[1, 2], timeout=10)
        c.send(1, "status")
        c.send(2, "status")

        # No Windows a saída dos processos pode demorar um pouco mais para chegar
        # ao pipe. Aguarde os dois status finais em vez de usar um sleep fixo.
        status_deadline = time.monotonic() + 3.0
        s1 = s2 = None
        while time.monotonic() < status_deadline:
            s1 = latest_status(c.nodes[1])
            s2 = latest_status(c.nodes[2])
            if s1 is not None and s2 is not None and s1[1] == 2 and s2[1] == 2:
                break
            time.sleep(0.05)

        h1 = global_history(c.nodes[1])
        h2 = global_history(c.nodes[2])

        # O anúncio COORDENADOR recebido/emitido pelos dois sobreviventes é uma
        # confirmação explícita da eleição. Em modo visual, o volume de escrita
        # concorrente no console do Windows pode atrasar a resposta do comando
        # `status`, gerando um falso negativo mesmo após a eleição já ter sido
        # concluída. Aceite o status final OU os dois anúncios explícitos.
        status_leaders_ok = (
            s1 is not None and s2 is not None and s1[1] == 2 and s2[1] == 2
        )
        coordinator_announced = all(
            any(
                "[COORDENADOR] Node 2 é o novo líder." in line
                for line in c.nodes[node_id].snapshot_lines()
            )
            for node_id in (1, 2)
        )
        leaders_ok = status_leaders_ok or coordinator_announced
        histories_ok = h1 == h2 and [m.sequence for m in h1] == [1, 2, 3]
        passed = leaders_ok and histories_ok

        relevant = []
        for node_id in (1, 2):
            for line in c.nodes[node_id].snapshot_lines():
                if any(
                    tag in line
                    for tag in (
                        "[ELEIÇÃO]",
                        "[RECUPERAÇÃO]",
                        "[COORDENADOR]",
                        "Líder não acessível",
                    )
                ):
                    relevant.append(f"Node {node_id}: {line}")
        # Deduplicate repeated status/noise while preserving order.
        relevant = list(dict.fromkeys(relevant))

        body = [
            "Líder inicial esperado: Node 3 (maior ID ativo).",
            f"Prefixo global antes da falha: {before}",
            "Ação do testador: encerramento forçado do processo do Node 3.",
            "Em seguida, Node 1 emitiu sendall APOS-REELEICAO, disparando a detecção da falha.",
            "",
            "Trechos observados durante eleição/recuperação:",
            *[f"  {line}" for line in relevant[-12:]],
            "",
            f"Status final Node 1: {s1}",
            f"Status final Node 2: {s2}",
            "Histórico final Node 1:",
            *[f"  {m.full()}" for m in h1],
            "Histórico final Node 2:",
            *[f"  {m.full()}" for m in h2],
            "",
            f"Novo líder é Node 2 em ambos os sobreviventes: {'SIM' if leaders_ok else 'NÃO'}",
            f"Sequência continuou em [1, 2, 3], sem reiniciar: {'SIM' if histories_ok else 'NÃO'}",
            f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
        ]
        # Grave a evidência mesmo quando o cenário falhar; assim o diagnóstico
        # contém os status finais e os históricos dos dois sobreviventes.
        path = write_evidence(
            "06_reeleicao_lider.txt",
            "EVIDÊNCIA 6 — QUEDA DO LÍDER, ELEIÇÃO E CONTINUIDADE",
            body,
        )
        if not passed:
            raise AssertionError(
                "Falha no cenário de reeleição/continuidade da ordem "
                f"(leaders_ok={leaders_ok}, histories_ok={histories_ok}); veja {path.name}"
            )
        return path


def scenario_unit_tests() -> Path:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip().splitlines()
    passed = completed.returncode == 0
    body = [
        "Suíte automatizada versionada no repositório:",
        "python -m unittest discover -s tests -v",
        "",
        *output,
        "",
        f"RESULTADO: {'APROVADO' if passed else 'FALHOU'}",
    ]
    path = write_evidence(
        "07_testes_unitarios.txt", "EVIDÊNCIA 7 — SUÍTE AUTOMATIZADA", body
    )
    if not passed:
        raise AssertionError("A suíte unittest falhou")
    return path


SCENARIOS: dict[str, Callable[[], Path]] = {
    "order3": scenario_order3,
    "order15": scenario_order15,
    "private": scenario_private,
    "causal": scenario_causal,
    "snapshot": scenario_snapshot,
    "election": scenario_election,
    "unit": scenario_unit_tests,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Executa cenários reproduzíveis e gera evidências textuais para o relatório."
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=["all", *SCENARIOS.keys()],
        help="cenário a executar (padrão: all)",
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help="exibe ao vivo as saídas relevantes dos processos para screenshots do relatório",
    )
    args = parser.parse_args()

    global VISUAL, VISUAL_SCENARIO
    VISUAL = args.visual

    EVIDENCE_DIR.mkdir(exist_ok=True)
    selected = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    summary: list[str] = []
    failed = False

    for name in selected:
        VISUAL_SCENARIO = name
        if VISUAL:
            visual("\n" + "=" * 92)
            visual(f"EXECUÇÃO VISUAL — CENÁRIO {name}")
            visual("=" * 92)
        else:
            print(f"\n>>> Executando cenário: {name}")
        try:
            path = SCENARIOS[name]()
            summary.append(f"[OK] {name}: {path.name}")
        except Exception as exc:
            failed = True
            summary.append(f"[FALHOU] {name}: {type(exc).__name__}: {exc}")
            print(summary[-1], file=sys.stderr)
            # Ensure a failed cluster has had time to release its ports.
            time.sleep(0.5)

    summary_path = EVIDENCE_DIR / "00_resumo.txt"
    summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n" + "=" * 92)
    print("RESUMO FINAL")
    print("=" * 92)
    print("\n".join(summary))
    print(f"\nEvidências: {EVIDENCE_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
