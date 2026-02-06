# Jupyter-SSMS (TUI)

CLI/TUI estilo "tela preta" para navegar em bancos SQL Server via Linux, com setas e execucao de queries.

Versao: Io v1.06022026  
Criado e desenvolvido por André Felipe Pinto © 2026

## Requisitos
- Linux Mint/Ubuntu
- Python 3
- Driver ODBC da Microsoft para SQL Server (ex: ODBC Driver 18)
- `unixodbc` instalado

## Instalar ODBC (Linux Mint/Ubuntu)
```bash
cd /home/andrefelipe/projetos/sqlserver-cli
./install_linux.sh
```
O instalador tambem cria um atalho na area de trabalho e no menu de aplicativos.
Inclui um icone exclusivo do Jupyter-SSMS.
Ele instala Python3, pip e pyodbc automaticamente.

## Instalar dependencias Python
```bash
cd /home/andrefelipe/projetos/sqlserver-cli
python3 -m pip install -r requirements.txt
```

## Executar
```bash
cd /home/andrefelipe/projetos/sqlserver-cli
python3 sqlserver_cli.py
```

## Layout (estilo SSMS)
- Esquerda: arvore (Server > Databases > Tables).
- Direita (topo): editor SQL.
- Direita (baixo): resultados.

## Teclas
- TAB: alternar foco (arvore/editor/resultados).
- Setas: navegar (em Results use ←/→ para colunas).
- Enter: editar query ou selecionar item.
- F1: ajuda.
- F2: conectar.
- F5: executar query.
- F6: salvar resultados em CSV (separador `;`, abre dialogo do sistema).
- ESC: voltar/sair.
- R: atualizar listas.

## Recursos
- Historico de conexoes no topo da tela inicial (selecionavel).
- Nome para conexoes (facilita reutilizar).
- Export CSV com `;` e UTF-8 BOM.
- Foco e clique com mouse (quando suportado pelo terminal).
- Nao precisa de `dbo` ao gerar query (o app muda para o DB correto).

## Configuracoes e logs
- Config: `~/.config/jupyter-ssms/config.json`
- Log: `~/.local/share/jupyter-ssms/jupyter_ssms.log`

## Notas
- Senha so e salva se `SalvarSenha` estiver ligado.
- CRUD e feito via queries reais. O menu cria templates e voce edita antes de executar.
