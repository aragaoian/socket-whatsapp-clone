# socket-whatsapp-clone

Chat distribuído por sockets TCP com relógio vetorial, sequenciador global,
recuperação da ordem após troca de líder, eleição pelo algoritmo do Valentão e
snapshot de Chandy–Lamport.

Na inicialização, o maior ID ativo do catálogo assume a coordenação, de acordo
com o critério do algoritmo do Valentão. Se esse coordenador falhar, o maior ID
entre os sobreviventes é eleito.

## Execução

```bash
./start.sh --count 3
```

Comandos: `send`, `sendall`, `local`, `global`, `status`, `list`, `snapshot`,
`help` e `exit`. O comando `snapshot` captura e exibe um estado global consistente
dos nós ativos.

## Execução no Windows (PowerShell)

O projeto também pode ser executado nativamente no Windows, sem WSL, Konsole ou
uma VM.

Na primeira vez, abra o PowerShell na pasta do projeto e execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
```

O script instala/verifica `uv`, instala Python 3.12 e executa `uv sync --locked`
para criar o ambiente virtual e instalar as dependências do `uv.lock`.

Depois, inicie os nós com:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Count 3
```

Será aberta uma janela PowerShell para cada nó. O parâmetro `-Count` equivale ao
`--count` do `start.sh`. Pressione `Ctrl+C` na janela do launcher para encerrar
todos os nós.
