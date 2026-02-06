# Jupyter-SSMS (TUI)

CLI/TUI estilo "tela preta" para navegar em bancos SQL Server via Linux, com setas e execucao de queries.

Versao: Io v0.06022026

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

## Teclas
- Setas: navegar
- Enter: selecionar/editar
- F2: conectar/executar query
- ESC: voltar/sair
- R: atualizar lista

## Notas
- Senha nao e salva no `config.json`.
- CRUD e feito via queries reais. O menu cria templates e voce edita antes de executar.
