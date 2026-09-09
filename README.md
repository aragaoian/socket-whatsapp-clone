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
