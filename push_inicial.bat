@echo off
REM ============================================================
REM push_inicial.bat
REM Inicializa git, faz commit e push pro repo Projeto-Final-IoT
REM Para usar: clique duas vezes neste arquivo.
REM ============================================================

setlocal
cd /d "%~dp0"

echo === Verificando git...
where git >nul 2>nul
if errorlevel 1 (
    echo ERRO: git nao esta instalado.
    echo Baixe em: https://git-scm.com/download/win
    pause
    exit /b 1
)

if exist ".git" (
    echo === .git ja existe; pulando init.
) else (
    echo === Inicializando repositorio...
    git init -b main
    if errorlevel 1 goto :erro
)

echo === Configurando autor...
git config user.email "henriquemanequini@gmail.com"
git config user.name "Henrique Manequini"

echo === Configurando remote...
git remote remove origin >nul 2>nul
git remote add origin https://github.com/henriquemanequini/Projeto-Final-IoT.git

echo === Adicionando arquivos...
git add -A
if errorlevel 1 goto :erro

echo === Criando commit...
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "feat: pivot AWS managed -^> EC2 self-hosted (Mosquitto+SQLite)"
    if errorlevel 1 goto :erro
) else (
    echo === Nada novo pra commitar.
)

echo === Fazendo push (vai pedir login do GitHub na primeira vez)...
git push -u origin main
if errorlevel 1 goto :erro

echo.
echo ============================================================
echo  Push concluido! Veja em:
echo  https://github.com/henriquemanequini/Projeto-Final-IoT
echo ============================================================
pause
exit /b 0

:erro
echo.
echo === ERRO no comando acima. Veja a mensagem em vermelho.
pause
exit /b 1
